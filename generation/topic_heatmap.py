"""
Topic-frequency heatmap generator for Campus Brain.

Uses pipe-delimited table format instead of JSON — avoids all JSON parsing
issues. The model handles table formats very reliably.

Free-tier optimized:
- Single call, one retry on empty.
- Paper truncated to 5000 chars (~1250 tokens).
"""
from services.llm_client import generate_text

_MAX_CHARS = 5000

HEATMAP_PROMPT = """You are an exam paper analyser.

Read the exam paper below and identify its main topics.

EXAM PAPER:
{paper_text}

Output a table with EXACTLY this format — one topic per line, pipe-separated:
TOPIC | QUESTIONS | MARKS | DESCRIPTION

Rules:
- TOPIC: name of the topic (short, clear)
- QUESTIONS: integer count of questions about this topic
- MARKS: integer total marks allocated (0 if not shown)
- DESCRIPTION: under 10 words describing what the topic covers
- List 5 to 10 topics, sorted by QUESTIONS descending
- Output ONLY the data rows, no headers, no extra text

Example output:
Digital Logic | 3 | 15 | Boolean algebra, gates and Karnaugh maps
Microprocessors | 2 | 10 | 8085 architecture and instruction set
Memory Systems | 1 | 5 | RAM, ROM types and organisation"""


def generate_topic_heatmap(paper_text: str) -> dict:
    """Extract topics from a paper as a pipe-delimited table — very reliable.

    Returns:
        {"topics": [{"topic": str, "questions": int, "marks": int, "description": str}, ...]}
    """
    truncated = paper_text[:_MAX_CHARS]
    if len(paper_text) > _MAX_CHARS:
        truncated += "\n[... paper continues ...]"

    prompt = HEATMAP_PROMPT.format(paper_text=truncated)

    raw = generate_text(prompt, temperature=0.3, max_tokens=1000)

    # Retry once if empty
    if not raw or not raw.strip():
        print("[topic_heatmap] Empty response — retrying...")
        raw = generate_text(prompt, temperature=0.5, max_tokens=1000)

    if not raw or not raw.strip():
        raise ValueError(
            "The model returned no output. This may be a temporary rate-limit. Please try again."
        )

    return _parse_table(raw)


def _parse_table(raw: str) -> dict:
    """Parse pipe-delimited table rows into a dict.

    Skips any header line or malformed row gracefully.
    """
    topics = []
    for line in raw.strip().splitlines():
        line = line.strip()
        # Skip empty lines, header-like lines, or separator lines
        if not line or "|" not in line:
            continue
        # Skip if it looks like a header (TOPIC | QUESTIONS ...)
        if "TOPIC" in line.upper() and "QUESTIONS" in line.upper():
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue

        try:
            topics.append({
                "topic": parts[0],
                "questions": int("".join(c for c in parts[1] if c.isdigit()) or "1"),
                "marks": int("".join(c for c in parts[2] if c.isdigit()) or "0"),
                "description": parts[3],
            })
        except (ValueError, IndexError):
            # Skip malformed rows silently
            continue

    if not topics:
        raise ValueError(
            "Could not extract topics from the model response. "
            f"Raw output was:\n{raw[:400]}"
        )

    return {"topics": topics}
