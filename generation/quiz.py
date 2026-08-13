"""Quiz generator for Campus Brain.

The input is a Previous Year Question (PYQ) paper — it contains only exam
questions, not answers.  The prompt treats the paper as a topic/syllabus signal
and generates NEW practice MCQs on those same topics, with correct answers
supplied from the LLM's own academic knowledge.

This is deliberately better than the paper itself: a student gets fresh
practice questions on exactly the topics their exam covers.
"""
import json
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


def generate_quiz(paper_text: str) -> dict:
    raw = generate_text(QUIZ_PROMPT.format(paper_text=paper_text))
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    return json.loads(cleaned.strip())
