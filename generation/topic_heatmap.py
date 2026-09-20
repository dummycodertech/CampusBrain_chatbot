"""
Topic-frequency heatmap generator for Campus Brain.

Uses JSON output (most reliable across models) with pipe-delimited fallback.
"""
import json
import re
from services.llm_client import generate_text

_MAX_CHARS = 3000
_MIN_CHARS = 100

HEATMAP_PROMPT = """You are an exam paper analyser.

Read the exam paper text below and identify the 5-8 main topics tested.

EXAM PAPER:
{paper_text}

Respond with ONLY a valid JSON array — no markdown, no explanation, no extra text.
Each object must have these exact keys:
- "topic": topic name (string)
- "questions": number of questions on this topic (integer)
- "marks": total marks allocated (integer, use 0 if not shown)
- "description": one short phrase under 10 words (string)

Sort by questions descending. Example of the EXACT format expected:
[
  {{"topic": "Pointers", "questions": 4, "marks": 20, "description": "Pointer arithmetic and dynamic memory"}},
  {{"topic": "Arrays", "questions": 3, "marks": 15, "description": "1D and 2D array operations"}},
  {{"topic": "Functions", "questions": 2, "marks": 10, "description": "Recursion and function pointers"}}
]"""


def generate_topic_heatmap(paper_text: str) -> dict:
    """Extract topics from a paper.

    Returns:
        {"topics": [{"topic": str, "questions": int, "marks": int, "description": str}, ...]}
    Raises ValueError on failure.
    """
    if not paper_text or len(paper_text.strip()) < _MIN_CHARS:
        raise ValueError(
            "This paper has very little extractable text. "
            "The heatmap cannot be generated without readable text."
        )

    truncated = paper_text[:_MAX_CHARS]
    prompt = HEATMAP_PROMPT.format(paper_text=truncated)

    topics = []
    raw = ""

    # Attempt 1 — JSON at low temperature
    raw = generate_text(prompt, temperature=0.2, max_tokens=700)
    print(f"[topic_heatmap] Attempt 1 raw output ({len(raw) if raw else 0} chars): {repr(raw[:300] if raw else '')}")
    if raw and raw.strip():
        topics = _parse_json(raw)

    # Attempt 2 — JSON at higher temperature
    if not topics:
        print("[topic_heatmap] Attempt 1 failed — retrying with higher temperature...")
        raw = generate_text(prompt, temperature=0.5, max_tokens=700)
        print(f"[topic_heatmap] Attempt 2 raw output ({len(raw) if raw else 0} chars): {repr(raw[:300] if raw else '')}")
        if raw and raw.strip():
            topics = _parse_json(raw)

    # Attempt 3 — fallback to simple pipe format
    if not topics:
        print("[topic_heatmap] Attempt 2 failed — trying pipe-format fallback...")
        fallback_prompt = (
            "List the main topics in this exam paper.\n"
            "One topic per line in this format: TopicName | number_of_questions | total_marks\n"
            "Output ONLY the data rows, nothing else.\n\n"
            f"Exam paper:\n{truncated}"
        )
        raw = generate_text(fallback_prompt, temperature=0.3, max_tokens=400)
        print(f"[topic_heatmap] Attempt 3 raw output ({len(raw) if raw else 0} chars): {repr(raw[:300] if raw else '')}")
        if raw and raw.strip():
            topics = _parse_pipe(raw)

    if not topics:
        # Show actual model output in the error so we can debug
        debug_sample = repr(raw[:200]) if raw else "EMPTY STRING"
        raise ValueError(
            f"Could not extract topics from this paper. "
            f"Model returned: {debug_sample}"
        )

    return {"topics": topics}


def _parse_json(raw: str) -> list:
    """Try to extract a JSON array from the model response."""
    try:
        # Find the JSON array even if there's surrounding text
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group())
        topics = []
        for item in data:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic", "")).strip()
            if not topic:
                continue
            topics.append({
                "topic": topic,
                "questions": _to_int(item.get("questions", 1)),
                "marks": _to_int(item.get("marks", 0)),
                "description": str(item.get("description", "")).strip(),
            })
        return topics
    except Exception as e:
        print(f"[topic_heatmap] JSON parse failed: {e}")
        return []


def _parse_pipe(raw: str) -> list:
    """Parse pipe-delimited rows as a fallback."""
    topics = []
    for line in raw.strip().splitlines():
        line = re.sub(r"^\d+[\.\)]\s*", "", line.strip())
        if "|" not in line:
            continue
        upper = line.upper()
        if "TOPIC" in upper and "QUESTION" in upper and upper.index("TOPIC") < 10:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        topics.append({
            "topic": parts[0],
            "questions": _to_int(parts[1]) if len(parts) > 1 else 1,
            "marks": _to_int(parts[2]) if len(parts) > 2 else 0,
            "description": parts[3].strip() if len(parts) > 3 else "",
        })
    return topics


def _to_int(val, default: int = 0) -> int:
    try:
        digits = "".join(c for c in str(val) if c.isdigit())
        return int(digits) if digits else default
    except Exception:
        return default
