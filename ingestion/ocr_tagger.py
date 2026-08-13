"""
Tags and extracts text from PDF pages.

For text-based pages (already extracted by PyMuPDF), just detect subject
headers from the text directly — zero API calls needed.

For image-based / scanned pages, ALL pages are sent to Gemini Vision in a
SINGLE batched multimodal request instead of one call per page.

Quota impact
------------
Old approach:  1 Gemini API call × N scanned pages  →  N RPD used per paper
New approach:  ALL scanned pages in 1 Gemini call    →  1 RPD used per paper

Gemini 2.5 Flash supports up to 3,600 image frames per request.  A typical
20-page PYQ uses ~1 RPD.  With 20 RPD/day free tier you can now process
~20 full scanned papers per day instead of just 1.

Chunking
--------
Very large PDFs (>MAX_PAGES_PER_BATCH image pages) are split into chunks so
each chunk stays well within Gemini's per-request token limits.

Fallback
--------
If a batch call fails (e.g. transient error, oversized chunk), the affected
pages fall back to individual per-page calls — the same behaviour as before.
"""
import json
import re
from typing import List, Dict, Tuple, Optional
from PIL import Image
from services.llm_client import generate_vision_batch, generate_vision

# Max scanned pages per Gemini call. 15 is conservative; the API supports
# up to 3,600 but smaller chunks produce more reliable JSON parsing.
MAX_PAGES_PER_BATCH = 15

# ── Prompts ────────────────────────────────────────────────────────────────────

# Used for the batch call (multiple images in one request).
BATCH_TAG_PROMPT = """You are reading {n_pages} pages from a scanned university exam paper (PYQ bundle).
I am sending you {n_pages} page images IN ORDER (page numbers: {page_nums}).
This bundle may mix multiple subjects; each subject starts on a new page with a header.
Known subjects (use exact name if header matches): {known_subjects}

For EACH page image (in the exact order sent), extract all text and detect subject headers.

Return ONLY valid JSON, no other text, in this exact shape:
{{"pages": [
  {{"page_num": <int>, "has_new_subject_header": <true|false>, "subject": "<name or null>", "text": "<full extracted text of this page>"}},
  ... one entry per page, in the same order as the images sent ...
]}}"""

# Used as a fallback for a single page when the batch call fails.
SINGLE_TAG_PROMPT = """You are reading one page from a scanned university exam paper (PYQ bundle).
Known subjects (use exact name if header matches): {known_subjects}

Return ONLY valid JSON, no other text, in this exact shape:
{{"has_new_subject_header": true or false,
  "subject": "detected subject name, or null if has_new_subject_header is false",
  "text": "the full extracted text of this page"}}"""

# Simple header patterns to detect subject changes in text-extracted pages
# without using the API.
_HEADER_PATTERNS = [
    re.compile(r"(?i)^(UNIT[\s\-]+\d|MODULE[\s\-]+\d|PART[\s\-]+[A-Z\d])", re.MULTILINE),
    re.compile(r"(?i)(B\.?Tech|M\.?Tech|B\.?E|B\.?Sc).*(semester|sem)", re.MULTILINE),
    re.compile(r"(?i)(examination|exam|paper|subject)\s*[-:]\s*\S"),
]


# ── Text-page helpers (free, no API) ──────────────────────────────────────────

def _detect_subject_from_text(text: str, known_subjects: List[str]) -> Optional[str]:
    """Check if a text page has a new subject header using string matching."""
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


# ── Vision helpers ─────────────────────────────────────────────────────────────

