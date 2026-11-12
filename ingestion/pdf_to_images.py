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

from ingestion.vision_ocr import is_vision_available, needs_vision_for_digital_page

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


def _digital_page_needs_vision(page: "fitz.Page", text: str) -> bool:
    """Check if a digital-text PDF page also contains diagrams/circuits/broken math."""
    if not is_vision_available():
        return False
    has_diagram_image = False
    drawing_count = 0
    try:
        has_diagram_image = any(
            info.get("width", 0) > 80 and info.get("height", 0) > 80
            for info in page.get_image_info()
        )
    except Exception:
        try:
            has_diagram_image = len(page.get_images(full=True)) > 0
        except Exception:
            has_diagram_image = False
    try:
        drawing_count = len(page.get_drawings())
    except Exception:
        drawing_count = 0

    needed, _ = needs_vision_for_digital_page(
        text,
        has_diagram_image=has_diagram_image,
        drawing_count=drawing_count,
    )
    return needed


def iter_pages(
    pdf_path: Path,
    dpi: int = SCAN_DPI,
) -> Iterator[Tuple[int, str, Optional[Image.Image]]]:
    """Yield ``(page_num, text, image_or_None)`` for every page, lazily.

    - Pure text-based pages: yields ``(n, text, None)``.  No image rendered.
    - Text pages flagged for diagrams/broken math (when Gemini Vision is configured):
      yields ``(n, text, image)`` at 200 DPI so Vision can inspect the figure/formulas
      while preserving ``text`` as fallback.
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
                if _digital_page_needs_vision(page, text):
                    img = _render_page(page, dpi=min(dpi, 200))
                    yield (i, text, img)
                else:
                    yield (i, text, None)
            else:
                img = _render_page(page, dpi=dpi)
                yield (i, "", img)
    finally:
        doc.close()
