"""
Deterministic lookup across every cached paper tagged with a given subject,
used for cross-year questions like "what's the most repeated topic".
Filter by subject (already tagged at ingestion), not a semantic search.
"""
from typing import List, Tuple
from storage.cache_store import CacheStore


def get_subject_corpus(subject: str) -> List[Tuple[str, str]]:
    """Returns [(year, text), ...] for every paper tagged with this subject."""
    return CacheStore().get_subject_text(subject)
