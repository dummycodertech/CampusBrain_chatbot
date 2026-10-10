"""
SQLite-backed cache for OCR-extracted, subject-tagged PYQ text.

Ingestion writes here once per paper. Every query-time lookup reads from
here only -- nothing ever re-OCRs a page that's already cached.
"""
from __future__ import annotations
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Tuple, Any

DB_PATH = Path(__file__).parent / "cache.db"


class CacheStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=30)

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_outputs (
                    paper_id TEXT,
                    kind TEXT,
                    input_hash TEXT,
                    content TEXT,
                    created_at REAL,
                    PRIMARY KEY(paper_id, kind, input_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_cache (
                    query_norm TEXT PRIMARY KEY,
                    content TEXT,
                    created_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_log (
                    day TEXT,
                    kind TEXT,
                    n INTEGER,
                    PRIMARY KEY(day, kind)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS question_topics (
                    paper_id TEXT,
                    subject TEXT,
                    q_idx INTEGER,
                    q_no TEXT,
                    text TEXT,
                    marks INTEGER,
                    topic TEXT,
                    PRIMARY KEY(paper_id, subject, q_idx)
                )
                """
            )
            # Guarded migration: add ocr_conf column if it was added after the
            # table was first created (old deployments won't have it).
            existing_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(pages)")
            }
            if "ocr_conf" not in existing_cols:
                conn.execute("ALTER TABLE pages ADD COLUMN ocr_conf REAL")
                print("[cache_store] Migrated pages table: added ocr_conf column.")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subject ON pages(subject)")
            conn.commit()

    def save_page(
        self,
        paper_id: str,
        page_num: int,
        subject: str,
        year: str,
        text: str,
        ocr_conf: Optional[float] = None,
    ) -> None:
        """Persist one page.  Silently skips pages with empty text so we never
        cache garbage OCR output that would pollute downstream retrieval."""
        if not text or not text.strip():
            return  # never cache empty pages
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pages
                   (paper_id, page_num, subject, year, text, ocr_conf)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (paper_id, page_num, subject, year, text, ocr_conf),
            )
            conn.commit()

    def is_cached(self, paper_id: str) -> bool:
        """Return True only if the paper has at least one page with real text.

        A paper cached with all-empty text (e.g. from a previous failed OCR
        attempt) is treated as NOT cached so it gets re-ingested.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM pages WHERE paper_id = ? AND TRIM(text) != '' LIMIT 1",
                (paper_id,),
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

    def get_subject_papers(self, subject: str) -> List[Tuple[str, str, str]]:
        """Return [(paper_id, year, text_of_only_pages_tagged_with_subject)] ordered by page_num.

        If a paper's year is empty or 'Uploaded', detects it from the first page text
        with r'20\\d{2}'; keeps 'Uploaded' if none found.
        """
        with self._connect() as conn:
            paper_rows = conn.execute(
                "SELECT DISTINCT paper_id, year FROM pages WHERE LOWER(subject) = LOWER(?) ORDER BY paper_id",
                (subject,),
            ).fetchall()

            results = []
            for paper_id, stored_year in paper_rows:
                page_rows = conn.execute(
                    """SELECT page_num, text FROM pages
                       WHERE paper_id = ? AND LOWER(subject) = LOWER(?) AND TRIM(text) != ''
                       ORDER BY page_num""",
                    (paper_id, subject),
                ).fetchall()

                if not page_rows:
                    continue

                tagged_text = "\n\n".join(r[1] for r in page_rows)

                # Year detection: if empty or 'Uploaded', detect from first page text
                year = (stored_year or "").strip()
                if not year or year.lower() == "uploaded":
                    first_page_row = conn.execute(
                        "SELECT text FROM pages WHERE paper_id = ? ORDER BY page_num LIMIT 1",
                        (paper_id,),
                    ).fetchone()
                    first_text = first_page_row[0] if first_page_row else page_rows[0][1]
                    m = re.search(r"20\d{2}", first_text)
                    if m:
                        year = m.group(0)
                    else:
                        year = "Uploaded"

                results.append((paper_id, year, tagged_text))

        return results

    def get_paper_subject(self, paper_id: str) -> Optional[str]:
        """Return the most common non-'Unknown' subject among that paper's pages."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT subject, COUNT(*) as cnt FROM pages
                   WHERE paper_id = ? AND LOWER(subject) != 'unknown' AND TRIM(subject) != ''
                   GROUP BY subject
                   ORDER BY cnt DESC
                   LIMIT 1""",
                (paper_id,),
            ).fetchone()
            return row[0] if row else None

    def get_output(self, paper_id: str, kind: str, input_hash: str) -> Optional[Any]:
        """Fetch cached generated output for (paper_id, kind, input_hash)."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT content FROM generated_outputs
                   WHERE paper_id = ? AND kind = ? AND input_hash = ?""",
                (paper_id, kind, input_hash),
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except Exception:
                return row[0]

    def save_output(self, paper_id: str, kind: str, input_hash: str, content: Any) -> None:
        """Persist generated output as JSON with timestamp."""
        now = time.time()
        serialized = json.dumps(content)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO generated_outputs
                   (paper_id, kind, input_hash, content, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (paper_id, kind, input_hash, serialized, now),
            )
            conn.commit()

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Lowercase with collapsed whitespace."""
        return " ".join(query.lower().split())

    def get_web(self, query: str) -> Optional[Any]:
        """Fetch web cache entry. Expires after 24h (86400s). Query is normalized."""
        query_norm = self._normalize_query(query)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content, created_at FROM web_cache WHERE query_norm = ?",
                (query_norm,),
            ).fetchone()
            if not row:
                return None
            content_str, created_at = row
            if time.time() - created_at > 86400:
                conn.execute("DELETE FROM web_cache WHERE query_norm = ?", (query_norm,))
                conn.commit()
                return None
            try:
                return json.loads(content_str)
            except Exception:
                return content_str

    def save_web(self, query: str, content: Any) -> None:
        """Persist web search results as JSON with 24h timestamp."""
        query_norm = self._normalize_query(query)
        now = time.time()
        serialized = json.dumps(content)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO web_cache (query_norm, content, created_at)
                   VALUES (?, ?, ?)""",
                (query_norm, serialized, now),
            )
            conn.commit()

    def bump_usage(self, kind: str) -> None:
        """Increment today's UTC usage counter for `kind` in one transaction."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO usage_log (day, kind, n)
                   VALUES (?, ?, 1)
                   ON CONFLICT(day, kind) DO UPDATE SET n = n + 1""",
                (today, kind),
            )
            conn.commit()

    def get_usage(self, kind: str) -> int:
        """Return today's UTC usage count for `kind`, or 0 if none recorded."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT n FROM usage_log WHERE day = ? AND kind = ?",
                (today, kind),
            ).fetchone()
            return row[0] if row else 0

    def has_topic_map(self, paper_id: str, subject: str) -> bool:
        """Return True if a topic map exists for (paper_id, subject)."""
        sub = (subject or "").strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM question_topics WHERE paper_id = ? AND subject = ? LIMIT 1",
                (paper_id, sub),
            ).fetchone()
            return row is not None

    def save_topic_map(self, paper_id: str, subject: str, rows: List[Dict[str, Any]]) -> None:
        """Replace topic map for (paper_id, subject) in one transaction."""
        sub = (subject or "").strip().lower()
        with self._connect() as conn:
            conn.execute("DELETE FROM question_topics WHERE paper_id = ? AND subject = ?", (paper_id, sub))
            for r in rows:
                conn.execute(
                    """INSERT INTO question_topics (paper_id, subject, q_idx, q_no, text, marks, topic)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        paper_id,
                        sub,
                        int(r["q_idx"]),
                        str(r.get("q_no", "")),
                        str(r.get("text", "")),
                        int(r.get("marks", 0) or 0),
                        str(r.get("topic", "")),
                    ),
                )
            conn.commit()

    def get_topic_map(self, paper_id: str, subject: str) -> List[Dict[str, Any]]:
        """Return cached topic map rows ordered by q_idx."""
        sub = (subject or "").strip().lower()
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT q_idx, q_no, text, marks, topic
                   FROM question_topics
                   WHERE paper_id = ? AND subject = ?
                   ORDER BY q_idx""",
                (paper_id, sub),
            )
            return [
                {
                    "q_idx": row[0],
                    "q_no": row[1],
                    "text": row[2],
                    "marks": row[3],
                    "topic": row[4],
                }
                for row in cursor.fetchall()
            ]

    def get_subject_topics(self, subject: str, limit: int = 40) -> List[str]:
        """Return distinct topics for a subject ordered by frequency."""
        sub = (subject or "").strip().lower()
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT topic, COUNT(*) as cnt
                   FROM question_topics
                   WHERE subject = ? AND topic IS NOT NULL AND TRIM(topic) != ''
                   GROUP BY topic
                   ORDER BY cnt DESC
                   LIMIT ?""",
                (sub, limit),
            )
            return [row[0] for row in cursor.fetchall()]

    def get_subject_questions(self, subject: str, limit: int = 600) -> List[Tuple[str, str]]:
        """Return [(text, topic)] from tagged rows of subject, excluding 'Other' and 'Uncategorized'."""
        sub = (subject or "").strip().lower()
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT text, topic
                   FROM question_topics
                   WHERE subject = ?
                     AND LOWER(topic) NOT IN ('other', 'uncategorized')
                     AND TRIM(text) != ''
                   LIMIT ?""",
                (sub, limit),
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]

