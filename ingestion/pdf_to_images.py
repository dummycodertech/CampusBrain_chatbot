"""
Fetches a PDF from a public URL and splits it into per-page images for
Gemini Vision OCR.
"""
import io
from pathlib import Path
from typing import List
import requests
try:
    import fitz  # PyMuPDF < 1.25
except ImportError:
    import pymupdf as fitz  # PyMuPDF >= 1.25
from PIL import Image


def fetch_pdf(pdf_url: str, dest: Path) -> Path:
    """Downloads a PDF from a public URL to a local path."""
    response = requests.get(pdf_url, timeout=30)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def pdf_to_page_images(pdf_path: Path, dpi: int = 200) -> List[Image.Image]:
    """Renders every page of a PDF to a PIL Image, in page order."""
    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    doc.close()
    return images
