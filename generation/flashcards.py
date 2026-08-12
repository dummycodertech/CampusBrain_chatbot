"""
Flashcard generator for Campus Brain.

Produces Anki-style term → definition pairs directly from the exam paper text.
Flashcards are a proven spaced-repetition study technique; they complement the
quiz (which tests application) by reinforcing raw concept recall first.

Design mirrors quiz.py:
- A fixed JSON schema is enforced in the prompt so the model can't return
  free-text that breaks the renderer.
- json.loads() on the response; markdown code fences are stripped first.
- generate_text() from services.llm_client keeps the provider abstraction.
"""
import json
from services.llm_client import generate_text

# ── Prompt ─────────────────────────────────────────────────────────────────────
# 10 cards is the sweet spot: enough to cover the paper's key concepts without
# overwhelming the student.  The "TERM" field must be short (<8 words) so it
# fits on a card front without wrapping.
FLASHCARD_PROMPT = """You are an expert exam tutor helping students revise.
Based ONLY on the exam paper text below, create 10 concise flashcards.
Each flashcard has:
  - "term": a short keyword, concept, formula, or question (max 8 words)
  - "definition": a clear, accurate explanation (2-4 sentences, exam-ready)

--- PAPER TEXT ---
{paper_text}
--- END PAPER TEXT ---

Rules:
- Cover the most important and frequently examined concepts in this paper.
- Do NOT invent content that isn't in the paper text.
- Keep definitions factual, precise, and useful for last-minute revision.
- Return ONLY valid JSON, no other text, in this exact shape:
{{"flashcards": [
  {{"term": "...", "definition": "..."}}
]}}"""


def generate_flashcards(paper_text: str) -> dict:
    """Generate 10 exam-focused flashcards from the paper text.

    Returns a dict with the shape::

        {"flashcards": [{"term": str, "definition": str}, ...]}

    Raises json.JSONDecodeError if the model returns malformed JSON (rare
    because the prompt enforces the schema, but callers should handle it).
    """
    raw = generate_text(FLASHCARD_PROMPT.format(paper_text=paper_text), temperature=0.3)

    # Strip markdown code fences the model occasionally wraps the JSON in
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove opening ``` (and optional language tag) and closing ```
        cleaned = "\n".join(
            line for i, line in enumerate(lines)
            if not (i == 0 and line.startswith("```")) and line.strip() != "```"
        )

    return json.loads(cleaned.strip())
