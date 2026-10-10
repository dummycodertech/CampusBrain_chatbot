"""
Smart PDF ingestion for Campus Brain — lazy text-extraction + OCR pipeline.

Strategy
--------
- PyMuPDF (fitz) text extraction is tried on every page first because it is
  instant and free (no API call).  If the extracted text is >= MIN_TEXT_CHARS
  characters the page is yielded as (page_num, text, None) — no image rendered.
- If extracted text is below the threshold, the page is rendered to a PIL Image
  at SCAN_DPI (300 DPI default) and yielded as (page_num, "", image).
  The caller owns the image and must discard it after use.

Memory safety
-------------
iter_pages() is a generator: only ONE page image is alive at a time regardless
of document length.  The caller (ocr_tagger.tag_and_extract_all) processes each
yielded item and discards the image before moving to the next.

For a typical university PYQ PDF with selectable text this means zero images
are ever held in memory.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator, Optional, Tuple

import requests

try:
    import fitz  # PyMuPDF < 1.25
except ImportError:
    import pymupdf as fitz  # PyMuPDF >= 1.25

from PIL import Image

# Minimum character count for a page to be treated as text-based.
# Real text pages typically have hundreds of chars; scanned pages produce
# < 20 chars of garbage text from PyMuPDF.
MIN_TEXT_CHARS = 80

# DPI for rendering scanned pages. 300 DPI is the sweet spot for Tesseract:
# legible for small fonts, manageable memory (~3 MB per A4 page in grayscale).
SCAN_DPI = 300


def fetch_pdf(pdf_url: str, dest: Path) -> Path:
    """Download a PDF from a public URL to a local path."""
    response = requests.get(pdf_url, timeout=30)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def _render_page(page: "fitz.Page", dpi: int = SCAN_DPI) -> Image.Image:
    """Render a fitz Page to a PIL Image at the given DPI (grayscale).

    Grayscale conversion here saves ~66 % memory vs. RGB and is fine for
    text OCR — colour carries no information for Tesseract.
    """
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def iter_pages(
    pdf_path: Path,
    dpi: int = SCAN_DPI,
) -> Iterator[Tuple[int, str, Optional[Image.Image]]]:
    """Yield ``(page_num, text, image_or_None)`` for every page, lazily.

    - Text-based pages: yields ``(n, text, None)``.  No image rendered.
    - Scanned pages: yields ``(n, "", image)``.  Image is a grayscale PIL Image
      at ``dpi`` resolution.  The caller **must discard the image after use** —
      the generator never holds more than one image in memory at a time.

    ``page_num`` is 1-indexed (matches the ``pages`` SQLite table).
    """
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) >= MIN_TEXT_CHARS:
                yield (i, text, None)
            else:
                img = _render_page(page, dpi=dpi)
                yield (i, "", img)
    finally:
        doc.close()
