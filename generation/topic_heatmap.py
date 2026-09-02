"""
Topic-frequency heatmap generator for Campus Brain.

Design choices for free-tier efficiency:
- Single LLM call — asks the model to extract ALL topics + estimated frequency
  in one shot instead of multiple calls.
- Paper text is truncated to 6000 chars: enough context for topic extraction
  without burning excessive tokens (a full OCR'd paper can be 15k+ chars).
- Returns structured JSON so the renderer never needs a second LLM call.
- Frequency is "estimated" (1–5 scale) because a single-paper upload has no
  multi-year data — the model infers frequency from how many marks/questions
  are devoted to each topic.
"""
import json
from services.llm_client import generate_text

# Truncate paper to this many chars before sending to the model.
# ~6000 chars ≈ 1500 tokens — keeps cost low on the free tier.
_MAX_CHARS = 6000

HEATMAP_PROMPT = """You are an expert exam analyser.
The text below is an exam paper (questions only, no answers).

--- PAPER TEXT ---
{paper_text}
--- END PAPER TEXT ---

Task:
1. Identify every distinct topic / subject area tested in this paper.
2. For each topic, count how many questions (or sub-questions / mark allocations)
   relate to it. If the paper has marks listed, use those; otherwise count questions.
3. Return a JSON list — most frequent topic first.

Return ONLY valid JSON, no other text, in this exact shape:
{{"topics": [
  {{"topic": "Topic Name", "questions": 3, "marks": 15, "description": "one-line description of what it covers"}}
]}}

Rules:
- "questions" is the number of questions/sub-parts about this topic (integer ≥ 1).
- "marks" is total marks allocated (integer); use 0 if marks are not shown.
- "description" is ≤ 12 words summarising what the topic covers.
- List between 4 and 12 topics.
- Sort by "questions" descending."""


def generate_topic_heatmap(paper_text: str) -> dict:
    """Extract topic frequency data from a paper — single LLM call.

    Returns:
        {
            "topics": [
                {"topic": str, "questions": int, "marks": int, "description": str},
                ...
            ]
        }

    Raises json.JSONDecodeError if the model returns malformed JSON (rare).
    """
    # Truncate to keep token usage minimal on free tier
    truncated = paper_text[:_MAX_CHARS]
    if len(paper_text) > _MAX_CHARS:
        truncated += "\n[... paper truncated for analysis ...]"

    raw = generate_text(HEATMAP_PROMPT.format(paper_text=truncated), temperature=0.1)

    if not raw or not raw.strip():
        raise ValueError("Model returned an empty response. Try again or use a longer paper.")

    return _extract_json(raw)


def _extract_json(raw: str) -> dict:
    """Robustly extract a JSON object from a model response.

    Handles:
    - Bare JSON
    - ```json ... ``` fences
    - ``` ... ``` fences (no language tag)
    - Extra leading/trailing text before/after the JSON object
    """
    import re
    text = raw.strip()

    # 1. Strip markdown code fences
    if text.startswith("```"):
        # Remove opening fence line (```json or ```)
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"```\s*$", "", text).strip()

    # 2. Find the first { ... } block in case model added preamble text
    match = re.search(r"\{[\s\S]+\}", text)
    if not match:
        raise ValueError(
            f"No JSON object found in model response. Raw response was:\n{raw[:300]}"
        )

    return json.loads(match.group(0))
