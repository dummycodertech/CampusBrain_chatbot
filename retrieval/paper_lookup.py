"""Deterministic lookup: fetch cached text by known paper_id. No embeddings,
no similarity search -- the filter key is always exact at query time."""
from __future__ import annotations
from storage.cache_store import CacheStore


def get_paper_text(paper_id: str) -> str | None:
    return CacheStore().get_paper_text(paper_id)
