"""
Tests for smart Gemini Vision OCR fallback criteria, graceful degradation,
key rotation, and formula/circuit question retention.
"""
from unittest.mock import MagicMock, patch

from PIL import Image, ImageDraw

from generation.question_prep import prepare_questions
from ingestion.ocr_tagger import tag_and_extract_all
from ingestion.vision_ocr import (
    get_gemini_keys,
    needs_vision_for_digital_page,
    needs_vision_for_scanned_page,
    ocr_page_with_gemini,
)


def test_scanned_fallback_skips_clean_text_page():
    clean_text = (
        "B.Tech Semester 3 Examination\n"
        "Q1. Explain deadlock prevention and avoidance algorithms in operating systems. [10M]\n"
        "Q2. Differentiate between paging and segmentation with suitable examples. [10M]"
    )
    img = Image.new("L", (400, 400), color=255)
    need, reason = needs_vision_for_scanned_page(clean_text, mean_conf=88.0, preprocessed_img=img, ocr_data=None)
    assert need is False
    assert reason == ""


def test_scanned_fallback_triggers_on_circuit_keyword_even_with_high_chars_and_conf():
    text = (
        "END TERM EXAMINATION ELECTRICAL SCIENCE\n"
        "Q1. Find the current through the 10 ohm resistor in the circuit shown below using "
        "Thevenin theorem and calculate maximum power transferred to the load. [10M]"
    )
    need, reason = needs_vision_for_scanned_page(text, mean_conf=86.0)
    assert need is True
    assert reason == "diagram_keyword"


def test_scanned_fallback_triggers_on_unboxed_diagram_ink():
    """Even without diagram keywords, dark drawing ink outside Tesseract word boxes triggers Vision."""
    img = Image.new("L", (400, 400), color=255)
    d = ImageDraw.Draw(img)
    # Word box text at top: (20, 20, 120, 20)
    d.rectangle([20, 20, 140, 40], fill=0)
    # Large un-OCR'd circuit schematic block below: > 1.5% of 400*400 = 2400 pixels
    d.rectangle([50, 120, 260, 260], fill=0)

    ocr_data = {
        "text": ["Question1"],
        "conf": [90],
        "left": [20],
        "top": [20],
        "width": [120],
        "height": [20],
    }
    need, reason = needs_vision_for_scanned_page(
        "Q1. Solve the following problem carefully for full marks.",
        mean_conf=90.0,
        preprocessed_img=img,
        ocr_data=ocr_data,
    )
    assert need is True
    assert reason == "unrecognized_diagram_ink"


def test_digital_page_fallback_triggers_only_when_graphics_or_broken_math_present():
    plain_text = "Q1. Define polymorphism and inheritance in C++. [5M]"
    need_plain, _ = needs_vision_for_digital_page(plain_text, has_diagram_image=False, drawing_count=2)
    assert need_plain is False

    circuit_text = "Q1. Calculate Vth across terminals A-B in the circuit shown below. [10M]"
    need_circuit, reason = needs_vision_for_digital_page(circuit_text, has_diagram_image=False, drawing_count=35)
    assert need_circuit is True
    assert reason == "digital_page_with_diagram"

    pua_text = "Q1. Solve \uf0f2 x^2 dx."
    need_pua, reason_pua = needs_vision_for_digital_page(pua_text, has_diagram_image=False, drawing_count=0)
    assert need_pua is True
    assert reason_pua == "broken_math_glyphs"


def test_tag_and_extract_all_uses_gemini_on_circuit_and_falls_back_gracefully():
    img1 = Image.new("L", (200, 200), color=255)
    img2 = Image.new("L", (200, 200), color=255)
    pages = [
        (1, "", img1),  # scanned circuit page
        (2, "Q2. Find I in the circuit shown below. [5M]", img2),  # flagged digital page
    ]

    with patch("ingestion.ocr_tagger._tesseract_available", return_value=True), \
         patch("ingestion.ocr_tagger.ocr_page", return_value=("Q1. Find Rth in the circuit shown below. [10M]", 82.0)), \
         patch("ingestion.ocr_tagger.is_vision_available", return_value=True), \
         patch(
             "ingestion.ocr_tagger.ocr_page_with_gemini",
             side_effect=[
                 "Q1. Find $R_{th}$ in the circuit shown below.\n[Circuit: 12V source, R1=4 ohm, R2=8 ohm]",
                 None,  # simulate failure on page 2 -> must keep original PDF text!
             ],
         ):
        results, warnings = tag_and_extract_all(pages, known_subjects=[])

    assert len(results) == 2
    assert "[Circuit: 12V source" in results[0]["text"]
    assert results[1]["text"] == "Q2. Find I in the circuit shown below. [5M]"


def test_gemini_multi_key_failover(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key_one, key_two")
    assert get_gemini_keys() == ["key_one", "key_two"]

    resp_429 = MagicMock(status_code=429)
    resp_200 = MagicMock(status_code=200)
    resp_200.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Q1. Evaluate $\\int x dx$"}]}}]
    }

    img = Image.new("RGB", (100, 100), color="white")
    with patch("ingestion.vision_ocr.requests.post", side_effect=[resp_429, resp_200]) as mock_post:
        out = ocr_page_with_gemini(img)

    assert out == "Q1. Evaluate $\\int x dx$"
    # First attempt used key_one, 429 broke out to key_two
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[0].kwargs["headers"]["x-goog-api-key"] == "key_one"
    assert mock_post.call_args_list[1].kwargs["headers"]["x-goog-api-key"] == "key_two"


def test_question_prep_retains_math_and_circuit_questions():
    text = (
        "Q1. Evaluate $\\int_0^2 (3x^2 + 2x + 1) dx$ for x = 0 to 2. [5M]\n"
        "Q2. Find Vth and Rth for R1 = 10 ohm, R2 = 20 ohm, V = 12V. [10M]"
    )
    qs = prepare_questions(text)
    assert len(qs) == 2
    assert "+" in qs[0]["text"]
    assert "=" in qs[1]["text"]
