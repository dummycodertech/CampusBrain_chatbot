"""
OCR and subject-tagging pipeline for Campus Brain.

OCR Strategy
------------
1. PyMuPDF text extraction (free, instant) — for text-based pages
   (handled upstream in pdf_to_images.iter_pages; we receive the text directly).
2. Tesseract OCR (free, local, no quota) — for scanned/image pages.
   - Pages are preprocessed (grayscale → autocontrast → median filter → threshold)
     before being passed to Tesseract.
   - Multi-PSM retry: tries PSM 6 first; if confidence < 70 retries PSM 4 then
     PSM 3, keeping the result with the highest mean confidence.
   - Line breaks are preserved by grouping words on (block_num, par_num, line_num),
     joining words with spaces and lines with "\\n". This is critical for the
     downstream question splitter in topic_heatmap.py.

Subject detection
-----------------
Regex + string matching against a configurable subject list; no LLM call needed.
Subject is forward-filled across pages (a new header re-tags subsequent pages).

Memory safety
-------------
tag_and_extract_all() processes pages from an iterator one at a time and
explicitly del-s each PIL Image before requesting the next, so peak memory
stays constant regardless of document length.
"""
from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageFilter, ImageOps

from ingestion.vision_ocr import (
    MAX_VISION_PAGES_PER_PAPER,
    is_vision_available,
    needs_vision_for_scanned_page,
    ocr_page_with_gemini,
)


# ── Tesseract probe ───────────────────────────────────────────────────────────

def _tesseract_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# ── Image preprocessing ───────────────────────────────────────────────────────

def preprocess(img: Image.Image, threshold: int = 160) -> Image.Image:
    """Prepare a page image for Tesseract OCR. Tunable threshold (default 160).

    Pipeline:
    1. Grayscale — colour carries no information for text OCR.
    2. Autocontrast — stretch the pixel histogram to fill [0, 255].
    3. Median filter (3×3) — suppress salt-and-pepper noise without blurring edges.
    4. Threshold (tunable) — binarise: dark text stays dark, background becomes white.

    Returns an "L"-mode (grayscale) image.
    """
    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = img.point(lambda x: 255 if x > threshold else 0)
    return img


# ── Line reconstruction ────────────────────────────────────────────────────────

def _reconstruct_lines(data: dict) -> str:
    """Rebuild text from pytesseract.image_to_data output, preserving layout.

    Groups words by (block_num, par_num, line_num) in reading order:
    - Words on the same line are joined with spaces.
    - Lines in the same paragraph are joined with newlines ("\\n").
    - Paragraphs are separated with blank lines ("\\n\\n").
    Words with confidence == -1 (non-text regions) or empty words are skipped.
    """
    paragraphs: OrderedDict[tuple, OrderedDict[int, list[str]]] = OrderedDict()

    n = len(data.get("text", []))
    for i in range(n):
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError, KeyError):
            continue
        word = str(data["text"][i]).strip()
        if conf == -1 or not word:
            continue
        block = int(data["block_num"][i])
        par = int(data["par_num"][i])
        line = int(data["line_num"][i])
        par_key = (block, par)
        if par_key not in paragraphs:
            paragraphs[par_key] = OrderedDict()
        if line not in paragraphs[par_key]:
            paragraphs[par_key][line] = []
        paragraphs[par_key][line].append(word)

    par_texts = []
    for lines in paragraphs.values():
        par_text = "\n".join(" ".join(words) for words in lines.values() if words)
        if par_text:
            par_texts.append(par_text)

    return "\n\n".join(par_texts)


def _compute_page_conf(data: dict) -> Tuple[float, int]:
    """Compute page average word confidence from conf field (ignoring conf == -1).

    Returns:
        (avg_conf, confident_word_count)
    """
    valid_confs = []
    n = len(data.get("text", []))
    for i in range(n):
        try:
            c = int(data["conf"][i])
        except (ValueError, TypeError, KeyError):
            continue
        word = str(data["text"][i]).strip()
        if c != -1 and word:
            valid_confs.append(c)

    if not valid_confs:
        return 0.0, 0
    return sum(valid_confs) / len(valid_confs), len(valid_confs)


# ── OCR with PSM retry ────────────────────────────────────────────────────────

