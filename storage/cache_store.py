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
from typing import Optional, List, Tuple, Any, Dict

DB_PATH = Path(__file__).parent / "cache.db"


_PLACEHOLDER_YEARS = {
    "", "uploaded", "unknown", "all years", "all", "unspecified", "none", "n/a",
}

_MONTH_PATTERN = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s,.\-/]*(20\d{2})\b",
    re.IGNORECASE,
)


def _extract_exam_label(
    text: str,
    stored_year: str = "",
    part_idx: int = 1,
    total_parts: int = 1,
) -> str:
    """Detect a concise exam year/label (e.g. 'Jan 2024', 'Mid Apr 2024', '2024', or 'Paper 2')."""
    base = (stored_year or "").strip()
    if total_parts == 1 and base.lower() not in _PLACEHOLDER_YEARS:
        return base

    head = (text or "")[:1200]
    is_mid = bool(re.search(r"\bmid[\s\-]*term\b", head[:500], re.IGNORECASE))

    m_mon = _MONTH_PATTERN.search(head)
    if m_mon:
        mon = m_mon.group(1)[:3].title()
        yr = m_mon.group(2)
        return f"Mid {mon} {yr}" if is_mid else f"{mon} {yr}"

    m_yr = re.search(r"\b(20\d{2})\b", head) or re.search(r"\b(20\d{2})\b", text or "")
    if m_yr:
        yr = m_yr.group(1)
        return f"Mid {yr}" if is_mid else yr

    if total_parts > 1:
        return f"Paper {part_idx}"
    return base if base else "Uploaded"


def _is_new_paper_page(page_text: str, prev_text: str) -> bool:
    """Heuristic to decide if page_text starts a new exam paper inside a merged PDF."""
    if not page_text or not page_text.strip():
        return False

    head = page_text[:900]
    tail_prev = (prev_text or "")[-200:]
    has_pto_prev = bool(re.search(r"p\.?\s*t\.?\s*o\.?\b", tail_prev, re.IGNORECASE))

    c_exam = bool(
        re.search(
            r"\b(?:end|mid|semester|annual|supplementary|sessional|internal)\s*[- ]*\s*(?:term|sem(?:ester)?)\b"
            r"|\b(?:end\s*term|mid\s*term|university)\s+examination\b",
            head,
            re.IGNORECASE,
        )
    )
    c_roll = bool(
        re.search(
            r"\bplease\s+write\s+your\s+exam|\bexam\s*\.?\s*roll\s*no|\broll\s*no\.?\s*[:\-_]",
            head,
            re.IGNORECASE,
        )
    )
    c_marks = bool(
        re.search(
            r"\bmax(?:imum)?\.?\s*marks\b|\bm\.?m\.?\s*[:\-]\s*\d+|\btime\s*[:\-]\s*\d+(?:\.\d+)?\s*(?:hr|hrs|hour|hours|min)",
            head,
            re.IGNORECASE,
        )
    )
    c_note = bool(
        re.search(r"\bnote\s*:\s*(?:attempt|answer|all\s+questions|q\.?\s*no)", head, re.IGNORECASE)
    )
    c_code = bool(re.search(r"\b(?:paper|subject|course)\s*code\b", head, re.IGNORECASE))
    c_degree = bool(
        re.search(r"\b(?:b\.?tech|m\.?tech|b\.?e\.?|bca|mca|b\.?sc)\b", head, re.IGNORECASE)
    )
    c_q1 = bool(
        re.search(
            r"(?:^|\n)\s*(?:Q\.?\s*1\b(?:\s*\(\s*a\s*\))?|Question\s*1\b|1\.\s+[A-Za-z]|PART[\s\-]*A\b|SECTION[\s\-]*A\b)",
            page_text[:700],
            re.IGNORECASE,
        )
    )

    strong_cover = sum([c_exam, c_roll, c_marks, c_note])
    all_cues = strong_cover + sum([c_code, c_degree, c_q1])

    # Clear cover banner (e.g. Roll No + Max Marks / End Term + Attempt)
    if strong_cover >= 2:
        return True

    # Respect P.T.O. continuation pages unless a full cover banner is present
    if has_pto_prev:
        return False

    if c_exam and all_cues >= 2:
        return True
    if c_roll:
        return True
    if c_marks and (c_q1 or c_code or c_degree or c_note):
        return True
    if c_q1 and all_cues >= 2:
        return True

    # Question numbering restart: previous page had Q2+ and this page restarts at Q1 / PART A
    # without being labelled Section/Part B-Z.
    prev_had_later_q = bool(
        re.search(r"(?:^|\n)\s*(?:Q\.?\s*[2-9]|Question\s*[2-9]|[2-9]\.\s+[A-Za-z])", prev_text or "", re.IGNORECASE)
    )
    is_later_section = bool(re.search(r"(?:PART|SECTION)\s*[B-Z]\b", head, re.IGNORECASE))
    if prev_had_later_q and c_q1 and not is_later_section:
        return True

    return False


