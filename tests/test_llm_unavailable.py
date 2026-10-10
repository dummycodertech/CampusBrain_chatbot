"""
Unit tests for LLMUnavailableError propagation.

Tests that when generate_text raises LLMUnavailableError, every generation
module returns a friendly message and does NOT crash.

Run with:
    pytest tests/test_llm_unavailable.py -v
"""
import sys
import pathlib
import pytest
from unittest.mock import patch, MagicMock

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.llm_client import LLMUnavailableError

# ── Shared stub text ──────────────────────────────────────────────────────────
_PAPER = "Q1. Explain deadlock. [10M]\nQ2. Describe paging. [10M]"


def _always_raises(*args, **kwargs):
    raise LLMUnavailableError("mocked: all models unavailable")


# ── summary ───────────────────────────────────────────────────────────────────
def test_summarize_paper_returns_friendly_msg_on_llm_error():
    from generation.summary import summarize_paper
    with patch("generation.summary.generate_text", side_effect=_always_raises):
        result = summarize_paper(_PAPER)
    assert isinstance(result, str)
    assert len(result) > 10, "Expected a non-empty friendly message"
    # Must not be blank
    assert result.strip() != ""


# ── quiz ──────────────────────────────────────────────────────────────────────
def test_generate_quiz_returns_error_card_on_llm_error():
    from generation.quiz import generate_quiz
    with patch("generation.quiz.generate_text", side_effect=_always_raises):
        result = generate_quiz(_PAPER)
    assert "quiz" in result
    assert isinstance(result["quiz"], list)
    assert len(result["quiz"]) >= 1
    # The error card question must mention something useful
    q_text = result["quiz"][0]["question"]
    assert q_text.strip() != ""


# ── flashcards ────────────────────────────────────────────────────────────────
def test_generate_flashcards_returns_friendly_card_on_llm_error():
    from generation.flashcards import generate_flashcards
    with patch("generation.flashcards.generate_text", side_effect=_always_raises):
        result = generate_flashcards(_PAPER)
    assert "flashcards" in result
    assert len(result["flashcards"]) >= 1
    assert result["flashcards"][0]["definition"].strip() != ""


# ── answer_checker ────────────────────────────────────────────────────────────
def test_check_answer_returns_friendly_msg_on_llm_error():
    from generation.answer_checker import check_answer
    with patch("generation.answer_checker.generate_text", side_effect=_always_raises):
        result = check_answer(_PAPER, "What is deadlock?", "Deadlock is a state.")
    assert isinstance(result, str)
    assert result.strip() != ""


# ── qa: knowledge_answer ──────────────────────────────────────────────────────
def test_knowledge_answer_returns_friendly_msg_on_llm_error():
    from generation.qa import knowledge_answer
    # Also stub web search so we don't need a Tavily key
    with patch("generation.qa.search_web", return_value=[]), \
         patch("generation.qa.generate_text", side_effect=_always_raises):
        result = knowledge_answer("Explain deadlock")
    assert isinstance(result, str)
    assert result.strip() != ""


# ── qa: answer_question ───────────────────────────────────────────────────────
def test_answer_question_returns_friendly_msg_on_llm_error():
    from generation.qa import answer_question
    with patch("generation.qa.generate_text", side_effect=_always_raises):
        result = answer_question(_PAPER, "Which topics are covered?")
    assert isinstance(result, str)
    assert result.strip() != ""


# ── generate_text raises, not returns empty ────────────────────────────────────
def test_generate_text_raises_on_all_models_failing():
    """generate_text must raise LLMUnavailableError, not return empty string."""
    from unittest.mock import MagicMock
    import services.llm_client as llmc

    # Build a mock client whose chat.completions.create always raises
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("network error")
    # Stub models.list so _get_active_model_chain does not need a real key
    mock_client.models.list.return_value = MagicMock(data=[])

    with patch("services.llm_client.get_groq_client", return_value=mock_client), \
         patch("services.llm_client._get_active_model_chain", return_value=["openai/gpt-oss-120b"]):
        with pytest.raises(LLMUnavailableError):
            llmc.generate_text("hello")
