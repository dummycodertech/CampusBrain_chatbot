"""
Topic-frequency heatmap generator for Campus Brain.

Design choices for free-tier efficiency:
- Single LLM call with one retry on empty response.
- Paper text is truncated to 5000 chars to keep token usage minimal.
- Returns structured JSON; rendering uses st.bar_chart (pure frontend, zero cost).
"""
import json
import re
from services.llm_client import generate_text

_MAX_CHARS = 5000

# Simplified prompt — no double-brace JSON example (confuses some models).
# Asks for numbered list first, then JSON conversion.
HEATMAP_PROMPT = """You are an expert exam analyser. Read the exam paper below and identify the main topics tested.

EXAM PAPER:
{paper_text}

Instructions:
- List between 5 and 10 distinct topics found in this paper.
- For each topic, estimate how many questions relate to it (integer).
- Estimate total marks if visible, else use 0.
- Write a brief description (under 10 words).

Respond ONLY with a valid JSON object in this exact format (no other text):
{json_example}"""

_JSON_EXAMPLE = """{
  "topics": [
    {"topic": "Topic Name", "questions": 3, "marks": 10, "description": "Brief description here"},
    {"topic": "Another Topic", "questions": 2, "marks": 8, "description": "Brief description here"}
  ]
}"""


def generate_topic_heatmap(paper_text: str) -> dict:
    """Extract topic frequency data from a paper — single LLM call with one retry.

    Returns:
        {"topics": [{"topic": str, "questions": int, "marks": int, "description": str}, ...]}
    """
    truncated = paper_text[:_MAX_CHARS]
    if len(paper_text) > _MAX_CHARS:
        truncated += "\n[... paper continues ...]"

    prompt = HEATMAP_PROMPT.format(paper_text=truncated, json_example=_JSON_EXAMPLE)

    # First attempt
    raw = generate_text(prompt, temperature=0.3, max_tokens=1500)

    # One retry if empty
    if not raw or not raw.strip():
        print("[topic_heatmap] Empty response on first try — retrying...")
        raw = generate_text(prompt, temperature=0.5, max_tokens=1500)

    if not raw or not raw.strip():
        raise ValueError(
            "The model returned an empty response twice. "
            "This may be a temporary Groq rate-limit issue — please try again in a moment."
        )

    return _extract_json(raw)


def _extract_json(raw: str) -> dict:
    """Robustly extract the first JSON object from a model response."""
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text).strip()

    # Find the first {...} block (in case model adds preamble)
    match = re.search(r"\{[\s\S]+\}", text)
    if not match:
        raise ValueError(
            f"No JSON object found in model response.\nRaw (first 400 chars):\n{raw[:400]}"
        )

    return json.loads(match.group(0))
