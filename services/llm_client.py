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

_gemini_clients = []
_current_client_idx = 0
VISION_MODEL = "gemini-2.0-flash"


def _init_gemini_clients():
    global _gemini_clients
    if not _gemini_clients:
        keys_str = os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        _gemini_clients = [genai.Client(api_key=k) for k in keys]
        if not _gemini_clients:
            raise ValueError("No Gemini API keys found in environment.")

def get_current_gemini_client() -> genai.Client:
    _init_gemini_clients()
    return _gemini_clients[_current_client_idx]

def rotate_gemini_client():
    global _current_client_idx
    _init_gemini_clients()
    _current_client_idx = (_current_client_idx + 1) % len(_gemini_clients)
    print(f"[llm_client] Exhausted current key. Switched to Gemini API key #{_current_client_idx + 1} of {len(_gemini_clients)}")

def get_num_keys() -> int:
    _init_gemini_clients()
    return len(_gemini_clients)

import time

def generate_vision(contents: list, model: str = VISION_MODEL) -> str:
    """Send a multimodal prompt (text + image) to Gemini and return the text response."""
    num_keys = get_num_keys()
    attempts = 0
    last_exception = None
    
    while attempts < num_keys:
        client = get_current_gemini_client()
        try:
            response = client.models.generate_content(model=model, contents=contents)
            return response.text
        except Exception as e:
            error_msg = str(e).lower()
            if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                print(f"[llm_client] Rate limit hit on current key. Rotating...")
                rotate_gemini_client()
                attempts += 1
                last_exception = e
                time.sleep(1)
            else:
                raise
                
    print("[llm_client] All Gemini keys exhausted or rate limited.")
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError("Failed to generate vision content due to rate limits.")


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