def split_paper_pages(
    paper_id: str,
    page_rows: List[Tuple[int, str]],
    stored_year: str = "",
) -> List[Tuple[str, str, str]]:
    """Split a cached paper's pages into logical exam papers if it is a combined PDF.

    For a normal single exam paper (even multi-page), returns 1 tuple with the
    original ``paper_id``. For a merged multi-paper PDF, returns one tuple per
    detected exam paper with id ``f"{paper_id}#p{start_page}"``.
    """
    valid_pages = [(pn, txt) for pn, txt in page_rows if txt and txt.strip()]
    if not valid_pages:
        return []

    groups: List[List[Tuple[int, str]]] = [[valid_pages[0]]]
    for pn, txt in valid_pages[1:]:
        prev_txt = groups[-1][-1][1]
        if _is_new_paper_page(txt, prev_txt):
            groups.append([(pn, txt)])
        else:
            groups[-1].append((pn, txt))

    total_parts = len(groups)
    out: List[Tuple[str, str, str]] = []
    for idx, grp in enumerate(groups, start=1):
        sub_pid = paper_id if total_parts == 1 else f"{paper_id}#p{grp[0][0]}"
        combined_text = "\n\n".join(t for _, t in grp)
        label = _extract_exam_label(
            grp[0][1],
            stored_year=stored_year,
            part_idx=idx,
            total_parts=total_parts,
        )
        out.append((sub_pid, label, combined_text))

    return out


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

    def backfill_paper_subject(self, paper_id: str, subject: str) -> None:
        """Replace 'Unknown'/empty subject tags for paper_id when an explicit subject is known."""
        sub = (subject or "").strip()
        if not paper_id or not sub or sub.lower() == "unknown":
            return
        with self._connect() as conn:
            conn.execute(
                """UPDATE pages
                   SET subject = ?
                   WHERE paper_id = ?
                     AND (subject IS NULL OR TRIM(subject) = '' OR LOWER(subject) = 'unknown')""",
                (sub, paper_id),
            )
            conn.commit()

    def get_paper_splits(
        self,
        paper_id: str,
        stored_year: str = "",
        fallback_text: str = "",
    ) -> List[Tuple[str, str, str]]:
        """Return logical paper tuples [(sub_paper_id, year_or_label, text), ...] for a paper_id.

        Automatically splits combined/merged multi-paper PDFs stored under one paper_id
        into separate entries while leaving single multi-page papers intact.
        """
        page_rows: List[Tuple[int, str]] = []
        db_year = (stored_year or "").strip()

        if paper_id:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT page_num, text, year FROM pages
                       WHERE paper_id = ? AND TRIM(text) != ''
                       ORDER BY page_num""",
                    (paper_id,),
                ).fetchall()
                if rows:
                    page_rows = [(int(r[0]), str(r[1])) for r in rows]
                    if not db_year:
                        db_year = str(rows[0][2] or "").strip()

        if page_rows:
            return split_paper_pages(paper_id, page_rows, stored_year=db_year)

        if fallback_text and fallback_text.strip():
            raw_pages = [p.strip() for p in fallback_text.split("\f") if p.strip()]
            if len(raw_pages) > 1:
                return split_paper_pages(
                    paper_id or "current",
                    [(i, t) for i, t in enumerate(raw_pages, start=1)],
                    stored_year=db_year,
                )
            label = _extract_exam_label(fallback_text, stored_year=db_year, part_idx=1, total_parts=1)
            return [(paper_id or "current", label, fallback_text)]

        return []

    def get_subject_papers(self, subject: str) -> List[Tuple[str, str, str]]:
        """Return [(paper_id, year, text), ...] for every paper tagged with this subject.

        Automatically splits merged multi-paper PDFs (e.g. 5 papers in 5 pages under one
        paper_id) into individual sub-papers so Predictor, Mock Paper, and Top 5 Topics
        work across both single-paper PDFs and combined bundles.
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

                results.extend(
                    split_paper_pages(
                        paper_id,
                        [(int(r[0]), str(r[1])) for r in page_rows],
                        stored_year=(stored_year or "").strip(),
                    )
                )

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

