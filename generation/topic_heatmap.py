"""
Topic-frequency heatmap generator for Campus Brain.

Uses pipe-delimited table format — avoids JSON parsing failures entirely.
Free-tier optimized: single call, one retry, 3000 char paper truncation.
"""
from services.llm_client import generate_text

_MAX_CHARS = 3000   # Keep prompt short so model has room to output
_MIN_CHARS = 100

HEATMAP_PROMPT = """You are an exam paper analyser. Read the exam paper below and list the main topics.

EXAM PAPER:
{paper_text}

List 5-8 topics as a pipe-delimited table. Each line must follow this exact format:
TopicName | NumQuestions | TotalMarks | OneLineDescription

Example output (copy this style exactly):
Data Structures | 4 | 20 | Arrays, linked lists, trees and graphs
Operating Systems | 3 | 15 | Process scheduling and memory management
DBMS | 2 | 10 | SQL queries and normalization

Rules:
- NumQuestions and TotalMarks must be plain integers (e.g. 3, not "3 questions")
- Use 0 for marks if not shown in the paper
- Sort by NumQuestions descending
- Output ONLY the data rows — no header row, no numbering, no extra text"""


def generate_topic_heatmap(paper_text: str) -> dict:
    """Extract topics from a paper as a pipe-delimited table.

    Returns:
        {"topics": [{"topic": str, "questions": int, "marks": int, "description": str}, ...]}

    Raises ValueError with a user-friendly message on failure.
    """
    if not paper_text or len(paper_text.strip()) < _MIN_CHARS:
        raise ValueError(
            "This paper has very little extractable text "
            "(possibly a scanned PDF where OCR yielded no content). "
            "The heatmap cannot be generated without readable text."
        )

    truncated = paper_text[:_MAX_CHARS]
    if len(paper_text) > _MAX_CHARS:
        truncated += "\n[... paper continues ...]"

    prompt = HEATMAP_PROMPT.format(paper_text=truncated)

    # Attempt 1
    raw = generate_text(prompt, temperature=0.2, max_tokens=600)
    topics = _parse_table(raw) if raw and raw.strip() else []

    # Attempt 2: retry with higher temp if nothing parsed
    if not topics:
        print("[topic_heatmap] No topics parsed — retrying...")
        raw = generate_text(prompt, temperature=0.5, max_tokens=600)
        topics = _parse_table(raw) if raw and raw.strip() else []

    # Attempt 3: fallback with a simpler numbered-list prompt
    if not topics:
        print("[topic_heatmap] Still empty — trying fallback numbered-list prompt...")
        fallback_prompt = (
            "List the main topics in this exam paper as a simple numbered list.\n"
            "Format each line as:  TopicName | number_of_questions\n\n"
            f"Exam paper:\n{truncated}"
        )
        raw = generate_text(fallback_prompt, temperature=0.3, max_tokens=400)
        topics = _parse_table(raw) if raw and raw.strip() else []

    if not topics:
        raise ValueError(
            "Could not extract topics from this paper. "
            "The paper text may be too short, in an unusual format, "
            "or the model is temporarily unavailable. Please try again."
        )

    return {"topics": topics}


def _parse_table(raw: str) -> list:
    """Parse pipe-delimited rows — very defensive, handles varied model output."""
    topics = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Strip leading numbering like "1." or "1)"
        import re
        line = re.sub(r"^\d+[\.\)]\s*", "", line)

        # Need at least one pipe to be a table row
        if "|" not in line:
            continue

        # Skip obvious header rows
        upper = line.upper()
        if ("TOPIC" in upper and ("QUESTION" in upper or "MARK" in upper)
                and upper.index("TOPIC") < 10):
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue

        topic_name = parts[0]
        if not topic_name or len(topic_name) > 80:
            continue

        def _to_int(s: str, default: int = 0) -> int:
            digits = "".join(c for c in s if c.isdigit())
            return int(digits) if digits else default

        questions = _to_int(parts[1], default=1) if len(parts) > 1 else 1
        marks = _to_int(parts[2], default=0) if len(parts) > 2 else 0
        description = parts[3].strip() if len(parts) > 3 else ""

        topics.append({
            "topic": topic_name,
            "questions": questions,
            "marks": marks,
            "description": description,
        })

    return topics
