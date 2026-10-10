"""
Mock paper generator for Campus Brain.

Builds a practice paper from real past questions weighted by topic frequency.
No LLM calls. No Streamlit imports.
"""
from __future__ import annotations

import difflib
import random
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

# ── Default exam structure ─────────────────────────────────────────────────────
DEFAULT_STRUCTURE: List[Dict[str, Any]] = [
    {"section": "Section A", "marks": 2,  "count": 5},
    {"section": "Section B", "marks": 5,  "count": 4},
    {"section": "Section C", "marks": 10, "count": 2},
]

_SKIP_TOPICS = {"Other", "Uncategorized"}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _year_num(y: Any) -> int:
    m = re.search(r"20\d{2}", str(y))
    return int(m.group(0)) if m else 0


def _build_pool(
    tagged: List[Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Flatten tagged into a question pool with year attached.

    tagged can be [(year, rows)] or [(paper_id, year, rows)].
    Returns (pool, sorted_years_desc).
    """
    pool: List[Dict[str, Any]] = []
    years_seen = set()

    for item in tagged:
        if len(item) == 2:
            year, rows = item[0], item[1]
        elif len(item) == 3:
            _, year, rows = item
        else:
            continue
        year_str = str(year).strip() if year else "Uploaded"
        if not rows:
            continue
        years_seen.add(year_str)
        for r in rows:
            text = (r.get("text") or "").strip()
            if len(text) < 15:
                continue
            pool.append({
                "text": text,
                "topic": (r.get("topic") or "Uncategorized").strip(),
                "marks": r.get("marks", 0) or 0,
                "q_no": r.get("q_no", ""),
                "year": year_str,
            })

    sorted_years = sorted(years_seen, key=_year_num, reverse=True)
    return pool, sorted_years


def _compute_topic_weights(
    pool: List[Dict[str, Any]],
    sorted_years: List[str],
    skip_topics: set,
) -> Dict[str, float]:
    """Count questions per topic + 0.5 recency bonus for each of the 2 most recent years."""
    topic_counts: Dict[str, int] = defaultdict(int)
    topic_years: Dict[str, set] = defaultdict(set)

    for q in pool:
        t = q["topic"]
        topic_counts[t] += 1
        topic_years[t].add(q["year"])

    real_topics = {t for t in topic_counts if t not in skip_topics}
    active_skip = skip_topics if real_topics else set()
    recent_two = set(sorted_years[:2])

    weights: Dict[str, float] = {}
    for topic, count in topic_counts.items():
        if topic in active_skip:
            continue
        recency_bonus = sum(0.5 for y in topic_years[topic] if y in recent_two)
        weights[topic] = count + recency_bonus

    return weights


def _similar(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.8


def build_mock_paper(
    tagged: List[Any],
    structure: Optional[List[Dict[str, Any]]] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a mock practice paper from tagged question rows.

    Args:
        tagged: [(year, rows)] or [(paper_id, year, rows)].
        structure: list of {section, marks, count}.
        seed: random seed for reproducibility.

    Returns:
        {sections: [...], total_marks: int, warnings: [str]}
    """
    if structure is None:
        structure = DEFAULT_STRUCTURE

    rng = random.Random(seed)
    pool, sorted_years = _build_pool(tagged)
    papers_used = len({q["year"] for q in pool})
    warnings: List[str] = []

    if papers_used < 2:
        warnings.append(
            "Only 1 paper was available; open more years of this subject for better variety."
        )

    weights = _compute_topic_weights(pool, sorted_years, _SKIP_TOPICS)
    if not weights:
        weights = _compute_topic_weights(pool, sorted_years, set())

    # Build per-topic question list (mutable copy for removal)
    topic_pool: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for q in pool:
        if q["topic"] in weights:
            topic_pool[q["topic"]].append(q)

    chosen_texts: List[str] = []
    chosen_ids: set = set()
    sections_out: List[Dict[str, Any]] = []
    total_marks = 0

    for slot in structure:
        section_name = slot.get("section", "Section")
        slot_marks = int(slot.get("marks", 0))
        slot_count = int(slot.get("count", 1))

        questions_out: List[Dict[str, Any]] = []

        # 3-pass: exact marks → zero marks → nearest marks
        for pass_num in range(3):
            if len(questions_out) >= slot_count:
                break

            remaining_topics = [t for t in weights if topic_pool.get(t)]

            while len(questions_out) < slot_count and remaining_topics:
                total_w = sum(weights[t] for t in remaining_topics)
                pick = rng.uniform(0, total_w)
                cumulative = 0.0
                chosen_topic = remaining_topics[-1]
                for t in remaining_topics:
                    cumulative += weights[t]
                    if pick <= cumulative:
                        chosen_topic = t
                        break

                candidates = list(topic_pool[chosen_topic])
                if pass_num == 0:
                    candidates = [q for q in candidates if q["marks"] == slot_marks]
                elif pass_num == 1:
                    candidates = [q for q in candidates if q["marks"] == 0]
                # pass 2: all remaining

                candidates = [
                    q for q in candidates
                    if id(q) not in chosen_ids
                    and not any(_similar(q["text"], ct) for ct in chosen_texts)
                ]

                if not candidates:
                    remaining_topics = [t for t in remaining_topics if t != chosen_topic]
                    continue

                chosen_q = rng.choice(candidates)
                topic_pool[chosen_topic] = [
                    q for q in topic_pool[chosen_topic] if q is not chosen_q
                ]
                chosen_ids.add(id(chosen_q))
                chosen_texts.append(chosen_q["text"])

                is_adjusted = pass_num > 0 and chosen_q["marks"] != slot_marks

                questions_out.append({
                    "n": len(questions_out) + 1,
                    "text": chosen_q["text"],
                    "topic": chosen_q["topic"],
                    "year": chosen_q["year"],
                    "marks": slot_marks,
                    "adjusted": is_adjusted,
                })

        if len(questions_out) < slot_count:
            warnings.append(
                f"{section_name}: could only fill {len(questions_out)} of {slot_count} "
                "question(s) — not enough unique past questions available."
            )

        total_marks += sum(q["marks"] for q in questions_out)
        sections_out.append({
            "section": section_name,
            "marks": slot_marks,
            "questions": questions_out,
        })

    return {
        "sections": sections_out,
        "total_marks": total_marks,
        "warnings": warnings,
    }


# ── Export helpers ─────────────────────────────────────────────────────────────

def to_text(paper: Dict[str, Any], title: str = "Mock Paper") -> str:
    """Render paper as plain text fallback."""
    lines = [title, "=" * len(title), f"Total Marks: {paper['total_marks']}", ""]
    for sec in paper.get("sections", []):
        lines.append(f"--- {sec['section']} ({sec['marks']} marks each) ---")
        for q in sec.get("questions", []):
            adj = "  [marks adjusted]" if q.get("adjusted") else ""
            lines.append(f"Q{q['n']}. {q['text']}  [{q['marks']} marks]{adj}")
        lines.append("")
    return "\n".join(lines)


def to_pdf_bytes(paper: Dict[str, Any], title: str = "Mock Paper") -> bytes:
    """Render paper as PDF bytes using reportlab.

    Raises ImportError if reportlab is not installed.
    Every dynamic string goes through xml.sax.saxutils.escape before Paragraph.
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "MockTitle", parent=styles["Title"], fontSize=16, spaceAfter=6,
    )
    style_subtitle = ParagraphStyle(
        "MockSubtitle", parent=styles["Normal"], fontSize=10, spaceAfter=12,
    )
    style_section = ParagraphStyle(
        "MockSection", parent=styles["Heading2"], fontSize=12,
        spaceBefore=12, spaceAfter=4,
    )
    style_q = ParagraphStyle(
        "MockQ", parent=styles["Normal"], fontSize=10, spaceAfter=8, leading=14,
    )

    story = []
    story.append(Paragraph(escape(title), style_title))
    story.append(Paragraph(escape(f"Total Marks: {paper['total_marks']}"), style_subtitle))

    global_n = 1
    for sec in paper.get("sections", []):
        story.append(Paragraph(
            escape(f"{sec['section']}  ({sec['marks']} marks each)"),
            style_section,
        ))
        for q in sec.get("questions", []):
            story.append(Paragraph(
                f"<b>Q{global_n}.</b> {escape(q['text'])} <i>[{q['marks']} marks]</i>",
                style_q,
            ))
            global_n += 1
        story.append(Spacer(1, 0.3 * cm))

    doc.build(story)
    return buf.getvalue()
