"""
Runs the full ingestion pipeline for one paper: fetch -> split -> OCR/tag -> cache.
Called once per paper (checks the cache first), never on a live query.
"""
from pathlib import Path
import tempfile
from typing import List, Optional

from ingestion.pdf_to_images import fetch_pdf, pdf_to_pages
from ingestion.ocr_tagger import tag_and_extract_all
from ingestion.subject_reference import get_expected_subjects
from storage.cache_store import CacheStore


def ingest_paper(
    paper_id: str,
    pdf_url: str,
    year: str,
    branch: str = "",
    semester: str = "",
    known_subjects: Optional[List[str]] = None,
) -> None:
    """
    known_subjects, if not passed explicitly, is looked up locally from
    data/subjects_by_semester.json using branch+semester -- the frontend
    never needs to supply a subject array, just the branch/semester strings
    it already tracks for catalog filtering.
    """
    if known_subjects is None:
        known_subjects = get_expected_subjects(branch, semester)

    store = CacheStore()
    if store.is_cached(paper_id):
        return  # already ingested, don't re-OCR

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = fetch_pdf(pdf_url, Path(tmp) / f"{paper_id}.pdf")
        pages = pdf_to_pages(pdf_path)
        tagged_pages = tag_and_extract_all(pages, known_subjects)

        for page in tagged_pages:
            store.save_page(
                paper_id=paper_id,
                page_num=page["page_num"],
                subject=page["subject"],
                year=year,
                text=page["text"],
            )

def ingest_local_paper(
    paper_id: str,
    pdf_path: Path,
    year: str = "Unknown",
    known_subjects: Optional[List[str]] = None,
) -> None:
    """Ingest a locally provided PDF file directly."""
    if known_subjects is None:
        known_subjects = ["Unknown"]

    store = CacheStore()
    if store.is_cached(paper_id):
        return  # already ingested

    pages = pdf_to_pages(pdf_path)
    tagged_pages = tag_and_extract_all(pages, known_subjects)

    for page in tagged_pages:
        store.save_page(
            paper_id=paper_id,
            page_num=page["page_num"],
            subject=page["subject"],
            year=year,
            text=page["text"],
        )
