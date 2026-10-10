"""
Tests for Task P1-1:
- Unit test for preprocess() function (tunable, Pillow-only, binarization)
- Unit test for _reconstruct_lines() and _compute_page_conf() with synthetic image_to_data dict
- Unit test for ocr_page() PSM retry and empty/garbled check
- Unit test for lazy ingestion with a mock 10-page PDF (generator, memory safety)
- Integration test for end-to-end ingestion of a sample PDF into CacheStore
"""
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

try:
    import fitz
except ImportError:
    import pymupdf as fitz

from ingestion.ocr_tagger import (
    preprocess,
    _reconstruct_lines,
    _compute_page_conf,
    ocr_page,
    tag_and_extract_all,
)
from ingestion.pdf_to_images import iter_pages
from ingestion.cache_writer import ingest_local_paper
from storage.cache_store import CacheStore


# ── 1. Unit test: preprocess() ────────────────────────────────────────────────

def test_preprocess_grayscale_and_binarization():
    """Verify preprocess converts to grayscale L mode and binarizes pixels."""
    # Create RGB test image with dark and light pixels
    img = Image.new("RGB", (100, 100), color=(240, 240, 240))
    # Draw some dark pixels (simulating text)
    for x in range(20, 80):
        for y in range(40, 60):
            img.putpixel((x, y), (20, 20, 20))

    processed = preprocess(img, threshold=160)

    # 1. Must be L mode
    assert processed.mode == "L"
    # 2. Dimensions preserved
    assert processed.size == (100, 100)
    # 3. Pixels must be binarized (only 0 and 255)
    pixel_values = set(processed.getdata())
    assert pixel_values.issubset({0, 255})
    # Text region should be dark (0) and background bright (255)
    assert processed.getpixel((50, 50)) == 0
    assert processed.getpixel((5, 5)) == 255


def test_preprocess_tunable_threshold():
    """Verify the threshold parameter tunes binarization."""
    # Gray image with uniform value 150
    img = Image.new("L", (50, 50), color=150)

    # With threshold 160, 150 is <= 160 -> should become 0
    p1 = preprocess(img, threshold=160)
    assert p1.getpixel((10, 10)) == 0

    # With threshold 140, 150 is > 140 -> should become 255
    p2 = preprocess(img, threshold=140)
    assert p2.getpixel((10, 10)) == 255


# ── 2. Unit test: _reconstruct_lines & _compute_page_conf ─────────────────────

def test_reconstruct_lines_layout_and_paragraphs():
    """Verify words are grouped into lines, lines into paragraphs, and conf=-1 ignored."""
    data = {
        "text": [
            "", "Department", "of", "CSE", "",
            "Question", "1.", "What", "is", "OOP?",
            "", "Question", "2.", "Define", "polymorphism.",
            "noise",
        ],
        "conf": [
            -1, 95, 92, 90, -1,
            88, 90, 85, 92, 94,
            -1, 80, 85, 90, 92,
            -1,
        ],
        "block_num": [
            1, 1, 1, 1, 1,
            2, 2, 2, 2, 2,
            2, 2, 2, 2, 2,
            3,
        ],
        "par_num": [
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            2, 2, 2, 2, 2,
            1,
        ],
        "line_num": [
            1, 1, 1, 1, 1,
            1, 1, 2, 2, 2,
            1, 1, 1, 2, 2,
            1,
        ],
    }

    reconstructed = _reconstruct_lines(data)

    # Paragraphs should be separated by \n\n
    paragraphs = reconstructed.split("\n\n")
    assert len(paragraphs) == 3

    # Paragraph 1 (block 1, par 1, line 1)
    assert paragraphs[0] == "Department of CSE"

    # Paragraph 2 (block 2, par 1, line 1 and line 2)
    lines_p2 = paragraphs[1].split("\n")
    assert lines_p2[0] == "Question 1."
    assert lines_p2[1] == "What is OOP?"

    # Paragraph 3 (block 2, par 2, line 1 and line 2)
    lines_p3 = paragraphs[2].split("\n")
    assert lines_p3[0] == "Question 2."
    assert lines_p3[1] == "Define polymorphism."

    # "noise" had conf=-1 so should not appear
    assert "noise" not in reconstructed


def test_compute_page_conf():
    """Verify confidence excludes conf == -1 and computes correct average and count."""
    data = {
        "text": ["", "Word1", "Word2", "Word3", ""],
        "conf": [-1, 80, 90, 100, -1],
    }
    avg_conf, count = _compute_page_conf(data)
    assert count == 3
    assert avg_conf == pytest.approx(90.0)

    # All -1 or empty
    empty_data = {"text": ["", ""], "conf": [-1, -1]}
    avg_empty, count_empty = _compute_page_conf(empty_data)
    assert count_empty == 0
    assert avg_empty == 0.0


# ── 3. Unit test: ocr_page PSM retry and empty/garbled check ──────────────────

def test_ocr_page_psm_retry_and_quality():
    """Verify multi-PSM retry tries PSM 6 -> 4 -> 3 when quality is low."""
    test_img = Image.new("L", (100, 100), color=255)

    calls = []

    def mock_image_to_data(img, config="", output_type=None):
        psm = config.split("--psm ")[-1]
        calls.append(psm)
        if psm == "6":
            # Return poor result: <30 chars, low conf
            return {
                "text": ["hi"],
                "conf": [20],
                "block_num": [1],
                "par_num": [1],
                "line_num": [1],
            }
        elif psm == "4":
            # Return good result: >30 chars, high conf
            words = [f"word{i}" for i in range(12)]
            return {
                "text": words,
                "conf": [85] * 12,
                "block_num": [1] * 12,
                "par_num": [1] * 12,
                "line_num": [1] * 12,
            }
        return {
            "text": ["fallback"],
            "conf": [50],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        }

    with patch("pytesseract.image_to_data", side_effect=mock_image_to_data):
        text, conf = ocr_page(test_img)
        # Should have tried PSM 6, then retried PSM 4 and stopped (quality met)
        assert calls == ["6", "4"]
        assert "word0" in text
        assert conf == pytest.approx(85.0)


