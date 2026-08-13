"""
Flashcard generator for Campus Brain.

The input is a Previous Year Question (PYQ) paper — questions only, no answers.

Design:
- The prompt tells the LLM to treat the questions as a topic/concept signal.
- Definitions are supplied from the LLM's own academic knowledge (correct),
  NOT invented from the paper text (which has no definitions to give).
- The old constraint "Do NOT invent content that isn't in the paper text" was
  wrong for PYQs and caused empty/hallucinated definitions — removed.
- JSON schema is enforced so the renderer never breaks.
"""
import json
from services.llm_client import generate_text

# ── Prompt ─────────────────────────────────────────────────────────────────────
# 10 cards is the sweet spot: enough to cover the paper's key concepts without
# overwhelming the student.  The "TERM" field must be short (<8 words) so it
# fits on a card front without wrapping.
FLASHCARD_PROMPT = """You are an expert exam tutor helping students revise for their university exam.
The text below is a Previous Year Question (PYQ) paper — it contains ONLY exam questions,
not answers or explanations.

--- PYQ PAPER TEXT ---
{paper_text}
--- END PYQ PAPER TEXT ---

Your job:
1. Read the questions to identify the key terms, concepts, formulas, and topics this exam tests.
2. Create 10 flashcards covering the most important of those concepts.
3. Write the definition/explanation for each card using YOUR academic knowledge
   (the paper has no answers — you must supply the correct content).

Rules:
- "term": a short keyword, concept name, formula name, or algorithm (max 8 words).
- "definition": a clear, accurate, exam-ready explanation in 2-4 sentences.
  For formulas: state the formula and what each variable means.
  For algorithms: state what it does and its time complexity.
  For concepts: define it and give a one-line real-world application.
- Prioritise terms that appear frequently or carry high marks in the paper.
- Keep definitions factual, precise, and useful for last-minute revision.
- Return ONLY valid JSON, no other text, in this exact shape:
{{"flashcards": [
  {{"term": "...", "definition": "..."}}
]}}"""


def generate_flashcards(paper_text: str) -> dict:
    """Generate 10 exam-focused flashcards from a PYQ paper.

    Topics are extracted from the exam questions; definitions are supplied
    from the LLM's academic knowledge (correct approach for question-only papers).

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
