"""
Extracts and ranks top recurring exam topics with exact past questions.
Zero LLM calls — pure Python keyword scoring, marks extraction, and difflib deduplication.
No Streamlit dependencies.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from generation.topic_heatmap import (
    TOPIC_KEYWORDS,
    extract_marks,
    score_question,
    split_into_questions,
)


def _year_num(y: Any) -> int:
    """Extract 4-digit integer year for sorting; defaults to 0 if not found."""
    m = re.search(r"20\d{2}", str(y))
    return int(m.group(0)) if m else 0


def _extract_q_no(q_text: str, fallback_idx: int) -> str:
    """Extract question label like 'Q1', '1.', '(a)', or fallback to 'Q{idx}'."""
    m = re.match(
        r"^\s*(?:Q\.?\s*(\d+[a-zA-Z]?)|(\d+[a-zA-Z]?)[.)]|\(([a-zA-Z\d]+)\)|([a-zA-Z])[.)])",
        q_text,
        re.IGNORECASE,
    )
    if m:
        # Return cleanly formatted label
        clean_label = m.group(0).strip().rstrip(".)")
        if not clean_label.upper().startswith("Q"):
            clean_label = f"Q{clean_label}"
        return clean_label
    return f"Q{fallback_idx}"


def _clean_question_text(q_text: str) -> str:
    """Normalize whitespace and strip extraneous delimiters."""
    # Collapse multiple whitespace
    cleaned = re.sub(r"\s+", " ", q_text).strip()
    return cleaned


def _merge_near_duplicates(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge questions across years with text similarity > 0.8."""
    merged: List[Dict[str, Any]] = []

    for q in questions:
        q_text_norm = q["text"].lower()
        matched_entry = None
        for existing in merged:
            ratio = difflib.SequenceMatcher(None, q_text_norm, existing["text"].lower()).ratio()
            if ratio > 0.8:
                matched_entry = existing
                break

        if matched_entry:
            for y in q["years"]:
                if y not in matched_entry["years"]:
                    matched_entry["years"].append(y)
            # Retain the higher mark allocation if available
            if q["marks"] > matched_entry["marks"]:
                matched_entry["marks"] = q["marks"]
        else:
            merged.append({
                "year": q["year"],
                "years": list(q["years"]),
                "q_no": q["q_no"],
                "marks": q["marks"],
                "text": q["text"],
            })

    # Sort years within each question newest first and format year display
    for entry in merged:
        entry["years"] = sorted(entry["years"], key=_year_num, reverse=True)
        entry["year"] = ", ".join(str(y) for y in entry["years"]) if entry["years"] else entry["year"]

    # Sort merged questions newest first
    merged.sort(key=lambda item: _year_num(item["years"][0] if item["years"] else item["year"]), reverse=True)
    return merged


def top_topics_with_questions(
    papers: List[Any],
    n: int = 5,
    per_topic: int = 4,
) -> List[Dict[str, Any]]:
    """Rank top topics across papers and return exact past questions.

    Args:
        papers: List of tuples (paper_id, year, text) or (year, text).
        n: Number of top topics to return (default 5).
        per_topic: Max questions per topic to return (default 4).

    Returns:
        List of dicts: [
            {
                "topic": str,
                "count": int,
                "total_marks": int,
                "years": list[str],
                "questions": [
                    {"year": str, "years": list[str], "q_no": str, "marks": int, "text": str}, ...
                ]
            }, ...
        ] ranked by (count, total_marks) descending.
    """
    if not papers:
        return []

    # Map: topic -> {"questions": [...], "count": int, "total_marks": int, "years": set()}
    topic_map: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"questions": [], "count": 0, "total_marks": 0, "years": set()}
    )

    for item in papers:
        if len(item) == 3:
            _pid, year, text = item
        elif len(item) >= 2:
            year, text = item[0], item[1]
        else:
            continue

        if not text or not str(text).strip():
            continue

        year_str = str(year).strip() if year else "Uploaded"
        questions = split_into_questions(str(text))

        for idx, q_text in enumerate(questions, start=1):
            scores = score_question(q_text)
            if not scores:
                continue

            best_topic = max(scores, key=scores.get)
            marks = extract_marks(q_text)
            q_no = _extract_q_no(q_text, idx)
            clean_text = _clean_question_text(q_text)

            topic_map[best_topic]["count"] += 1
            topic_map[best_topic]["total_marks"] += marks
            topic_map[best_topic]["years"].add(year_str)
            topic_map[best_topic]["questions"].append({
                "year": year_str,
                "years": [year_str],
                "q_no": q_no,
                "marks": marks,
                "text": clean_text,
            })

    if not topic_map:
        return []

    # Format and rank
    results: List[Dict[str, Any]] = []
    for topic_name, data in topic_map.items():
        merged_qs = _merge_near_duplicates(data["questions"])
        sorted_years = sorted(list(data["years"]), key=_year_num, reverse=True)
        results.append({
            "topic": topic_name,
            "count": data["count"],
            "total_marks": data["total_marks"],
            "years": sorted_years,
            "questions": merged_qs[:per_topic],
        })

    # Rank by (count, total_marks) descending
    results.sort(key=lambda t: (t["count"], t["total_marks"]), reverse=True)
    return results[:n]
