"""
Multi-paper lookup for cross-year analysis (Paper Predictor).

Fetches all cached papers for a given subject from SQLite.
Returns a list of (year, text) tuples, sorted by year ascending.
"""
from __future__ import annotations
from typing import List, Tuple
from storage.cache_store import CacheStore


def get_all_papers_for_subject(subject: str) -> List[Tuple[str, str]]:
    """
    Return [(year, full_text), ...] for every cached paper tagged with `subject`.
    Sorted by year ascending so cross-year analysis is chronological.
    Papers with empty text are silently dropped.
    """
    store = CacheStore()
    papers = store.get_subject_text(subject)

    # Filter blanks and sort chronologically
    papers = [(yr, txt) for yr, txt in papers if txt and len(txt.strip()) > 80]

    def _year_sort_key(item):
        try:
            return int(item[0])
        except (ValueError, TypeError):
            return 0

    return sorted(papers, key=_year_sort_key)
