"""Fixed-template quiz generator -- the "Quiz" button, fixed JSON schema output.
Enforcing the schema removes almost all "weird formatting" failure modes."""
import json
from services.llm_client import generate_text

QUIZ_PROMPT = """Based ONLY on the exam paper text below, generate a 5-question
multiple-choice quiz that tests the same topics this paper covers.

--- PAPER TEXT ---
{paper_text}
--- END PAPER TEXT ---

Return ONLY valid JSON, no other text, in this exact shape:
{{"quiz": [
  {{"question": "...", "options": ["A", "B", "C", "D"], "correct_answer": "A"}}
]}}"""


def generate_quiz(paper_text: str) -> dict:
    raw = generate_text(QUIZ_PROMPT.format(paper_text=paper_text))
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    return json.loads(cleaned.strip())
