"""
Exam Predictor engine for Campus Brain.

Analyses past papers for a subject across multiple years using zero LLM calls.
Calculates recency-weighted topic probability scores from AI-tagged rows,
detects 'due for return' topics, and identifies near-duplicate questions.

No Streamlit dependencies.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from generation.topic_heatmap import (
    extract_marks,
    split_into_questions,
)
from generation.topic_questions import (
    _clean_question_text,
    _extract_q_no,
    _year_num,
)


def _parse_paper_tuple(paper: Any) -> Tuple[str, str, str]:
    """Normalize paper tuple to (paper_id, year, text)."""
    if isinstance(paper, (list, tuple)):
        if len(paper) == 3:
            return str(paper[0]), str(paper[1]), str(paper[2])
        elif len(paper) == 2:
            return "", str(paper[0]), str(paper[1])
    return "", "Unknown", str(paper)


def _normalize_question_for_match(text: str) -> str:
    """Strip question prefix (e.g. 'Q1.', '(a)') and marks annotations for similarity comparison."""
    # Strip leading label
    t = re.sub(
        r"^\s*(?:Q\.?\s*\d+[a-zA-Z]?|\d+[a-zA-Z]?|\([a-zA-Z\d]+\)|[a-zA-Z])[.)]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Strip marks like [10M], (10 marks)
    t = re.sub(
        r"\[\s*\d+\s*(?:marks?|m)?\s*\]|\(\s*\d+\s*(?:marks?|m)?\s*\)",
        "",
        t,
        flags=re.IGNORECASE,
    )
    return " ".join(t.lower().split())




def predict_topics_from_rows(tagged: List[Any]) -> List[Dict[str, Any]]:
    """Predict likely topics driven by AI-tagged question rows.

    Args:
        tagged: List of (year, rows) or (paper_id, year, rows) where rows have 'topic'.

    Returns:
        List of dicts ordered by score descending, each containing:
            - "topic": Topic name
            - "score": Recency-weighted score = sum over papers of 1 / (1 + years_ago)
            - "count": Total questions matched for this topic
            - "years": List of years the topic appeared in (newest first)
            - "due": True if topic appeared in >=2 years but is absent from the most recent 1-2 papers
    """
    if not tagged:
        return []

    parsed_papers: List[Tuple[str, int, List[Dict[str, Any]]]] = []
    valid_years: List[int] = []

    for item in tagged:
        if len(item) == 3:
            _pid, y_val, rows = item
        elif len(item) == 2:
            y_val, rows = item
        else:
            continue

        y_str = str(y_val).strip() if y_val else "Uploaded"
        y_int = _year_num(y_str)
        parsed_papers.append((y_str, y_int, rows or []))
        if y_int > 0:
            valid_years.append(y_int)

    unique_sorted_years = sorted(list(set(valid_years)))
    max_year = max(unique_sorted_years) if unique_sorted_years else 0

    topic_scores: Dict[str, float] = defaultdict(float)
    topic_counts: Dict[str, int] = defaultdict(int)
    topic_years: Dict[str, Set[str]] = defaultdict(set)

    for y_str, y_int, rows in parsed_papers:
        if max_year > 0 and y_int > 0:
            years_ago = max(0, max_year - y_int)
        else:
            years_ago = 0
        weight = 1.0 / (1.0 + years_ago)

        paper_topics_seen: Set[str] = set()
        for r in rows:
            top = (r.get("topic") or "Uncategorized").strip()
            if top in ("Uncategorized", "Other"):
                continue
            topic_counts[top] += 1
            paper_topics_seen.add(top)

        for top in paper_topics_seen:
            topic_scores[top] += weight
            topic_years[top].add(y_str)

    results: List[Dict[str, Any]] = []
    for topic, cnt in topic_counts.items():
        if cnt == 0:
            continue
        score = round(topic_scores.get(topic, 0.0), 2)
        years_set = topic_years.get(topic, set())
        years_sorted = sorted(list(years_set), key=_year_num, reverse=True)

        num_years_appeared = len(years_set)
        years_int_set = {_year_num(y) for y in years_set}
        is_due = (
            num_years_appeared >= 2
            and len(unique_sorted_years) >= 2
            and max_year not in years_int_set
        )

        results.append({
            "topic": topic,
            "score": score,
            "count": cnt,
            "years": years_sorted,
            "due": is_due,
        })

    results.sort(key=lambda x: (x["score"], x["count"]), reverse=True)
    return results


def find_repeated_questions(papers: List[Any]) -> List[Dict[str, Any]]:
    """Identify questions asked across 2 or more distinct years using difflib similarity > 0.8.

    Args:
        papers: List of paper tuples (paper_id, year, text) or (year, text).

    Returns:
        List of dicts sorted by recurrence, each containing:
            - "text": Cleaned question text
            - "years": List of distinct years the question appeared in
            - "count": Number of years appeared
            - "marks": Extracted marks
    """
    if not papers:
        return []

    # Extract all questions across papers with their year
    all_questions: List[Dict[str, Any]] = []

    for p in papers:
        pid, y_str, text = _parse_paper_tuple(p)
        y_int = _year_num(y_str)
        if y_int == 0:
            m = re.search(r"20\d{2}", text[:1000])
            if m:
                y_str = m.group(0)

        chunks = split_into_questions(text)
        for idx, chunk in enumerate(chunks, start=1):
            cleaned = _clean_question_text(chunk)
            norm_match = _normalize_question_for_match(chunk)
            if len(norm_match) < 15:
                continue  # skip short section headers or fragments
            marks = extract_marks(chunk)
            q_no = _extract_q_no(chunk, idx)
            all_questions.append({
                "text": cleaned,
                "norm_match": norm_match,
                "year": y_str,
                "marks": marks,
                "q_no": q_no,
            })

    # Cluster questions by difflib.SequenceMatcher ratio > 0.8
    clusters: List[Dict[str, Any]] = []

    for q in all_questions:
        q_norm = q["norm_match"]
        matched_cluster = None

        for cluster in clusters:
            ratio = difflib.SequenceMatcher(None, q_norm, cluster["norm_match"]).ratio()
            if ratio > 0.8:
                matched_cluster = cluster
                break

        if matched_cluster:
            matched_cluster["years"].add(q["year"])
            if q["marks"] > matched_cluster["marks"]:
                matched_cluster["marks"] = q["marks"]
            # Retain the more descriptive question text
            if len(q["text"]) > len(matched_cluster["text"]):
                matched_cluster["text"] = q["text"]
        else:
            clusters.append({
                "text": q["text"],
                "norm_match": q_norm,
                "years": {q["year"]},
                "marks": q["marks"],
            })

    # Filter to questions that appeared in 2 or more distinct years
    repeated: List[Dict[str, Any]] = []
    for c in clusters:
        if len(c["years"]) >= 2:
            years_list = sorted(list(c["years"]), key=_year_num, reverse=True)
            repeated.append({
                "text": c["text"],
                "years": years_list,
                "count": len(years_list),
                "marks": c["marks"],
            })

    # Sort repeated questions by count (years appeared) descending, then newest year
    repeated.sort(
        key=lambda item: (item["count"], _year_num(item["years"][0]) if item["years"] else 0),
        reverse=True,
    )
    return repeated
