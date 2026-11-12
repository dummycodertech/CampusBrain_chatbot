"""
Gemini Vision OCR fallback and math/circuit detection heuristics for ExamPrep.

Tesseract / PyMuPDF remain the primary, zero-cost extraction path. Gemini Vision
is called ONLY when a page shows signs of unreadable math formulas, circuit/figure
diagrams, broken font glyphs, or un-OCR'd drawing ink.
"""
from __future__ import annotations

import base64
import io
import os
import re
from typing import List, Optional, Tuple

import requests
from PIL import Image, ImageDraw

DEFAULT_VISION_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

MAX_VISION_PAGES_PER_PAPER = 8

_VISION_PROMPT_SCANNED = (
    "You are an expert OCR engine for university exam papers (especially engineering, "
    "mathematics, physics, and electrical/electronics circuits).\n"
    "Transcribe EVERY question and instruction on this exam page accurately in reading order:\n"
    "1. Preserve question numbers (e.g., Q1., (a), (b)) and marks (e.g., [5M], (10 marks)). "
    "Omit noisy decorative stars (****), UNIT headers, and CO1/CO2 outcome tags inside questions.\n"
    "2. Write all mathematical formulas, fractions, integrals, summations, matrices, "
    "subscripts/superscripts, and Greek symbols clearly using properly closed LaTeX ($...$ inline).\n"
    "3. For EVERY circuit diagram, schematic, logic gate diagram, block diagram, phasor, "
    "waveform, K-map, or graph, add a concise SINGLE-LINE description immediately under that "
    "question (with NO numbered bullets inside it) in the exact format:\n"
    "   [Circuit/Diagram: <all nodes/terminals, components with exact values/units, "
    "sources, and how branches/gates are connected>]\n"
    "4. If the page is completely blank with no text or diagrams, reply with exactly: BLANK_PAGE\n"
    "5. Output ONLY the transcribed exam text with no introductory or closing remarks."
)

_VISION_PROMPT_DIGITAL_WITH_DIAGRAM = (
    "You are an expert OCR engine for university exam papers. Some text was already "
    "extracted from this PDF page, but it contains circuit diagrams, figures, or math "
    "formulas that plain PDF text extraction misses or corrupts.\n"
    "Transcribe the FULL page cleanly in reading order:\n"
    "1. Keep all question wording, numbers (Q1., (a), etc.), and marks accurate; omit "
    "decorative asterisks (****), UNIT headers, and CO codes.\n"
    "2. Format all equations/formulas/symbols in cleanly closed LaTeX ($...$).\n"
    "3. Describe every circuit schematic, logic diagram, graph, waveform, or figure as a "
    "single-line summary (no numbered bullets inside) under its question:\n"
    "   [Circuit/Diagram: <all components, values, labels, terminals, and connections>]\n"
    "4. Output ONLY the complete transcribed exam page, with no commentary."
)

_DIAGRAM_KEYWORD_RE = re.compile(
    r"\b(?:"
    r"(?:the\s+|given\s+|following\s+)?circuit\b|circuit\s+shown|shown\s+(?:in\s+)?(?:the\s+)?fig|"
    r"given\s+fig(?:ure)?|fig(?:ure)?\s*(?:below|above|\d)|below\s+fig(?:ure)?|"
    r"following\s+(?:circuit|network|diagram|figure|waveform)|"
    r"network\s+shown|for\s+the\s+network|equivalent\s+(?:circuit|resistance|impedance)|"
    r"block\s+diagram|logic\s+diagram|circuit\s+diagram|"
    r"truth\s+table|k-?map|karnaugh|timing\s+diagram|state\s+diagram|"
    r"phasor\s*(?:diagram)?|waveform|flowchart|graph\s+shown|"
    r"thevenin|norton|mesh\s+analysis|nodal\s+analysis|"
    r"kirchhoff|\bkvl\b|\bkcl\b|\brlc\b|op-?amp|transistor|mosfet|\bbjt\b|"
    r"find\s+(?:v_?th|r_?th|i_?n|r_?n|v_?ab|i_?\d|v_?\d)"
    r")\b",
    re.IGNORECASE,
)

_DIGITAL_GRAPHICS_KEYWORD_RE = re.compile(
    r"\b(?:"
    r"circuit|network|diagram|fig(?:ure)?|waveform|phasor|k-?map|karnaugh|"
    r"truth\s+table|graph|thevenin|norton|mesh|nodal|kvl|kcl|rlc|op-?amp|"
    r"transistor|diode|mosfet|bjt|star|delta|bridge|sin|cos|rms|average"
    r")\b",
    re.IGNORECASE,
)

