"""
Tags and extracts text from PDF pages.

For text-based pages (already extracted by PyMuPDF), just detect subject
headers from the text directly — zero API calls needed.

For image-based / scanned pages, calls Gemini Vision to OCR and detect headers.
"""
import json
import re
import time
from typing import List, Dict, Tuple, Optional
from PIL import Image
from services.llm_client import generate_vision

TAG_PROMPT = """You are reading a page from a college exam paper (PYQ) bundle.
This bundle may mix multiple subjects together, with each subject's paper
starting on a new page with a header, subject name, or course code.

Return ONLY valid JSON, no other text, in this exact shape:
{{"has_new_subject_header": true or false,
  "subject": "detected subject name, or null if has_new_subject_header is false",
  "text": "the full extracted text of this page"}}

Known subjects for this bundle (if the header matches one, use this exact name): {known_subjects}
"""

# Simple header patterns to detect subject changes in text-extracted pages
# without using the API.
_HEADER_PATTERNS = [
    re.compile(r"(?i)^(UNIT[\s\-]+\d|MODULE[\s\-]+\d|PART[\s\-]+[A-Z\d])", re.MULTILINE),
    re.compile(r"(?i)(B\.?Tech|M\.?Tech|B\.?E|B\.?Sc).*?(semester|sem)", re.MULTILINE),
    re.compile(r"(?i)(examination|exam|paper|subject)\s*[-:]\s*\S"),
]


def _detect_subject_from_text(text: str, known_subjects: List[str]) -> Optional[str]:
    """Check if a text page has a new subject header using string matching.
    Returns the matched subject name, or None if no header detected.
    """
    text_lower = text.lower()
    for subj in known_subjects:
        if subj.lower() in text_lower and len(subj) > 3:
            return subj
    return None


def tag_text_page(text: str, known_subjects: List[str], page_num: int) -> dict:
    """Process a text-extracted page without any API call."""
    subject = _detect_subject_from_text(text, known_subjects)
    return {
        "has_new_subject_header": subject is not None,
        "subject": subject,
        "text": text,
    }


def tag_vision_page(image: Image.Image, known_subjects: List[str]) -> dict:
    """OCR a scanned/image page via Gemini Vision. Key rotation and
    rate-limit retries are handled inside generate_vision.
    """
    prompt = TAG_PROMPT.format(known_subjects=", ".join(known_subjects) or "unknown")
    raw = generate_vision([prompt, image])
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[4:] if raw.lower().startswith("json") else raw
    return json.loads(raw.strip())


def tag_and_extract_all(
    pages: List[Tuple[str, Optional[Image.Image]]],
    known_subjects: List[str],
) -> List[Dict]:
    """Process all pages. Each element of `pages` is (extracted_text, image_or_None)
    as returned by pdf_to_pages().

    - Text pages: handled locally, no API call.
    - Image pages: sent to Gemini Vision with rate-limiting sleep.

    Returns [{"page_num", "subject", "text"}, ...] with subject forward-filled.
    """
    results = []
    current_subject = None
    vision_call_count = 0

    for i, (text, image) in enumerate(pages, start=1):
        if image is None:
            # Text-based page — free, instant
            parsed = tag_text_page(text, known_subjects, i)
            print(f"[ocr_tagger] Page {i}: text extraction (no API call)")
        else:
            # Image-based page — needs Gemini Vision
            # gemini-2.5-flash free tier: 5 RPM → need ≥12s between calls
            if vision_call_count > 0:
                time.sleep(15)
            parsed = tag_vision_page(image, known_subjects)
            vision_call_count += 1
            print(f"[ocr_tagger] Page {i}: Gemini Vision OCR (call #{vision_call_count})")

        if parsed.get("has_new_subject_header") and parsed.get("subject"):
            current_subject = parsed["subject"]

        results.append({
            "page_num": i,
            "subject": current_subject or "Unknown",
            "text": parsed.get("text", ""),
        })

    print(f"[ocr_tagger] Done: {len(pages)} pages, {vision_call_count} Vision API calls used.")
    return results
