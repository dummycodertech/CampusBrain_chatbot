"""
Tags and extracts text from PDF pages.

OCR Strategy (priority order)
------------------------------
1. PyMuPDF text extraction (free, instant) — used for text-based pages.
2. Tesseract OCR (free, local, no quota) — used for scanned/image pages.
3. Gemini Vision (optional fallback) — only used if GEMINI_API_KEYS is set
   AND Tesseract returns too little text (< TESSERACT_MIN_CHARS chars).

This means the app works fully offline (OCR-wise) with no Gemini API key.
Gemini is kept as a quality-upgrade fallback for cases where Tesseract
struggles (e.g. dense math, poor scan quality).

Subject detection
-----------------
For all OCR engines, after extracting raw text we run lightweight regex +
string matching to detect subject-header pages.  No LLM call needed.
"""
import os
import re
from typing import List, Dict, Tuple, Optional
from PIL import Image

# ── Tesseract setup ────────────────────────────────────────────────────────────

def _tesseract_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_with_tesseract(image: Image.Image) -> str:
    """Run Tesseract on a PIL Image and return extracted text."""
    import pytesseract
    # PSM 6 = assume uniform block of text (best for exam papers)
    custom_config = r"--oem 3 --psm 6"
    return pytesseract.image_to_string(image, config=custom_config)


# ── Gemini setup (optional) ────────────────────────────────────────────────────

def _gemini_available() -> bool:
    keys = os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
    return bool(keys.strip())


# Minimum chars Tesseract must return before we skip Gemini fallback.
# If Tesseract returns fewer chars it likely failed on a poor scan.
TESSERACT_MIN_CHARS = 50

# ── Subject detection (regex, no LLM) ─────────────────────────────────────────

_HEADER_PATTERNS = [
    re.compile(r"(?i)^(UNIT[\s\-]+\d|MODULE[\s\-]+\d|PART[\s\-]+[A-Z\d])", re.MULTILINE),
    re.compile(r"(?i)(B\.?Tech|M\.?Tech|B\.?E|B\.?Sc).*(semester|sem)", re.MULTILINE),
    re.compile(r"(?i)(examination|exam|paper|subject)\s*[-:]\s*\S"),
]


def _detect_subject_from_text(text: str, known_subjects: List[str]) -> Optional[str]:
    """Check if a text page has a new subject header using string matching."""
    text_lower = text.lower()
    for subj in known_subjects:
        if subj.lower() in text_lower and len(subj) > 3:
            return subj
    return None


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences the model occasionally adds around JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Text-page helper (free, no API) ───────────────────────────────────────────

def tag_text_page(text: str, known_subjects: List[str], page_num: int) -> dict:
    """Process a text-extracted page without any API call."""
    subject = _detect_subject_from_text(text, known_subjects)
    return {
        "has_new_subject_header": subject is not None,
        "subject": subject,
        "text": text,
    }


# ── Tesseract OCR (primary for scanned pages) ─────────────────────────────────

def tag_vision_page_tesseract(image: Image.Image, known_subjects: List[str], page_num: int) -> dict:
    """OCR a scanned page using Tesseract. No API quota used."""
    text = _ocr_with_tesseract(image).strip()
    subject = _detect_subject_from_text(text, known_subjects)
    print(f"[ocr_tagger] Page {page_num}: Tesseract → {len(text)} chars extracted.")
    return {
        "has_new_subject_header": subject is not None,
        "subject": subject,
        "text": text,
    }


# ── Gemini Vision (optional quality-upgrade fallback) ─────────────────────────

GEMINI_SINGLE_PROMPT = """You are reading one page from a scanned university exam paper (PYQ bundle).
Known subjects (use exact name if header matches): {known_subjects}

Return ONLY valid JSON, no other text, in this exact shape:
{{"has_new_subject_header": true or false,
  "subject": "detected subject name, or null if has_new_subject_header is false",
  "text": "the full extracted text of this page"}}"""

