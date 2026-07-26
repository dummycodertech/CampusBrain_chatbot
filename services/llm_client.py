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
import time
from google import genai
from google.genai import errors as genai_errors
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

def generate_vision(contents: list, model: str = VISION_MODEL) -> str:
    """Send a multimodal prompt (text + image) to Gemini and return the text response.
    
    Automatically rotates through all configured API keys on 429 RESOURCE_EXHAUSTED.
    Catches google.genai.errors.ClientError by type (not by message string) so this
    works even when Streamlit Cloud redacts the error message.
    """
    num_keys = get_num_keys()
    last_exception = None

    for attempt in range(num_keys):
        client = get_current_gemini_client()
        try:
            response = client.models.generate_content(model=model, contents=contents)
            return response.text
        except genai_errors.ClientError as e:
            # Use e.code (not e.status_code) — that's the correct attribute in google-genai SDK
            # Also check e.status as a secondary fallback
            is_rate_limit = (e.code == 429 or e.status == "RESOURCE_EXHAUSTED")
            if is_rate_limit:
                print(
                    f"[llm_client] Rate limit hit on key #{_current_client_idx + 1}. "
                    f"Rotating to next key (attempt {attempt + 1}/{num_keys})..."
                )
                rotate_gemini_client()
                last_exception = e
                time.sleep(2)  # brief pause before retrying with new key
            else:
                raise
        except Exception as e:
            # Non-ClientError (network, etc.) — re-raise immediately
            raise

    print("[llm_client] All Gemini keys exhausted or rate limited.")
    if last_exception:
        raise last_exception
    raise RuntimeError("Failed to generate vision content: all API keys are rate-limited.")


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