_MATH_KEYWORD_RE = re.compile(
    r"\b(?:"
    r"evaluate|integrate|integration|integral|differentiate|derivative|"
    r"laplace|fourier|z-?transform|matrix|matrices|determinant|eigen\w*|"
    r"differential\s+equation|\blim\b|taylor|maclaurin|residue|convolu\w*|"
    r"prove\s+that|show\s+that|derive|find\s+the\s+value\s+of"
    r")\b",
    re.IGNORECASE,
)

_STRAY_MATH_ARTIFACT_RE = re.compile(r"[\ufffd\uf000-\uf8ff]")


def get_gemini_keys() -> List[str]:
    """Return configured Gemini API keys from GEMINI_API_KEYS / GEMINI_API_KEY."""
    raw_multi = os.environ.get("GEMINI_API_KEYS", "").strip()
    raw_single = os.environ.get("GEMINI_API_KEY", "").strip()
    combined = ",".join(x for x in (raw_single, raw_multi) if x)
    keys: List[str] = []
    seen = set()
    for part in combined.split(","):
        k = part.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def is_vision_available() -> bool:
    """Return True if at least one Gemini API key is configured in environment."""
    return len(get_gemini_keys()) > 0


def _get_vision_models() -> List[str]:
    env_models = os.environ.get("GEMINI_VISION_MODEL", "").strip()
    if env_models:
        custom = [m.strip() for m in env_models.split(",") if m.strip()]
        if custom:
            return custom
    return list(DEFAULT_VISION_MODELS)


def _count_short_fragment_lines(text: str) -> int:
    """Count short isolated lines typical of OCR slicing a 2D equation vertically."""
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if 1 <= len(s) <= 12 and not re.match(r"^(?:Q\.?\s*\d+|PART\s+[A-Z]|P\.?T\.?O\.?)$", s, re.I):
            if any(ch.isdigit() or ch in "+-*/=<>^()[]{}" for ch in s):
                count += 1
    return count


def _noise_token_ratio(text: str) -> float:
    tokens = text.split()
    if len(tokens) < 10:
        return 0.0
    noisy = 0
    for tok in tokens:
        if len(tok) == 1 and not tok.isalnum() and tok not in ("?", "!"):
            noisy += 1
        elif all(not ch.isalnum() for ch in tok):
            noisy += 1
    return noisy / len(tokens)


def _unboxed_ink_ratio(preprocessed_img: Image.Image, ocr_data: dict) -> float:
    """Estimate fraction of page area occupied by dark ink outside Tesseract word boxes."""
    if not preprocessed_img or not ocr_data:
        return 0.0
    texts = ocr_data.get("text", [])
    confs = ocr_data.get("conf", [])
    lefts = ocr_data.get("left", [])
    tops = ocr_data.get("top", [])
    widths = ocr_data.get("width", [])
    heights = ocr_data.get("height", [])
    if not (texts and lefts and tops and widths and heights):
        return 0.0

    gray = preprocessed_img.convert("L")
    # Ink becomes 255, background becomes 0
    ink_mask = gray.point(lambda p: 255 if p < 180 else 0)
    draw = ImageDraw.Draw(ink_mask)

    n = min(len(texts), len(confs), len(lefts), len(tops), len(widths), len(heights))
    for i in range(n):
        word = str(texts[i]).strip()
        try:
            conf = int(confs[i])
        except (ValueError, TypeError):
            conf = -1
        if not word or conf < 30:
            continue
        try:
            l = int(lefts[i])
            t = int(tops[i])
            w = int(widths[i])
            h = int(heights[i])
        except (ValueError, TypeError):
            continue
        if w <= 0 or h <= 0:
            continue
        draw.rectangle([max(0, l - 4), max(0, t - 4), l + w + 4, t + h + 4], fill=0)

    hist = ink_mask.histogram()
    ink_pixels = hist[255] if len(hist) > 255 else 0
    total_pixels = max(1, ink_mask.width * ink_mask.height)
    ink_ratio = ink_pixels / total_pixels
    if ink_ratio > 0.004:
        return ink_ratio

    # Even thin-line circuit schematics (wires, resistors) occupy concentrated grid cells
    grid = ink_mask.resize((64, 90), getattr(Image, "Resampling", Image).BILINEAR)
    dark_cells = sum(1 for val in grid.getdata() if val >= 16)
    if dark_cells >= 4:
        return 0.02
    return ink_ratio


