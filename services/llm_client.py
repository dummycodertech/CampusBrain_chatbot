"""
Thin wrappers around the two LLM providers this project uses:

- Gemini (vision) for OCR + subject-boundary detection on scanned pages.
  Chosen over Tesseract because it handles messy scans, multi-column
  layouts, and math notation far better out of the box.
  Uses the new google-genai SDK (google.generativeai is deprecated).
- Groq (Llama 3.3 70B) for all text generation: Q&A, summary, quiz,
  topic ranking. Fast and free-tier, and this task (answer from provided
  text) is squarely in its comfort zone.
"""
import os
from google import genai
from groq import Groq

_gemini_client = None
VISION_MODEL = "gemini-3.5-flash"


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini_client


def generate_vision(contents: list, model: str = VISION_MODEL) -> str:
    """Send a multimodal prompt (text + image) to Gemini and return the text response."""
    client = _get_gemini_client()
    response = client.models.generate_content(model=model, contents=contents)
    return response.text


def get_groq_client() -> Groq:
    return Groq(api_key=os.environ["GROQ_API_KEY"])


def generate_text(prompt: str, model: str = "llama-3.3-70b-versatile", temperature: float = 0.2) -> str:
    client = get_groq_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content
