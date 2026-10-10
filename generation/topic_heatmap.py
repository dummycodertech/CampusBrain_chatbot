"""
Topic-frequency heatmap generator for Campus Brain.

Builds heatmap data from AI-tagged question rows (see generation/topic_tagger.py).
No LLM calls in this module — tagging is handled upstream.

Public API:
  split_into_questions(text) -> list
  extract_marks(text)        -> int
  build_heatmap_from_rows(rows) -> dict
"""
import re
from collections import defaultdict


def split_into_questions(text: str) -> list:
    """Split paper text into individual question chunks."""
    # Match Q1, Q.1, 1., 1), a), a., (a), (1) etc.
    pattern = re.compile(
        r"(?:^|\n)\s*(?:Q\.?\s*\d+|(?:\d+|[a-zA-Z])[.)]\s+|\([a-zA-Z\d]\)\s+)",
        re.MULTILINE,
    )
    splits = [m.start() for m in pattern.finditer(text)]
    if not splits:
        # Fallback: split by sentences
        return [s.strip() for s in re.split(r"[.?!]\s+", text) if len(s.strip()) > 20]

    chunks = []
    for i, start in enumerate(splits):
        end = splits[i + 1] if i + 1 < len(splits) else len(text)
        chunks.append(text[start:end].strip())
    return chunks

_split_into_questions = split_into_questions


def extract_marks(text: str) -> int:
    """Extract question marks from text, handling [10], (10), [10M], (10 marks), '10 Marks'."""
    # 1. Prefer explicit marks/M notation: [10M], (10 marks), 10 Marks, [10 Marks]
    for m in re.finditer(r"(?:\[|\()?\s*(\d{1,2})\s*(?:marks?|m)\s*(?:\]|\)?|\b)", text, re.IGNORECASE):
        try:
            return int(m.group(1))
        except ValueError:
            pass
    # 2. Look for bracketed numbers: [10], (10)
    brackets = list(re.finditer(r"[\[\(]\s*(\d{1,2})\s*[\]\)]", text))
    if brackets:
        return int(brackets[-1].group(1))
    return 0


def build_heatmap_from_rows(rows: list) -> dict:
    """Build topic frequency data from AI-tagged question rows.

    Returns {"topics": [{"topic": str, "questions": int, "marks": int, "description": str}, ...]}
    description is set to the first 70 characters of the first question for that topic.
    """
    if not rows:
        return {"topics": []}

    topic_counts = defaultdict(int)
    topic_marks = defaultdict(int)
    topic_first_q: dict = {}  # topic -> first question text seen

    for r in rows:
        top = (r.get("topic") or "Uncategorized").strip()
        if top in ("Uncategorized", "Other"):
            continue
        topic_counts[top] += 1
        m = r.get("marks", 0) or 0
        if m > 0:
            topic_marks[top] += m
        if top not in topic_first_q:
            topic_first_q[top] = (r.get("text") or "").strip()

    sorted_topics = sorted(
        topic_counts.items(),
        key=lambda x: (x[1], topic_marks.get(x[0], 0)),
        reverse=True,
    )[:8]

    topics = []
    for name, count in sorted_topics:
        first_q = topic_first_q.get(name, "")
        desc = first_q[:70].rstrip() if first_q else name
        topics.append({
            "topic": name,
            "questions": count,
            "marks": topic_marks.get(name, 0),
            "description": desc,
        })

    return {"topics": topics}
