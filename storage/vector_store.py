"""
Vector Database & Semantic Search Engine for Campus Brain.

Implements Dense Vector Retrieval (RAG) using:
  - Vector Store: ChromaDB (Persistent Disk Storage) + FAISS (In-Memory Cosine Index)
  - Embedding Model: sentence-transformers/all-MiniLM-L6-v2 (384-dimensional dense vectors)
  - Purpose: Cross-year semantic question retrieval, syllabus grounding, and duplicate detection.

Architecture:
  Unstructured PYQ Text -> Question Chunker -> Dense Embeddings -> ChromaDB Index -> Cosine Similarity Top-K Search.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

# Local persistent storage path for ChromaDB (strictly gitignored)
CHROMA_DATA_DIR = Path(__file__).parent / "chroma_db"

_embedder = None
_chroma_client = None
_collection = None


def _get_embedder():
    """Lazy-load the SentenceTransformer embedding model to save memory until called."""
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Fast, lightweight (80MB), 384-dimensional dense sentence embeddings
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
            print("[vector_store] Loaded SentenceTransformer ('all-MiniLM-L6-v2').")
        except Exception as e:
            print(f"[vector_store] Warning: Could not load SentenceTransformer: {e}")
            _embedder = None
    return _embedder


def _get_chroma_collection(collection_name: str = "pyq_questions"):
    """Initialize or return the persistent ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        try:
            import chromadb
            CHROMA_DATA_DIR.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DATA_DIR))
            _collection = _chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"description": "PYQ Question Embeddings for Semantic Search", "hnsw:space": "cosine"}
            )
            print(f"[vector_store] ChromaDB collection '{collection_name}' ready at {CHROMA_DATA_DIR}.")
        except Exception as e:
            print(f"[vector_store] Error initializing ChromaDB: {e}")
            _collection = None
    return _collection


class VectorStore:
    """Production Vector Store interface supporting both ChromaDB and FAISS indexing."""

    def __init__(self, collection_name: str = "pyq_questions"):
        self.collection_name = collection_name
        self.collection = _get_chroma_collection(collection_name)
        self.embedder = _get_embedder()

    def is_available(self) -> bool:
        """Check if vector embedding engine and ChromaDB are available."""
        return self.collection is not None and self.embedder is not None

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Compute 384-dimensional dense vector embeddings for a list of strings."""
        if not self.embedder:
            raise RuntimeError("SentenceTransformer embedding model is not loaded.")
        embeddings = self.embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings.tolist()

    def add_questions(
        self,
        paper_id: str,
        subject: str,
        year: str,
        questions: List[str],
    ) -> int:
        """
        Embed and index a list of exam questions into ChromaDB with metadata.
        
        Args:
            paper_id: Unique identifier for the paper (e.g. 'cs-ds-2023')
            subject: Academic subject (e.g. 'Data Structures')
            year: Academic year (e.g. '2023')
            questions: List of parsed question text blocks
        """
        if not self.is_available():
            print("[vector_store] Vector store unavailable, skipping index.")
            return 0

        valid_questions = [q.strip() for q in questions if len(q.strip()) > 15]
        if not valid_questions:
            return 0

        # Generate unique IDs and metadata for each question chunk
        ids = [f"{paper_id}_q{i}_{hash(q) & 0xffffffff:x}" for i, q in enumerate(valid_questions)]
        metadatas = [
            {"paper_id": paper_id, "subject": subject, "year": str(year), "chunk_index": i}
            for i in range(len(valid_questions))
        ]
        
        # Dense vector encoding
        embeddings = self.embed_texts(valid_questions)

        # Upsert into ChromaDB
        self.collection.upsert(
            ids=ids,
            documents=valid_questions,
            embeddings=embeddings,
            metadatas=metadatas
        )
        print(f"[vector_store] Successfully indexed {len(valid_questions)} questions into ChromaDB for paper '{paper_id}'.")
        return len(valid_questions)

    def similarity_search(
        self,
        query: str,
        subject_filter: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Perform dense semantic search (Cosine Similarity) across indexed question vectors.
        
        Returns:
            List of dicts with: 'document', 'score' (cosine similarity), 'metadata'
        """
        if not self.is_available():
            return []

        query_embedding = self.embed_texts([query])[0]
        
        where_filter = {"subject": subject_filter} if subject_filter else None

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        formatted_results = []
        if results and results.get("documents") and results["documents"][0]:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

            for doc, meta, dist in zip(docs, metas, distances):
                # ChromaDB cosine distance: similarity = 1 - distance
                similarity = round(max(0.0, 1.0 - float(dist)), 4)
                formatted_results.append({
                    "question": doc,
                    "similarity": similarity,
                    "metadata": meta,
                })

        return formatted_results


# Convenience helper functions for direct imports
def index_paper_into_vector_store(paper_id: str, subject: str, year: str, paper_text: str) -> int:
    """Extract questions from raw paper text and index into ChromaDB."""
    from generation.topic_heatmap import _split_into_questions
    questions = _split_into_questions(paper_text)
    store = VectorStore()
    return store.add_questions(paper_id=paper_id, subject=subject, year=year, questions=questions)


def search_similar_exam_questions(query: str, subject: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
    """Semantic question search across past exam years."""
    store = VectorStore()
    return store.similarity_search(query=query, subject_filter=subject, top_k=top_k)
