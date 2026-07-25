"""
SQLite-backed cache for OCR-extracted, subject-tagged PYQ text.

Ingestion writes here once per paper. Every query-time lookup reads from
here only -- nothing ever re-OCRs a page that's already cached.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple

DB_PATH = Path(__file__).parent / "cache.db"


class CacheStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    paper_id TEXT NOT NULL,
                    page_num INTEGER NOT NULL,
                    subject TEXT,
                    year TEXT,
                    text TEXT NOT NULL,
                    PRIMARY KEY (paper_id, page_num)
                )
                """
            )
            conn.commit()

    def save_page(self, paper_id: str, page_num: int, subject: str, year: str, text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pages (paper_id, page_num, subject, year, text)
                   VALUES (?, ?, ?, ?, ?)""",
                (paper_id, page_num, subject, year, text),
            )
            conn.commit()

    def is_cached(self, paper_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM pages WHERE paper_id = ? LIMIT 1", (paper_id,)
            ).fetchone()
            return row is not None

    def get_paper_text(self, paper_id: str) -> Optional[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT text FROM pages WHERE paper_id = ? ORDER BY page_num",
                (paper_id,),
            ).fetchall()
            if not rows:
                return None
            return "\n\n".join(r[0] for r in rows)

    def get_subject_text(self, subject: str) -> List[Tuple[str, str]]:
        """Returns [(year, text), ...] for every cached paper tagged with this subject."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT paper_id, year FROM pages WHERE subject = ?",
                (subject,),
            ).fetchall()
        results = []
        for paper_id, year in rows:
            text = self.get_paper_text(paper_id)
            if text:
                results.append((year, text))
        return results