def ocr_page(img: Image.Image) -> Tuple[str, float]:
    """OCR a preprocessed page image with multi-PSM retry and quality check.

    Strategy:
    - Run pytesseract with --psm 6 (uniform block of text).
    - If output has <30 chars or avg confidence <40, retry with --psm 4
      (single column of variable text sizes), then --psm 3 (fully automatic).
    - Return the result with the highest avg confidence.
    - Empty/garbled check: if confident word count < 10 or avg confidence < 35,
      return empty text so garbage is not cached.
    """
    import pytesseract

    attempts = []
    for psm in [6, 4, 3]:
        config = f"--oem 3 --psm {psm}"
        data = pytesseract.image_to_data(
            img, config=config, output_type=pytesseract.Output.DICT
        )
        avg_conf, word_count = _compute_page_conf(data)
        text = _reconstruct_lines(data)
        attempts.append({
            "psm": psm,
            "text": text,
            "avg_conf": avg_conf,
            "word_count": word_count,
            "data": data,
        })
        # If output meets quality threshold, accept immediately
        if len(text.strip()) >= 30 and avg_conf >= 40:
            break

    # Pick the attempt with the highest average confidence
    best = max(attempts, key=lambda a: a["avg_conf"])
    ocr_page.last_data = best.get("data")
    best_text = best["text"]
    best_conf = best["avg_conf"]
    best_words = best["word_count"]

    # Empty/garbled check: if confident word count < 10 or avg confidence < 35,
    # return empty text so garbage is not cached.
    if best_words < 10 or best_conf < 35:
        return "", max(best_conf, 0.0)

    return best_text, max(best_conf, 0.0)


ocr_page.last_data = None


# ── Subject detection (regex, no LLM) ─────────────────────────────────────────

_HEADER_PATTERNS = [
    re.compile(r"(?i)^(UNIT[\s\-]+\d|MODULE[\s\-]+\d|PART[\s\-]+[A-Z\d])", re.MULTILINE),
    re.compile(r"(?i)(B\.?Tech|M\.?Tech|B\.?E|B\.?Sc).*(semester|sem)", re.MULTILINE),
    re.compile(r"(?i)(examination|exam|paper|subject)\s*[-:]\s*\S"),
]


def _detect_subject_from_text(text: str, known_subjects: List[str]) -> Optional[str]:
    """Return the matching known subject name if one appears in the page text."""
    candidates = [
        s.strip() for s in known_subjects
        if s and len(s.strip()) > 3 and s.strip().lower() != "unknown"
    ]
    # Prefer longest subject names first to avoid short-prefix collisions
    candidates.sort(key=len, reverse=True)

    header_lower = text[:1200].lower()
    for subj in candidates:
        if subj.lower() in header_lower:
            return subj

    text_lower = text.lower()
    for subj in candidates:
        if subj.lower() in text_lower:
            return subj

    m = re.search(
        r"(?im)^\s*(?:subject|course)\s*(?:name|title)?\s*[:\-]\s*([A-Za-z][A-Za-z0-9 &,/\-]{3,60})\s*$",
        text[:1000],
    )
    if m:
        extracted = " ".join(m.group(1).split()).strip(" .,-:")
        if len(extracted) > 3 and extracted.lower() != "unknown":
            return extracted

    return None


# ── Text-page handler (free, no OCR) ──────────────────────────────────────────

def tag_text_page(text: str, known_subjects: List[str], page_num: int) -> dict:
    """Process a text-extracted page without any OCR call."""
    subject = _detect_subject_from_text(text, known_subjects)
    return {
        "has_new_subject_header": subject is not None,
        "subject": subject,
        "text": text,
    }


# ── Poor-quality thresholds ───────────────────────────────────────────────────

# If OCR yields fewer than this many characters, the page is considered poorly scanned.
POOR_CHARS_THRESHOLD = 50

# If mean OCR confidence is below this, emit a warning (even if chars are OK).
POOR_CONF_THRESHOLD = 60


# ── Main entry point ───────────────────────────────────────────────────────────

