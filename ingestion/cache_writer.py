"""
Runs the full ingestion pipeline for one paper: fetch → split → OCR/tag → cache.
Called once per paper (checks the cache first), never on a live query.

Both public functions now return a list of warning strings that callers can
display as non-blocking UI messages.  An empty list means everything went fine.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import List, Optional

from ingestion.pdf_to_images import iter_pages
from ingestion.ocr_tagger import tag_and_extract_all
from ingestion.safe_fetch import fetch_pdf_bytes
from ingestion.subject_reference import get_expected_subjects
from storage.cache_store import CacheStore

PAPER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _validate_paper_id(paper_id: str) -> None:
    """Validate paperId against ^[A-Za-z0-9._-]{1,128}$ before use."""
    if not paper_id or not PAPER_ID_PATTERN.match(paper_id):
        try:
            import streamlit as st
            st.error(
                f"❌ **Invalid paperId:** `{paper_id}`.\n\n"
                "paperId must match `^[A-Za-z0-9._-]{1,128}$`."
            )
            st.stop()
        except Exception:
            pass
        raise ValueError(f"Invalid paperId: '{paper_id}'. Must match ^[A-Za-z0-9._-]{{1,128}}$.")


def ingest_paper(
    paper_id: str,
    pdf_url: str,
    year: str,
    branch: str = "",
    semester: str = "",
    known_subjects: Optional[List[str]] = None,
) -> List[str]:
    """Fetch a PYQ PDF by URL, OCR/tag every page, and cache the result.

    ``known_subjects``, if not passed explicitly, is looked up locally from
    ``data/subjects_by_semester.json`` using branch + semester — the frontend
    never needs to supply a subject array, just the branch/semester strings it
    already tracks for catalog filtering.

    Returns:
        List of warning strings (empty means success with no issues).
        Entries prefixed ``TESSERACT_MISSING:`` indicate the binary is absent.
    """
    _validate_paper_id(paper_id)

    if known_subjects is None:
        known_subjects = get_expected_subjects(branch, semester)

    store = CacheStore()
    if store.is_cached(paper_id):
        return []  # already ingested, don't re-OCR

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        try:
            pdf_bytes = fetch_pdf_bytes(pdf_url)
        except Exception as exc:
            try:
                import streamlit as st
                st.error(
                    f"❌ **Failed to download PDF:**\n\n"
                    f"{exc}\n\n"
                    "Please check the `pdfUrl` parameter and try again."
                )
                st.stop()
            except Exception:
                pass
            raise

        pdf_path = Path(tmp) / f"{paper_id}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        pages_iter = iter_pages(pdf_path)
        tagged_pages, warnings = tag_and_extract_all(pages_iter, known_subjects)

        for page in tagged_pages:
            store.save_page(
                paper_id=paper_id,
                page_num=page["page_num"],
                subject=page["subject"],
                year=year,
                text=page["text"],
                ocr_conf=page.get("ocr_conf"),
            )

    return warnings


def ingest_local_paper(
    paper_id: str,
    pdf_path: Path,
    year: str = "Unknown",
    known_subjects: Optional[List[str]] = None,
) -> List[str]:
    """Ingest a locally provided PDF file directly (upload mode).

    Returns:
        List of warning strings (empty means success with no issues).
    """
    _validate_paper_id(paper_id)

    if known_subjects is None:
        known_subjects = ["Unknown"]

    store = CacheStore()
    if store.is_cached(paper_id):
        return []  # already ingested

    pages_iter = iter_pages(pdf_path)
    tagged_pages, warnings = tag_and_extract_all(pages_iter, known_subjects)

    for page in tagged_pages:
        store.save_page(
            paper_id=paper_id,
            page_num=page["page_num"],
            subject=page["subject"],
            year=year,
            text=page["text"],
            ocr_conf=page.get("ocr_conf"),
        )

    return warnings