def _has_visible_ink(img: Optional[Image.Image], min_ink_ratio: float = 0.0005) -> bool:
    """Return True if the page image contains meaningful dark ink (not a blank page)."""
    if img is None:
        return True
    gray = img.convert("L")
    ink_mask = gray.point(lambda p: 255 if p < 200 else 0)
    hist = ink_mask.histogram()
    ink_pixels = hist[255] if len(hist) > 255 else 0
    total_pixels = max(1, ink_mask.width * ink_mask.height)
    return (ink_pixels / total_pixels) >= min_ink_ratio


def needs_vision_for_scanned_page(
    text: str,
    mean_conf: float,
    preprocessed_img: Optional[Image.Image] = None,
    ocr_data: Optional[dict] = None,
) -> Tuple[bool, str]:
    """Decide whether a scanned page needs Gemini Vision fallback after Tesseract."""
    if not text or not text.strip():
        if preprocessed_img is not None and not _has_visible_ink(preprocessed_img):
            return False, "blank_page"
        return True, "empty_ocr"

    if mean_conf < 65.0:
        return True, f"low_conf({mean_conf:.0f})"

    if _STRAY_MATH_ARTIFACT_RE.search(text):
        return True, "broken_math_glyphs"

    if _DIAGRAM_KEYWORD_RE.search(text):
        return True, "diagram_keyword"

    if _noise_token_ratio(text) > 0.18:
        return True, "high_symbol_noise"

    if _MATH_KEYWORD_RE.search(text) and _count_short_fragment_lines(text) >= 3:
        return True, "fragmented_formula"

    if preprocessed_img is not None and ocr_data is not None:
        if _unboxed_ink_ratio(preprocessed_img, ocr_data) > 0.004:
            return True, "unrecognized_diagram_ink"

    return False, ""


def needs_vision_for_digital_page(
    page_text: str,
    has_diagram_image: bool = False,
    drawing_count: int = 0,
) -> Tuple[bool, str]:
    """Decide whether a selectable-text PDF page still needs Gemini Vision for figures/math."""
    if not page_text:
        return False, ""

    if _STRAY_MATH_ARTIFACT_RE.search(page_text):
        return True, "broken_math_glyphs"

    has_graphics = has_diagram_image or drawing_count >= 10
    if has_graphics and _DIGITAL_GRAPHICS_KEYWORD_RE.search(page_text):
        return True, "digital_page_with_diagram"

    if has_diagram_image and _MATH_KEYWORD_RE.search(page_text):
        return True, "digital_image_math"

    if _MATH_KEYWORD_RE.search(page_text) and _count_short_fragment_lines(page_text) >= 4:
        return True, "digital_fragmented_formula"

    return False, ""


def _encode_image_png_b64(img: Image.Image, max_dim: int = 1600) -> str:
    work = img
    if work.mode not in ("RGB", "L"):
        work = work.convert("RGB")
    if max(work.size) > max_dim:
        work = work.copy()
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        work.thumbnail((max_dim, max_dim), resampling)
    buf = io.BytesIO()
    work.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ocr_page_with_gemini(
    image: Image.Image,
    existing_text: str = "",
    timeout: int = 35,
) -> Optional[str]:
    """Transcribe a page image using Gemini Vision. Returns None on unavailability/failure."""
    keys = get_gemini_keys()
    if not keys or image is None:
        return None

    img_b64 = _encode_image_png_b64(image)
    prompt = _VISION_PROMPT_DIGITAL_WITH_DIAGRAM if existing_text.strip() else _VISION_PROMPT_SCANNED
    if existing_text.strip():
        prompt = f"{prompt}\n\nExtracted PDF text for reference:\n{existing_text[:3000]}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": img_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    models = _get_vision_models()
    for api_key in keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                resp = requests.post(
                    url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=timeout,
                )
            except Exception as exc:
                print(f"[vision_ocr] Request error ({model}): {type(exc).__name__}: {exc}")
                continue

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    candidates = data.get("candidates") or []
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text_out = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
                    if text_out and text_out.upper() != "BLANK_PAGE":
                        print(f"[vision_ocr] Gemini Vision succeeded (model={model}, chars={len(text_out)})")
                        return text_out
                    if text_out.upper() == "BLANK_PAGE":
                        return None
                except Exception as exc:
                    print(f"[vision_ocr] Parse error ({model}): {exc}")
                    continue
            else:
                print(f"[vision_ocr] {model} HTTP {resp.status_code}")
                if resp.status_code in (401, 403, 429):
                    # Quota/auth applies to this key; move to next key
                    break

    return None
