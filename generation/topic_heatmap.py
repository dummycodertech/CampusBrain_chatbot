"""
Topic-frequency heatmap generator for Campus Brain.

Piggybacks on summarize_paper() which reliably works, then parses the
structured TOPICS_START/TOPICS_END block the summary prompt emits.
Parsing is trivial — no regex, no JSON, just splitlines + split('|').
"""
from generation.summary import summarize_paper, SUMMARY_PROMPT
from services.llm_client import generate_text


def _parse_topics_block(summary_text: str) -> list:
    """Extract topics from the ---TOPICS_START--- block in the summary."""
    topics = []

    start = summary_text.find("---TOPICS_START---")
    end = summary_text.find("---TOPICS_END---")

    if start == -1 or end == -1:
        return []

    block = summary_text[start + len("---TOPICS_START---"):end].strip()

    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("TOPIC:"):
            continue
        # Format: TOPIC: name | Q: n | M: m
        rest = line[len("TOPIC:"):].strip()
        parts = [p.strip() for p in rest.split("|")]

        topic_name = parts[0] if parts else ""
        if not topic_name or len(topic_name) < 2:
            continue

        def _get_int(parts, prefix, default=0):
            for p in parts:
                if p.upper().startswith(prefix.upper()):
                    val = p.split(":", 1)[-1].strip()
                    digits = "".join(c for c in val if c.isdigit())
                    return int(digits) if digits else default
            return default

        questions = _get_int(parts, "Q", 1)
        marks = _get_int(parts, "M", 0)

        topics.append({
            "topic": topic_name,
            "questions": max(1, questions),
            "marks": marks,
            "description": topic_name,
        })

    return topics


def generate_topic_heatmap(paper_text: str, cached_summary: str = "") -> dict:
    """Extract topics for the heatmap by running/reusing the summary.

    The summary prompt already produces a structured TOPICS_START block.
    If cached_summary is provided, parse it directly — zero extra API calls.

    Returns {"topics": [...], "summary_text": str}
    Raises ValueError on failure.
    """
    if not paper_text or len(paper_text.strip()) < 80:
        raise ValueError("Not enough text to analyse topics.")

    # Use cached summary if it already has the TOPICS block
    if cached_summary and "---TOPICS_START---" in cached_summary:
        summary = cached_summary
        print("[topic_heatmap] Using cached summary — no extra API call.")
    else:
        print("[topic_heatmap] Running summary to extract topics...")
        summary = generate_text(SUMMARY_PROMPT.format(paper_text=paper_text[:4000]))
        if not summary or not summary.strip():
            raise ValueError(
                "The model returned no output. Please try again in a moment."
            )

    topics = _parse_topics_block(summary)

    if not topics:
        # Fallback: model didn't emit the TOPICS block — show a friendly message
        raise ValueError(
            "The model didn't emit a structured topic list this time. "
            "Try clicking **Summarize** first, then **Topic Heatmap**."
        )

    return {"topics": topics, "summary_text": summary}