def tag_and_extract_all(
    pages: Iterable[Tuple[int, str, Optional[Image.Image]]],
    known_subjects: List[str],
) -> Tuple[List[Dict], List[str]]:
    """Process all pages from a lazy iterator, one at a time.

    Args:
        pages: Iterator of ``(page_num, text, image_or_None)`` from
               ``pdf_to_images.iter_pages()``.  When image is not None the
               caller (here) owns it and must ``del`` it after use.
        known_subjects: List of expected subject names for this PYQ bundle.

    Returns:
        (results, warnings) where:
        - results: list of dicts with keys ``page_num``, ``subject``,
          ``text``, ``ocr_conf`` (float or None).
        - warnings: list of human-readable strings describing poor pages.
          Entries prefixed ``TESSERACT_MISSING:`` indicate the binary is absent.

    Subject is forward-filled: once a page header sets the subject, all
    subsequent pages inherit it until the next header.
    """
    use_tesseract = _tesseract_available()
    vision_available = is_vision_available()
    max_vision_pages = int(
        os.environ.get("MAX_VISION_PAGES_PER_PAPER", str(MAX_VISION_PAGES_PER_PAPER)).strip()
        or MAX_VISION_PAGES_PER_PAPER
    )
    vision_calls_used = 0

    if use_tesseract:
        print("[ocr_tagger] Tesseract available — using as primary OCR engine.")
    elif vision_available:
        print("[ocr_tagger] Tesseract not found — using Gemini Vision OCR for scanned pages.")
    else:
        print("[ocr_tagger] WARNING: Tesseract not found. Scanned pages will be empty.")

    results: List[Dict] = []
    warnings: List[str] = []
    current_subject: Optional[str] = None
    scanned_page_count = 0
    tesseract_missing_warned = False

    for page_num, text, image in pages:
        if image is None:
            # ── Pure text-based page: subject detection only, no OCR ─────────
            parsed = tag_text_page(text, known_subjects, page_num)
            ocr_conf = None
            print(f"[ocr_tagger] Page {page_num}: text extraction ({len(text)} chars)")
        elif text and text.strip():
            # ── Digital-text page flagged for diagrams/circuits/broken math ──
            chosen_text = text
            if vision_available and vision_calls_used < max_vision_pages:
                vision_text = ocr_page_with_gemini(image, existing_text=text)
                if vision_text:
                    vision_calls_used += 1
                    chosen_text = vision_text
                    print(f"[ocr_tagger] Page {page_num}: Gemini Vision enhanced digital page ({len(chosen_text)} chars)")
            del image
            parsed = tag_text_page(chosen_text, known_subjects, page_num)
            ocr_conf = None
        else:
            # ── Scanned page: preprocess → Tesseract → smart Gemini fallback ─
            scanned_page_count += 1

            if not use_tesseract:
                vision_text = None
                if vision_available and vision_calls_used < max_vision_pages:
                    vision_text = ocr_page_with_gemini(image)
                    if vision_text:
                        vision_calls_used += 1
                del image  # free memory even on the error path

                if vision_text:
                    ocr_conf = 95.0
                    parsed = tag_text_page(vision_text, known_subjects, page_num)
                    parsed["ocr_conf"] = ocr_conf
                else:
                    if not tesseract_missing_warned:
                        warnings.append(
                            "TESSERACT_MISSING: Tesseract OCR binary is not installed. "
                            "Scanned pages cannot be read. Digital-text PDFs still work normally."
                        )
                        tesseract_missing_warned = True
                    parsed = {"has_new_subject_header": False, "subject": None, "text": ""}
                    ocr_conf = None
            else:
                try:
                    preprocessed = preprocess(image)
                    ocr_page.last_data = None
                    raw_text, mean_conf = ocr_page(preprocessed)
                    ocr_data = getattr(ocr_page, "last_data", None)

                    used_vision = False
                    if vision_available and vision_calls_used < max_vision_pages:
                        need_vision, reason = needs_vision_for_scanned_page(
                            raw_text,
                            mean_conf,
                            preprocessed_img=preprocessed,
                            ocr_data=ocr_data,
                        )
                        if need_vision:
                            vision_text = ocr_page_with_gemini(image)
                            if vision_text:
                                vision_calls_used += 1
                                raw_text = vision_text
                                mean_conf = max(mean_conf, 95.0)
                                used_vision = True
                                print(
                                    f"[ocr_tagger] Page {page_num}: Gemini Vision fallback "
                                    f"({reason}) -> {len(raw_text)} chars"
                                )

                    del preprocessed
                    del image

                    ocr_conf = round(mean_conf, 2)
                    char_count = len(raw_text.strip())

                    print(
                        f"[ocr_tagger] Page {page_num}: "
                        f"{char_count} chars, conf={mean_conf:.0f}"
                        f"{' [vision]' if used_vision else ''}"
                    )

                    if not raw_text or not raw_text.strip():
                        warnings.append(f"Page {page_num} could not be read clearly by OCR")
                        parsed = {"has_new_subject_header": False, "subject": None, "text": ""}
                        parsed["ocr_conf"] = ocr_conf
                    else:
                        if mean_conf < POOR_CONF_THRESHOLD and not used_vision:
                            warnings.append(
                                f"Page {page_num}: low OCR confidence "
                                f"({mean_conf:.0f} % — some text may be inaccurate)"
                            )
                        parsed = tag_text_page(raw_text, known_subjects, page_num)
                        parsed["ocr_conf"] = ocr_conf

                except Exception as tess_err:
                    try:
                        del image
                    except Exception:
                        pass
                    print(f"[ocr_tagger] Page {page_num}: Tesseract error — {tess_err}")
                    warnings.append(
                        f"Page {page_num}: OCR failed ({type(tess_err).__name__})"
                    )
                    parsed = {"has_new_subject_header": False, "subject": None, "text": ""}
                    ocr_conf = None

        # ── Subject forward-fill ─────────────────────────────────────────────
        if parsed.get("has_new_subject_header") and parsed.get("subject"):
            current_subject = parsed["subject"]

        results.append({
            "page_num": page_num,
            "subject": current_subject or "Unknown",
            "text": parsed.get("text", ""),
            "ocr_conf": parsed.get("ocr_conf", ocr_conf),
        })

    text_count = len(results) - scanned_page_count
    print(
        f"[ocr_tagger] Done: {len(results)} pages total — "
        f"{text_count} text (free), {scanned_page_count} Tesseract OCR."
    )
    return results, warnings
