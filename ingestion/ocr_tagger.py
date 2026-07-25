"""
Sends each page image to Gemini Vision, extracting text and detecting subject
boundaries (headers/course codes) so a semester-wise, multi-subject PDF can be
split into per-subject sections without tagging every page by hand.

Only boundary pages need to be correctly classified: a page with no detected
header inherits the subject of the most recent page that had one
(forward-fill). This is far more reliable than classifying every page
independently from content alone.
"""
import json
import re
import time
from typing import List, Dict
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


def _get_retry_delay(e: Exception, default: int = 60) -> int:
    """Extract retryDelay from a Gemini ClientError response, or return a default."""
    try:
        # e.args[0] may be a string like "429 RESOURCE_EXHAUSTED. {...}"
        err_str = str(e)
        # Try to find retryDelay in the error details
        match = re.search(r"retryDelay.*?(\d+)s", err_str)
        if match:
            return int(match.group(1)) + 5  # add 5s buffer
        # Also check structured response attribute
        details = getattr(e, "response", None)
        if details:
            for detail in getattr(details, "get", lambda *a: {})('details', []):
                if 'retryDelay' in str(detail):
                    m = re.search(r'(\d+)s', str(detail.get('retryDelay', '')))
                    if m:
                        return int(m.group(1)) + 5
    except Exception:
        pass
    return default


def tag_and_extract_page(image: Image.Image, known_subjects: List[str]) -> dict:
    prompt = TAG_PROMPT.format(known_subjects=", ".join(known_subjects) or "unknown")
    # Retry up to 3 times on quota errors (429) with backoff
    for attempt in range(3):
        try:
            raw = generate_vision([prompt, image])
            break
        except Exception as e:
            # Detect rate limit by class name, status code attribute, or string
            is_rate_limit = (
                type(e).__name__ in ["ClientError", "APIError", "ResourceExhausted"]
                or getattr(e, "code", None) == 429
                or "429" in str(e)
                or "RESOURCE_EXHAUSTED" in str(e)
            )
            if is_rate_limit and attempt < 2:
                wait = _get_retry_delay(e, default=60 * (attempt + 1))
                print(f"[ocr_tagger] Rate limited (attempt {attempt+1}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[4:] if raw.lower().startswith("json") else raw
    return json.loads(raw.strip())


def tag_and_extract_all(images: List[Image.Image], known_subjects: List[str]) -> List[Dict]:
    """Returns [{"page_num", "subject", "text"}, ...] with subject forward-filled."""
    results = []
    current_subject = None
    for i, image in enumerate(images, start=1):
        # gemini-2.0-flash free tier: 15 RPM → safe at 1 request per 5s (12 RPM)
        # Add a small delay even before page 1 to avoid collisions with prior requests
        sleep_time = 2 if i == 1 else 5
        time.sleep(sleep_time)

        parsed = tag_and_extract_page(image, known_subjects)
        if parsed.get("has_new_subject_header") and parsed.get("subject"):
            current_subject = parsed["subject"]
        results.append({
            "page_num": i,
            "subject": current_subject or "Unknown",
            "text": parsed.get("text", ""),
        })
    return results
