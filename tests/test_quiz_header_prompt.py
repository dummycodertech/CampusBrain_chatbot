"""
Tests for:
1. Quiz answer checking and JSON extraction (generation/quiz.py & components/chat_box.py)
2. Groq rate-limit header parsing (services/llm_client.py)
3. Per-session prompt cap enforcement (services/llm_client.py)
"""
import os
from unittest.mock import MagicMock, patch
import pytest

from components.chat_box import check_quiz_answer, _extract_letter_and_text
from generation.json_utils import extract_json
from generation.quiz import generate_quiz
import services.llm_client as llmc


# ── 1. Quiz Tests ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "selected,correct,expected",
    [
        ("A. Stack", "A", True),
        ("A. Stack", "A. Stack", True),
        ("(A) Stack", "A", True),
        ("Option A: Queue", "A", True),
        ("A", "A", True),
        ("a", "A", True),
        ("B. Tree", "A. Stack", False),
        ("Option B", "Option A", False),
        ("Stack", "Stack", True),
        ("stack", "Stack", True),
        ("", "A", False),
        ("A", "", False),
        ("Option (C) Binary Search", "C. Binary Search", True),
        ("D. None of the above", "D", True),
    ],
)
def test_check_quiz_answer_matching(selected, correct, expected):
    assert check_quiz_answer(selected, correct) is expected


def test_extract_letter_and_text():
    assert _extract_letter_and_text("A. Stack") == ("A", "stack")
    assert _extract_letter_and_text("(B) Queue") == ("B", "queue")
    assert _extract_letter_and_text("Option C: Graph") == ("C", "graph")
    assert _extract_letter_and_text("D") == ("D", "")
    assert _extract_letter_and_text("Just plain text") == (None, "just plain text")
    assert _extract_letter_and_text("") == (None, "")


def test_quiz_json_extraction():
    fenced = '```json\n{"quiz": [{"question": "Q1", "options": ["A", "B"], "correct_answer": "A"}]}\n```'
    parsed = extract_json(fenced)
    assert isinstance(parsed, dict)
    assert "quiz" in parsed
    assert len(parsed["quiz"]) == 1

    fenced_no_lang = '```\n{"quiz": []}\n```'
    assert extract_json(fenced_no_lang) == {"quiz": []}

    raw = 'Some thought text {"quiz": [{"q": 1}]} end comments'
    assert extract_json(raw) == {"quiz": [{"q": 1}]}

    list_json = '```json\n[{"term": "T", "def": "D"}]\n```'
    assert isinstance(extract_json(list_json), list)


# ── 2. Header-Name Tests ──────────────────────────────────────────────────────

def test_groq_header_name_parsing():
    """Verify rate-limit headers are captured case-insensitively and saved."""
    # Reset tracking state for test
    with llmc._rate_info_lock:
        llmc._rate_info.clear()

    # Mixed-case headers from HTTP response
    headers = {
        "X-RateLimit-Limit-Requests": "1000",
        "X-RateLimit-Remaining-Requests": "995",
        "x-ratelimit-reset-requests": "2m30s",
        "X-RateLimit-Limit-Tokens": "100000",
        "x-ratelimit-remaining-tokens": "95000",
        "X-RateLimit-Reset-Tokens": "1s",
        "Content-Type": "application/json",
        "Date": "Sat, 10 Oct 2026 12:00:00 GMT",
    }

    llmc._update_rate_info(headers)
    info = llmc.get_rate_info()

    assert info["x-ratelimit-limit-requests"] == "1000"
    assert info["x-ratelimit-remaining-requests"] == "995"
    assert info["x-ratelimit-reset-requests"] == "2m30s"
    assert info["x-ratelimit-limit-tokens"] == "100000"
    assert info["x-ratelimit-remaining-tokens"] == "95000"
    assert info["x-ratelimit-reset-tokens"] == "1s"

    # Non-tracked headers should NOT be present
    assert "content-type" not in info
    assert "date" not in info


# ── 3. Prompt-Cap Tests ───────────────────────────────────────────────────────

def test_prompt_cap_enforcement_and_increment():
    """Verify prompt limit guard prevents API calls when session cap is reached."""
    class FakeSessionState(dict):
        def __getattr__(self, name):
            if name in self:
                return self[name]
            raise AttributeError(name)
        def __setattr__(self, name, val):
            self[name] = val

    fake_session_state = FakeSessionState(prompts_used=2)

    mock_client = MagicMock()
    mock_raw = MagicMock()
    mock_raw.headers = {}
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Mocked answer"), finish_reason="stop")]
    mock_raw.parse.return_value = mock_resp
    mock_client.chat.completions.with_raw_response.create.return_value = mock_raw

    with patch.dict(os.environ, {"MAX_PROMPTS_PER_SESSION": "3"}), \
         patch("streamlit.runtime.exists", return_value=True), \
         patch("streamlit.session_state", fake_session_state), \
         patch("streamlit.warning") as mock_warning, \
         patch("services.llm_client.get_groq_client", return_value=mock_client), \
         patch("services.llm_client._get_active_model_chain", return_value=["openai/gpt-oss-120b"]):

        # Call 1: prompts_used is 2, limit is 3 -> allowed, increments to 3
        res1 = llmc.generate_text("test prompt 1")
        assert res1 == "Mocked answer"
        assert fake_session_state["prompts_used"] == 3
        assert mock_client.chat.completions.with_raw_response.create.call_count == 1

        # Call 2: prompts_used is 3, limit is 3 -> blocked!
        res2 = llmc.generate_text("test prompt 2")
        assert "reached your session limit" in res2
        assert fake_session_state["prompts_used"] == 3  # Not incremented past limit
        # The Groq API must NOT have been called a second time
        assert mock_client.chat.completions.with_raw_response.create.call_count == 1
        mock_warning.assert_called_once()