GEMINI_BATCH_PROMPT = """You are reading {n_pages} pages from a scanned university exam paper (PYQ bundle).
I am sending you {n_pages} page images IN ORDER (page numbers: {page_nums}).
This bundle may mix multiple subjects; each subject starts on a new page with a header.
Known subjects (use exact name if header matches): {known_subjects}

For EACH page image (in the exact order sent), extract all text and detect subject headers.

Return ONLY valid JSON, no other text, in this exact shape:
{{"pages": [
  {{"page_num": <int>, "has_new_subject_header": <true|false>, "subject": "<name or null>", "text": "<full extracted text of this page>"}},
  ... one entry per page, in the same order as the images sent ...
]}}"""


def _tag_vision_page_gemini(image: Image.Image, known_subjects: List[str]) -> dict:
    """Single-page Gemini OCR (fallback for poor Tesseract results)."""
    import json
    from services.llm_client import generate_vision
    prompt = GEMINI_SINGLE_PROMPT.format(
        known_subjects=", ".join(known_subjects) or "unknown"
    )
    raw = generate_vision([prompt, image])
    return json.loads(_strip_fences(raw))


def _tag_vision_batch_gemini(
    images: List[Image.Image],
    page_indices: List[int],
    known_subjects: List[str],
) -> List[dict]:
    """Batch Gemini OCR for multiple pages in one API call."""
    import json
    from services.llm_client import generate_vision_batch
    n = len(images)
    prompt = GEMINI_BATCH_PROMPT.format(
        n_pages=n,
        page_nums=", ".join(str(i) for i in page_indices),
        known_subjects=", ".join(known_subjects) or "unknown",
    )
    raw = generate_vision_batch(prompt, images)
    data = json.loads(_strip_fences(raw))
    pages = data.get("pages", [])
    if len(pages) != n:
        raise ValueError(
            f"Batch response has {len(pages)} entries but {n} images were sent."
        )
    return pages


# ── Main entry point ───────────────────────────────────────────────────────────

MAX_PAGES_PER_BATCH = 15  # for Gemini batch calls only