def _strip_fences(raw: str) -> str:
    """Remove markdown code fences the model occasionally adds around JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


def tag_vision_batch(
    images: List[Image.Image],
    page_indices: List[int],
    known_subjects: List[str],
) -> List[dict]:
    """Send a chunk of scanned pages to Gemini Vision in ONE API call.

    Returns a list of per-page dicts:
        [{"page_num": N, "has_new_subject_header": bool, "subject": str|None, "text": str}, ...]

    Raises on any API / JSON error so the caller can fall back to per-page.
    """
    n = len(images)
    prompt = BATCH_TAG_PROMPT.format(
        n_pages=n,
        page_nums=", ".join(str(i) for i in page_indices),
        known_subjects=", ".join(known_subjects) or "unknown",
    )
    raw = generate_vision_batch(prompt, images)
    data = json.loads(_strip_fences(raw))
    pages = data.get("pages", [])

    # Sanity-check: model must return one entry per image sent.
    if len(pages) != n:
        raise ValueError(
            f"Batch response has {len(pages)} entries but {n} images were sent. "
            "Falling back to per-page."
        )
    return pages


def tag_vision_page(image: Image.Image, known_subjects: List[str]) -> dict:
    """Single-page fallback: OCR one image via Gemini Vision."""
    prompt = SINGLE_TAG_PROMPT.format(
        known_subjects=", ".join(known_subjects) or "unknown"
    )
    raw = generate_vision([prompt, image])
    return json.loads(_strip_fences(raw))


# ── Main entry point ───────────────────────────────────────────────────────────

def tag_and_extract_all(
    pages: List[Tuple[str, Optional[Image.Image]]],
    known_subjects: List[str],
) -> List[Dict]:
    """Process all pages of a PDF.

    Each element of `pages` is (extracted_text, image_or_None) as returned
    by pdf_to_pages():
      - image_or_None is None  → text-based page, processed locally for free.
      - image_or_None is Image → scanned page, sent to Gemini Vision.

    ALL scanned pages are batched into as few Gemini calls as possible
    (ideally 1 call for the whole PDF).  Per-page fallback is used if a
    batch call fails.

    Returns [{\"page_num\", \"subject\", \"text\"}, ...] with subject forward-filled.
    """
    # ── Step 1: Process text pages locally; collect image pages ───────────────
    text_page_results: Dict[int, dict] = {}
    image_page_queue: List[Tuple[int, Image.Image]] = []  # (1-based page_num, image)

    for i, (text, image) in enumerate(pages, start=1):
        if image is None:
            parsed = tag_text_page(text, known_subjects, i)
            text_page_results[i] = parsed
            print(f"[ocr_tagger] Page {i}: text extraction (no API call)")
        else:
            image_page_queue.append((i, image))

    print(
        f"[ocr_tagger] {len(text_page_results)} text page(s) extracted free. "
        f"{len(image_page_queue)} scanned page(s) queued for Vision OCR."
    )

    # ── Step 2: Batch-OCR all scanned pages ───────────────────────────────────
    image_page_results: Dict[int, dict] = {}
    total_api_calls = 0

    if image_page_queue:
        # Chunk into groups of MAX_PAGES_PER_BATCH
        chunks = [
            image_page_queue[start: start + MAX_PAGES_PER_BATCH]
            for start in range(0, len(image_page_queue), MAX_PAGES_PER_BATCH)
        ]
        print(
            f"[ocr_tagger] Sending {len(image_page_queue)} scanned page(s) "
            f"in {len(chunks)} batch call(s) (max {MAX_PAGES_PER_BATCH} pages/call)."
        )

        for chunk_idx, chunk in enumerate(chunks, start=1):
            chunk_indices = [p for p, _ in chunk]
            chunk_images  = [img for _, img in chunk]

            try:
                batch_results = tag_vision_batch(chunk_images, chunk_indices, known_subjects)
                total_api_calls += 1
                for r in batch_results:
                    image_page_results[r["page_num"]] = r
                print(
                    f"[ocr_tagger] Batch {chunk_idx}/{len(chunks)}: "
                    f"{len(chunk_images)} pages → 1 API call ✓"
                )

            except Exception as batch_err:
                print(
                    f"[ocr_tagger] Batch {chunk_idx} failed ({type(batch_err).__name__}: {batch_err}). "
                    f"Falling back to per-page for {len(chunk)} page(s)."
                )
                for page_num, img in chunk:
                    try:
                        parsed = tag_vision_page(img, known_subjects)
                        parsed["page_num"] = page_num
                        image_page_results[page_num] = parsed
                        total_api_calls += 1
                        print(f"[ocr_tagger] Page {page_num}: per-page fallback OCR ✓")
                    except Exception as page_err:
                        print(
                            f"[ocr_tagger] Page {page_num}: OCR failed "
                            f"({type(page_err).__name__}: {page_err}) — empty text."
                        )
                        image_page_results[page_num] = {
                            "page_num": page_num,
                            "has_new_subject_header": False,
                            "subject": None,
                            "text": "",
                        }

    # ── Step 3: Merge results in page order with subject forward-fill ──────────
    results = []
    current_subject = None

    for i in range(1, len(pages) + 1):
        parsed = text_page_results.get(i) or image_page_results.get(i, {})

        if parsed.get("has_new_subject_header") and parsed.get("subject"):
            current_subject = parsed["subject"]

        results.append({
            "page_num": i,
            "subject": current_subject or "Unknown",
            "text": parsed.get("text", ""),
        })

    print(
        f"[ocr_tagger] Done: {len(pages)} total pages, "
        f"{len(text_page_results)} text (0 API calls), "
        f"{len(image_page_queue)} scanned ({total_api_calls} API call(s))."
    )
    return results
