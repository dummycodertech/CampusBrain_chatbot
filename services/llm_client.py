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
_exhausted_keys = set()   # indices of keys that hit daily/permanent limits
# Only gemini-2.5-flash is confirmed working on free tier (campus brain dashboard shows 1/20 RPD)
# gemini-2.0-flash → limit=0 (blocked), gemini-2.0-flash-lite → also blocked, gemini-1.5-flash → 404
VISION_MODEL = "gemini-2.5-flash"
VISION_MODEL_FALLBACK = "gemini-2.5-flash-lite"  # lighter variant, separate quota pool


def _init_gemini_clients():
    global _gemini_clients
    if not _gemini_clients:
        keys_str = os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        _gemini_clients = [genai.Client(api_key=k) for k in keys]
        if not _gemini_clients:
            raise ValueError("No Gemini API keys found in environment.")
        print(f"[llm_client] Loaded {len(_gemini_clients)} Gemini API key(s).")

def get_current_gemini_client() -> genai.Client:
    _init_gemini_clients()
    return _gemini_clients[_current_client_idx]

def rotate_gemini_client():
    global _current_client_idx
    _init_gemini_clients()
    _current_client_idx = (_current_client_idx + 1) % len(_gemini_clients)
    print(f"[llm_client] Switched to Gemini API key #{_current_client_idx + 1} of {len(_gemini_clients)}")

def get_num_keys() -> int:
    _init_gemini_clients()
    return len(_gemini_clients)


def _parse_retry_delay(e: genai_errors.ClientError) -> float:
    """Extract retryDelay seconds from the API error details, default 5s."""
    try:
        details = e.details if hasattr(e, "details") else []
        if isinstance(details, dict):
            details = details.get("error", {}).get("details", [])
        for item in (details or []):
            if isinstance(item, dict) and "retryDelay" in item:
                delay_str = item["retryDelay"]  # e.g. "54s"
                return float(delay_str.rstrip("s"))
    except Exception:
        pass
    return 5.0


def _is_daily_exhausted(e: genai_errors.ClientError) -> bool:
    """Return True if this 429 is a daily quota violation (not just per-minute RPM)."""
    try:
        details = e.details if hasattr(e, "details") else []
        if isinstance(details, dict):
            details = details.get("error", {}).get("details", [])
        for item in (details or []):
            violations = item.get("violations", []) if isinstance(item, dict) else []
            for v in violations:
                if "PerDay" in v.get("quotaId", ""):
                    return True
    except Exception:
        pass
    return False


def generate_vision(contents: list, model: str = VISION_MODEL) -> str:
    """Send a multimodal prompt (text + image) to Gemini and return the text response.

    On 429 RESOURCE_EXHAUSTED:
    - Per-minute limit: waits the retry delay then tries the next key.
    - Daily limit: marks the key as permanently exhausted and skips it.
    Tries every available key, then falls back to gemini-1.5-flash (separate quota).
    """
    global _current_client_idx
    _init_gemini_clients()

    # Try primary model first, then fallback — each has its own separate quota pool
    models_to_try = [model]
    if model != VISION_MODEL_FALLBACK:
        models_to_try.append(VISION_MODEL_FALLBACK)

    last_exception = None

    for current_model in models_to_try:
        if current_model != model:
            print(f"[llm_client] Falling back to {current_model} (separate quota pool)...")
            # Reset exhausted keys for the new model — new quota pool
            _exhausted_keys.clear()

        num_keys = len(_gemini_clients)

        for attempt in range(num_keys):
            idx = (_current_client_idx + attempt) % num_keys
            if idx in _exhausted_keys:
                print(f"[llm_client] Skipping key #{idx + 1} (daily quota exhausted for {current_model}).")
                continue

            client = _gemini_clients[idx]
            try:
                response = client.models.generate_content(model=current_model, contents=contents)
                _current_client_idx = idx
                return response.text

            except genai_errors.APIError as e:
                # Log the real code/status to stdout (visible in Streamlit Cloud logs)
                code = getattr(e, "code", None)
                status = getattr(e, "status", None)
                print(f"[llm_client] Key #{idx + 1} / {current_model} → error code={code} status={status}")

                is_rate_limit = (
                    code == 429
                    or str(code) == "429"
                    or status == "RESOURCE_EXHAUSTED"
                )
                is_server_error = code is not None and int(code) >= 500
                is_not_found = code == 404

                if is_not_found:
                    # This model isn't available — stop trying it entirely
                    print(f"[llm_client] Model {current_model} returned 404 — skipping all keys for this model.")
                    break  # break inner loop, try next model in models_to_try

                if is_rate_limit or is_server_error:
                    last_exception = e
                    daily = _is_daily_exhausted(e)
                    delay = _parse_retry_delay(e)

                    if daily:
                        _exhausted_keys.add(idx)
                        print(
                            f"[llm_client] Key #{idx + 1} daily quota exhausted for {current_model}. "
                            f"({len(_exhausted_keys)}/{num_keys} keys dead)"
                        )
                    else:
                        print(
                            f"[llm_client] Key #{idx + 1} per-minute limit on {current_model}. "
                            f"Waiting {delay:.0f}s..."
                        )
                        time.sleep(min(delay, 10))
                else:
                    # Unexpected error — log and re-raise
                    print(f"[llm_client] Unexpected error (code={code}), re-raising.")
                    raise

            except Exception as e:
                print(f"[llm_client] Non-API exception: {type(e).__name__}: {e}")
                raise


        print(f"[llm_client] All keys exhausted for {current_model}.")

    print("[llm_client] All models and keys exhausted.")
    if last_exception:
        raise last_exception
    raise RuntimeError("Failed to generate vision content: all API keys and models are rate-limited.")


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