def tag_and_extract_all(
    pages: List[Tuple[str, Optional[Image.Image]]],
    known_subjects: List[str],
) -> List[Dict]:
    """Process all pages of a PDF.

    Pipeline per scanned page:
      1. Tesseract OCR  (always tried first — free, no quota)
      2. Gemini Vision  (only if Tesseract returns < TESSERACT_MIN_CHARS AND
                         Gemini API keys are configured)

    Text-based pages are handled locally with zero API calls.

    Returns [{"page_num", "subject", "text"}, ...] with subject forward-filled.
    """
    use_tesseract = _tesseract_available()
    use_gemini = _gemini_available()

    if use_tesseract:
        print("[ocr_tagger] Tesseract available — using as primary OCR engine.")
    else:
        print("[ocr_tagger] WARNING: Tesseract not found. Install tesseract-ocr.")

    if use_gemini:
        print("[ocr_tagger] Gemini keys found — will use as fallback for poor Tesseract results.")
    else:
        print("[ocr_tagger] No Gemini keys — Tesseract only.")

    # ── Step 1: Process text pages locally; collect image pages ───────────────
    text_page_results: Dict[int, dict] = {}
    image_page_queue: List[Tuple[int, Image.Image]] = []

    for i, (text, image) in enumerate(pages, start=1):
        if image is None:
            parsed = tag_text_page(text, known_subjects, i)
            text_page_results[i] = parsed
            print(f"[ocr_tagger] Page {i}: text extraction (no OCR needed)")
        else:
            image_page_queue.append((i, image))

    print(
        f"[ocr_tagger] {len(text_page_results)} text page(s) free. "
        f"{len(image_page_queue)} scanned page(s) need OCR."
    )

    # ── Step 2: OCR all scanned pages ─────────────────────────────────────────
    image_page_results: Dict[int, dict] = {}

    # Pages that Tesseract couldn't read well — candidates for Gemini upgrade
    gemini_upgrade_queue: List[Tuple[int, Image.Image]] = []

    for page_num, img in image_page_queue:
        if use_tesseract:
            try:
                parsed = tag_vision_page_tesseract(img, known_subjects, page_num)
                parsed["page_num"] = page_num
                image_page_results[page_num] = parsed

                # Queue for Gemini upgrade if text is suspiciously short
                if len(parsed["text"]) < TESSERACT_MIN_CHARS and use_gemini:
                    print(
                        f"[ocr_tagger] Page {page_num}: Tesseract returned only "
                        f"{len(parsed['text'])} chars — queuing for Gemini upgrade."
                    )
                    gemini_upgrade_queue.append((page_num, img))

            except Exception as tess_err:
                print(f"[ocr_tagger] Page {page_num}: Tesseract failed ({tess_err}).")
                image_page_results[page_num] = {
                    "page_num": page_num,
                    "has_new_subject_header": False,
                    "subject": None,
                    "text": "",
                }
                if use_gemini:
                    gemini_upgrade_queue.append((page_num, img))
        else:
            # No Tesseract — go straight to Gemini if available
            if use_gemini:
                gemini_upgrade_queue.append((page_num, img))
            else:
                image_page_results[page_num] = {
                    "page_num": page_num,
                    "has_new_subject_header": False,
                    "subject": None,
                    "text": "",
                }
                print(f"[ocr_tagger] Page {page_num}: no OCR engine available — empty text.")

    # ── Step 3: Gemini upgrade for pages Tesseract struggled with ─────────────
    if gemini_upgrade_queue:
        print(
            f"[ocr_tagger] Sending {len(gemini_upgrade_queue)} page(s) to Gemini "
            f"for quality upgrade (in batches of {MAX_PAGES_PER_BATCH})."
        )
        chunks = [
            gemini_upgrade_queue[s: s + MAX_PAGES_PER_BATCH]
            for s in range(0, len(gemini_upgrade_queue), MAX_PAGES_PER_BATCH)
        ]
        for chunk_idx, chunk in enumerate(chunks, start=1):
            chunk_indices = [p for p, _ in chunk]
            chunk_images = [img for _, img in chunk]
            try:
                batch_results = _tag_vision_batch_gemini(chunk_images, chunk_indices, known_subjects)
                for r in batch_results:
                    pn = r["page_num"]
                    if len(r.get("text", "")) > len(image_page_results.get(pn, {}).get("text", "")):
                        image_page_results[pn] = r
                        print(f"[ocr_tagger] Page {pn}: Gemini upgrade applied ✓")
                    else:
                        print(f"[ocr_tagger] Page {pn}: Tesseract result kept (Gemini not better).")
            except Exception as gem_err:
                print(f"[ocr_tagger] Gemini batch {chunk_idx} failed ({gem_err}) — keeping Tesseract results.")
                # Per-page fallback
                for page_num, img in chunk:
                    try:
                        r = _tag_vision_page_gemini(img, known_subjects)
                        r["page_num"] = page_num
                        if len(r.get("text", "")) > len(image_page_results.get(page_num, {}).get("text", "")):
                            image_page_results[page_num] = r
                    except Exception as e:
                        print(f"[ocr_tagger] Page {page_num}: Gemini per-page also failed ({e}) — keeping Tesseract.")

    # ── Step 4: Merge results in page order with subject forward-fill ──────────
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

    total_ocr = len(image_page_queue)
    tess_count = total_ocr - len(gemini_upgrade_queue)
    print(
        f"[ocr_tagger] Done: {len(pages)} pages total. "
        f"{len(text_page_results)} text (free), "
        f"{tess_count} Tesseract OCR, "
        f"{len(gemini_upgrade_queue)} Gemini upgrade attempted."
    )
    return results
