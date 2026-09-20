"""
Topic-frequency heatmap generator for Campus Brain.

Strategy: run the existing summarize_paper() which reliably works, then
parse the topics out of sections 1 and 3. This piggybacks on the prompt
that's already proven to produce output rather than fighting a separate
prompt that silently returns empty strings.

If the summary is already in st.session_state (user clicked Summarize
earlier), the topics are extracted instantly at zero API cost.
"""
import re
from generation.summary import summarize_paper, SUMMARY_PROMPT
from services.llm_client import generate_text


def _extract_topics_from_summary(summary_text: str) -> list:
    """Pull topic names out of the summary's section 1 (Topics & Chapters)
    and cross-reference marks from section 3 (Marks Weightage).

    Returns [{"topic", "questions", "marks", "description"}, ...]
    """
    topics = []

    # ── Section 1: Topics & Chapters ───────────────────────────────────────
    # Match from "1. Topics" up to the next numbered section "2."
    sec1_match = re.search(
        r"\*\*1\.\s*Topics.*?\*\*(.*?)(?=\*\*2\.|\Z)",
        summary_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not sec1_match:
        # Fallback: look for any bullet list
        sec1_match = re.search(r"Topics.*?\n((?:\s*[-•*]\s*.+\n?)+)", summary_text, re.IGNORECASE)

    topic_lines = []
    if sec1_match:
        block = sec1_match.group(1)
        for line in block.splitlines():
            line = line.strip()
            # Keep lines that look like bullet points
            cleaned = re.sub(r"^[-•*]\s*", "", line).strip()
            if cleaned and len(cleaned) > 3 and not cleaned.startswith("**"):
                topic_lines.append(cleaned)

    # ── Section 3: Marks Weightage ─────────────────────────────────────────
    sec3_match = re.search(
        r"\*\*3\.\s*Marks.*?\*\*(.*?)(?=\*\*4\.|\Z)",
        summary_text,
        re.DOTALL | re.IGNORECASE,
    )
    marks_text = sec3_match.group(1) if sec3_match else ""

    def _marks_for(topic_name: str) -> int:
        """Try to find a mark number near the topic name in the marks section."""
        # Look for patterns like "Topic Name – 10 marks" or "Topic: 15M"
        pattern = re.compile(
            re.escape(topic_name[:12]) + r".{0,40}?(\d+)\s*(?:marks?|M\b)",
            re.IGNORECASE,
        )
        m = pattern.search(marks_text)
        if m:
            return int(m.group(1))
        # Just look for any standalone number near the topic
        m2 = re.search(re.escape(topic_name[:10]) + r".{0,30}?(\d+)", marks_text, re.IGNORECASE)
        return int(m2.group(1)) if m2 else 0

    # Build topic list — assign question counts by position (1st = most repeated)
    total = len(topic_lines)
    for i, line in enumerate(topic_lines[:10]):  # cap at 10 topics
        # Trim long descriptions to a short topic name + description split
        if ":" in line:
            name, desc = line.split(":", 1)
        elif "–" in line or "-" in line:
            parts = re.split(r"[–\-]", line, maxsplit=1)
            name, desc = parts[0], parts[1] if len(parts) > 1 else ""
        else:
            name, desc = line, ""

        name = name.strip()
        desc = desc.strip()[:60]

        # Assign descending question counts (first topics are most repeated)
        q_count = max(1, total - i)

        topics.append({
            "topic": name,
            "questions": q_count,
            "marks": _marks_for(name),
            "description": desc or name,
        })

    return topics


def generate_topic_heatmap(paper_text: str, cached_summary: str = "") -> dict:
    """Extract topics for the heatmap.

    If cached_summary is provided (user already clicked Summarize), parse it
    directly — zero extra API calls.

    Otherwise, run summarize_paper() to get a fresh summary, then parse it.
    The summary prompt is reliable and already proven to work.

    Returns {"topics": [...], "summary_used": str}
    Raises ValueError on failure.
    """
    if not paper_text or len(paper_text.strip()) < 80:
        raise ValueError("Not enough text to analyse topics.")

    # Use cached summary if available, otherwise generate one
    if cached_summary and len(cached_summary.strip()) > 100:
        summary = cached_summary
        print("[topic_heatmap] Using cached summary — no extra API call needed.")
    else:
        print("[topic_heatmap] Generating summary to extract topics...")
        summary = generate_text(SUMMARY_PROMPT.format(paper_text=paper_text[:4000]))
        if not summary or not summary.strip():
            raise ValueError(
                "The model returned no output. Please try again in a moment."
            )

    topics = _extract_topics_from_summary(summary)

    if not topics:
        raise ValueError(
            "Could not extract topics from the summary. "
            "Try clicking 'Summarize' first, then 'Topic Heatmap'."
        )

    return {"topics": topics, "summary_text": summary}
