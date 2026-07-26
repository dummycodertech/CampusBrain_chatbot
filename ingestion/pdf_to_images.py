"""
Smart PDF ingestion: tries direct text extraction first (PyMuPDF), falls back
to Gemini Vision OCR only for pages that are image-based / scanned.

For a typical university PYQ PDF with selectable text this means zero Gemini
API calls. OCR is only triggered when a page's extracted text is below the
MIN_TEXT_CHARS threshold (indicating it's a scanned/image page).
"""
import io
from pathlib import Path
from typing import List, Tuple, Optional
import requests

try:
    import fitz  # PyMuPDF < 1.25
except ImportError:
    import pymupdf as fitz  # PyMuPDF >= 1.25

from PIL import Image

# Pages with fewer than this many characters after text extraction are
# treated as image-based and sent to Gemini Vision OCR.
MIN_TEXT_CHARS = 80


def fetch_pdf(pdf_url: str, dest: Path) -> Path:
    """Downloads a PDF from a public URL to a local path."""
    response = requests.get(pdf_url, timeout=30)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def _page_to_image(page: fitz.Page, dpi: int = 200) -> Image.Image:
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return Image.open(io.BytesIO(pix.tobytes("png")))


def pdf_to_pages(
    pdf_path: Path,
    dpi: int = 200,
) -> List[Tuple[str, Optional[Image.Image]]]:
    """Return a list of (extracted_text, image_or_None) tuples, one per page.

    - If a page has sufficient selectable text, image_or_None is None (no
      need to render or OCR it).
    - If a page is image-based / scanned, extracted_text is '' and
      image_or_None is a PIL Image ready for Gemini Vision.
    """
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        text = page.get_text("text").strip()
        if len(text) >= MIN_TEXT_CHARS:
            # Text-based page — no OCR needed
            pages.append((text, None))
        else:
            # Image-based or scanned page — render and queue for OCR
            img = _page_to_image(page, dpi=dpi)
            pages.append(("", img))
    doc.close()
    return pages


# ---------------------------------------------------------------------------
# Legacy helper kept for any callers that still expect a list of images.
# Returns only the pages that need OCR (image-based).
# ---------------------------------------------------------------------------
def pdf_to_page_images(pdf_path: Path, dpi: int = 200) -> List[Image.Image]:
    """Renders every page to a PIL Image (legacy interface, still used by
    ingest_paper for URL-fetched PDFs where we don't have the fitz doc yet).
    Prefer pdf_to_pages() for new code.
    """
    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    doc.close()
    return images