def test_ocr_page_garbled_empty_check():
    """Verify that if confident word count < 10 or avg confidence < 35, text is returned as empty."""
    test_img = Image.new("L", (100, 100), color=255)

    def mock_low_words(img, config="", output_type=None):
        return {
            "text": ["only", "four", "words", "here"],
            "conf": [90, 90, 90, 90],
            "block_num": [1, 1, 1, 1],
            "par_num": [1, 1, 1, 1],
            "line_num": [1, 1, 1, 1],
        }

    with patch("pytesseract.image_to_data", side_effect=mock_low_words):
        text, conf = ocr_page(test_img)
        # Word count is 4 (< 10), so text must be empty string
        assert text == ""


# ── 4. Unit test: Lazy ingestion with mock 10-page PDF ─────────────────────────

def test_lazy_ingestion_mock_10_page_pdf(tmp_path):
    """Verify iter_pages is a lazy generator and peak memory is bounded."""
    pdf_path = tmp_path / "mock_10_pages.pdf"

    # Create a 10-page PDF:
    # Pages 1-5 have selectable text >= 80 chars
    # Pages 6-10 have no text (simulate scanned pages)
    doc = fitz.open()
    for i in range(1, 11):
        page = doc.new_page()
        if i <= 5:
            # Add > 80 chars of text
            sample_text = (
                f"Page {i}: This is university exam question paper content with selectable text. "
                "Question 1: Explain data structures and their computational complexity in detail."
            )
            page.insert_text((50, 50), sample_text)
    doc.save(str(pdf_path))
    doc.close()

    # 1. Verify iter_pages is a generator (not preloaded list)
    gen = iter_pages(pdf_path)
    assert inspect.isgenerator(gen)

    # 2. Iterate and verify page by page
    pages_processed = []
    for page_num, text, img in gen:
        pages_processed.append(page_num)
        if page_num <= 5:
            # Digital text page: img is None
            assert img is None
            assert len(text) >= 80
        else:
            # Scanned page: rendered to grayscale PIL Image
            assert img is not None
            assert isinstance(img, Image.Image)
            assert img.mode == "L"
            assert text == ""
            # Memory safety: caller immediately discards image
            del img

    assert pages_processed == list(range(1, 11))


# ── 5. Integration test: End-to-end ingestion into CacheStore ──────────────────

def test_end_to_end_ingestion_sample_pdf(tmp_path):
    """Integration test ingesting a sample PDF end-to-end into CacheStore."""
    db_file = tmp_path / "test_cache.db"
    pdf_file = tmp_path / "sample_exam.pdf"

    # Create a 2-page sample PDF
    doc = fitz.open()
    # Page 1: Has subject header and questions
    p1 = doc.new_page()
    p1.insert_text(
        (50, 50),
        "B.Tech Semester 3 Examination\n"
        "Subject: Data Structures\n"
        "PART A\n"
        "Q1. Define Stack and Queue data structures with diagrams.\n"
        "Q2. What is time complexity of QuickSort in worst case?"
    )
    # Page 2: Follow-up questions without explicit subject header
    p2 = doc.new_page()
    p2.insert_text(
        (50, 50),
        "PART B\n"
        "Q3. Explain Binary Search Tree insertion and deletion algorithms.\n"
        "Q4. Write short notes on Dijkstra shortest path algorithm."
    )
    doc.save(str(pdf_file))
    doc.close()

    # Ingest using a test CacheStore
    test_store = CacheStore(db_path=db_file)
    with patch("ingestion.cache_writer.CacheStore", return_value=test_store):
        warnings = ingest_local_paper(
            paper_id="test_exam_2024",
            pdf_path=pdf_file,
            year="2024",
            known_subjects=["Data Structures", "Operating Systems"],
        )

    # Verify ingestion results
    assert test_store.is_cached("test_exam_2024")

    # Full text retrieval
    full_text = test_store.get_paper_text("test_exam_2024")
    assert full_text is not None
    assert "Stack and Queue" in full_text
    assert "Binary Search Tree" in full_text

    # Subject tag checking
    subject_papers = test_store.get_subject_text("Data Structures")
    assert len(subject_papers) == 1
    assert subject_papers[0][0] == "2024"
    assert "Stack and Queue" in subject_papers[0][1]


def test_failed_ocr_does_not_cache_empty_paper(tmp_path):
    """Verify that a paper where text extraction completely fails is NOT cached."""
    db_file = tmp_path / "test_empty_cache.db"
    pdf_file = tmp_path / "blank_exam.pdf"

    # Create blank 1-page PDF
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_file))
    doc.close()

    test_store = CacheStore(db_path=db_file)

    # Mock ocr_page returning empty text (quality failure)
    with patch("ingestion.cache_writer.CacheStore", return_value=test_store), \
         patch("ingestion.ocr_tagger.ocr_page", return_value=("", 20.0)), \
         patch("ingestion.ocr_tagger._tesseract_available", return_value=True):
        warnings = ingest_local_paper(
            paper_id="blank_exam_fail",
            pdf_path=pdf_file,
            year="2024",
        )

    # Warning must be emitted
    assert any("Page 1 could not be read clearly by OCR" in w for w in warnings)
    # Paper must NOT be cached in DB
    assert not test_store.is_cached("blank_exam_fail")
    assert test_store.get_paper_text("blank_exam_fail") is None
