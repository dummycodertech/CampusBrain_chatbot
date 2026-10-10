"""
Semantic Vector Search for Campus Brain.

Complements deterministic paper_lookup.py and subject_lookup.py with
Dense Vector Similarity Search (using ChromaDB + all-MiniLM-L6-v2 embeddings).

Used for:
  - Cross-year conceptual question search (e.g. "Find questions on Deadlock Avoidance")
  - Duplicate / recurring question detection across historical exam papers
  - Reference textbook & syllabus chunk retrieval
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from storage.vector_store import VectorStore, search_similar_exam_questions, index_paper_into_vector_store


def semantic_question_search(
    query: str,
    subject: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search for semantically similar exam questions across cached papers.
    Uses Cosine Similarity on dense 384-dimensional sentence embeddings.
    """
    return search_similar_exam_questions(query=query, subject=subject, top_k=top_k)


def index_paper_vectors(paper_id: str, subject: str, year: str, paper_text: str) -> int:
    """Index a new paper's questions into the persistent vector database."""
    return index_paper_into_vector_store(paper_id=paper_id, subject=subject, year=year, paper_text=paper_text)
