"""Quiz generator for Campus Brain.

The input is a Previous Year Question (PYQ) paper — it contains only exam
questions, not answers.  The prompt treats the paper as a topic/syllabus signal
and generates NEW practice MCQs on those same topics, with correct answers
supplied from the LLM's own academic knowledge.

This is deliberately better than the paper itself: a student gets fresh
practice questions on exactly the topics their exam covers.
"""
import json
import re
from services.llm_client import generate_text

QUIZ_PROMPT = """You are an expert exam tutor for university students.
The text below is a Previous Year Question (PYQ) paper — it contains ONLY
exam questions, not answers or explanations.

Your job:
1. Read the questions to identify the key topics and concepts this exam covers.
2. Generate 5 NEW multiple-choice practice questions on those same topics.
3. Provide the correct answer for each question using YOUR academic knowledge
   (not from the paper — it has no answers).

--- PYQ PAPER TEXT ---
{paper_text}
--- END PYQ PAPER TEXT ---

Rules:
- Each question must be clear, unambiguous, and exam-appropriate.
- Options A–D should be plausible; only one should be correct.
- "correct_answer" must be the FULL option text (e.g. "A. O(n log n)"), not just "A".
- Cover a range of topics from the paper, not just one.
- Return ONLY valid JSON, no other text, in this exact shape:
{{"quiz": [
  {{"question": "...", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], "correct_answer": "A. ..."}}
]}}"""


def _extract_json(raw: str) -> str:
    """Robustly extract the first JSON object from raw LLM output.

    Handles:
    - Bare JSON with no fences
    - ```json ... ``` or ``` ... ``` fences (with or without trailing newlines)
    - Extra explanation text before/after the JSON block
    - Numerical values, special characters, graph notation in the paper text
    """
    # 1. Try stripping a markdown code fence (most common case)
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            return candidate
        except Exception:
            pass

    # 2. Try finding a JSON object directly (greedy, from first { to last })
    obj_match = re.search(r"(\{[\s\S]*\})", raw)
    if obj_match:
        return obj_match.group(1).strip()

    # 3. Fallback: return the whole thing stripped and hope for the best
    return raw.strip()


def generate_quiz(paper_text: str) -> dict:
    """Generate a 5-question MCQ quiz from a PYQ paper.

    Returns a dict with key ``quiz`` containing a list of question dicts.
    On any JSON parse failure, returns a single-item quiz with an error
    message so the UI never crashes.
    """
    raw = generate_text(QUIZ_PROMPT.format(paper_text=paper_text))

    if not raw or not raw.strip():
        return {"quiz": [{"question": "Quiz generation failed — the AI returned an empty response. Please try again.",
                          "options": ["A. Retry", "B. Try a different paper", "C. Check API quota", "D. Contact support"],
                          "correct_answer": "A. Retry"}]}

    cleaned = _extract_json(raw)
    try:
        data = json.loads(cleaned)
        # Validate expected structure
        if "quiz" not in data or not isinstance(data["quiz"], list):
            raise ValueError("Unexpected JSON structure — 'quiz' list missing.")
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[quiz] JSON parse failed: {exc}\nRaw output (first 500 chars):\n{raw[:500]}")
        return {"quiz": [{"question": f"Quiz could not be parsed from the AI response. Raw error: {exc}",
                          "options": ["A. Retry", "B. Try a different paper", "C. Check API quota", "D. Contact support"],
                          "correct_answer": "A. Retry"}]}
