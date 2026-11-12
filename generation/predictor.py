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


_STOP_DOMAIN_WORDS = {
    "explain", "define", "state", "derive", "prove", "discuss", "write",
    "calculate", "find", "what", "how", "why", "which", "when", "where",
    "suitable", "example", "examples", "diagram", "diagrams", "neat",
    "theorem", "theorems", "following", "circuit", "circuits", "show",
    "shown", "below", "above", "between", "difference", "differentiate",
    "short", "note", "notes", "give", "with", "that", "this", "from",
    "into", "across", "obtain", "determine", "expression", "equation",
    "equations", "using", "used", "types", "different", "various",
}


def _strip_exam_clutter(text: str) -> str:
    """Remove asterisks, UNIT/CO tags, and marks clutter before display/matching."""
    t = re.sub(r"^\s*(?:\d+\s+)?CO\d\s*(?:\d+[a-zA-Z]?\s*\([a-zA-Z]\)|\(\w+\))?\s*", "", text, flags=re.I)
    t = re.sub(r"\*{2,}|-{2,}\s*UNIT[\s\-]*[IVX\d]+|\bUNIT[\s\-]*[IVX\d]+\b|\bCO[1-6]\b", " ", t, flags=re.I)
    return " ".join(t.split()).strip()


def _normalize_question_for_match(text: str) -> str:
    """Strip question prefix (e.g. 'Q1.', '(a)'), marks, and clutter for similarity comparison."""
    t = _strip_exam_clutter(text)
    t = re.sub(r"\[(?:Circuit|Diagram)[^\]]*\]", " ", t, flags=re.IGNORECASE)
    # Strip leading label
    t = re.sub(
        r"^\s*(?:Q\.?\s*\d+[a-zA-Z]?|\d+[a-zA-Z]?|\([a-zA-Z\d]+\)|[a-zA-Z])[.)]?\s*",
        "",
        t,
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


def _domain_tokens(norm_text: str) -> Set[str]:
    words = re.findall(r"[a-z]{3,}", norm_text.lower())
    return {w.rstrip("s") if len(w) > 4 and w.endswith("s") else w for w in words if w not in _STOP_DOMAIN_WORDS}




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

    for p_idx, p in enumerate(papers):
        pid, y_str, text = _parse_paper_tuple(p)
        paper_key = pid.strip() or f"paper_{p_idx}_{y_str}"
        y_int = _year_num(y_str)
        if y_int == 0:
            m = re.search(r"20\d{2}", text[:1000])
            if m:
                y_str = m.group(0)

        chunks = split_into_questions(text)
        for idx, chunk in enumerate(chunks, start=1):
            cleaned = _strip_exam_clutter(_clean_question_text(chunk))
            norm_match = _normalize_question_for_match(chunk)
            if len(norm_match) < 15:
                continue  # skip short section headers or fragments
            marks = extract_marks(chunk)
            q_no = _extract_q_no(chunk, idx)
            all_questions.append({
                "text": cleaned,
                "norm_match": norm_match,
                "tokens": _domain_tokens(norm_match),
                "year": y_str,
                "paper_key": paper_key,
                "marks": marks,
                "q_no": q_no,
            })

    # Cluster questions by sequence similarity (>= 0.72) OR strong domain-concept overlap
    clusters: List[Dict[str, Any]] = []

    for q in all_questions:
        q_norm = q["norm_match"]
        q_tokens = q["tokens"]
        matched_cluster = None

        for cluster in clusters:
            ratio = difflib.SequenceMatcher(None, q_norm, cluster["norm_match"]).ratio()
            is_match = ratio >= 0.72
            if not is_match and q_tokens and cluster["tokens"]:
                shared = q_tokens & cluster["tokens"]
                union = q_tokens | cluster["tokens"]
                jaccard = len(shared) / len(union) if union else 0.0
                if (len(shared) >= 2 and jaccard >= 0.45) or (len(shared) >= 3 and jaccard >= 0.35):
                    is_match = True
            if is_match:
                matched_cluster = cluster
                break

        if matched_cluster:
            matched_cluster["years"].add(q["year"])
            matched_cluster["paper_keys"].add(q["paper_key"])
            if q["marks"] > matched_cluster["marks"]:
                matched_cluster["marks"] = q["marks"]
            # Retain the more descriptive question text
            if len(q["text"]) > len(matched_cluster["text"]):
                matched_cluster["text"] = q["text"]
        else:
            clusters.append({
                "text": q["text"],
                "norm_match": q_norm,
                "tokens": set(q_tokens),
                "years": {q["year"]},
                "paper_keys": {q["paper_key"]},
                "marks": q["marks"],
            })

    # Filter to questions that appeared in 2 or more distinct papers
    repeated: List[Dict[str, Any]] = []
    for c in clusters:
        if len(c["paper_keys"]) >= 2:
            years_list = sorted(list(c["years"]), key=_year_num, reverse=True)
            repeated.append({
                "text": c["text"],
                "years": years_list,
                "count": len(c["paper_keys"]),
                "marks": c["marks"],
            })

    # Sort repeated questions by count (years appeared) descending, then newest year
    repeated.sort(
        key=lambda item: (item["count"], _year_num(item["years"][0]) if item["years"] else 0),
        reverse=True,
    )
    return repeated
