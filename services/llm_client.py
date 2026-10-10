"""
Thin wrappers around the Groq LLM provider used by Campus Brain.

All text generation (Q&A, summaries, quizzes,
topic ranking, flashcards) goes through Groq only.

Provider:
  Text → Groq openai/gpt-oss-120b (fast inference, free tier)
         with fallback chain → gpt-oss-20b → configurable via GROQ_MODEL_CHAIN
"""
import functools
import os
import threading
from groq import Groq


class LLMUnavailableError(Exception):
    """Raised when every model in the Groq fallback chain fails or returns
    empty content.  Callers should catch this and show a friendly UI message
    rather than displaying a blank response.
    """


# Default Groq model chain (primary → fallbacks). Override via env:
#   GROQ_MODEL_CHAIN=openai/gpt-oss-120b,openai/gpt-oss-20b
_DEFAULT_MODEL_CHAIN = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# ── Groq rate limit tracking ──────────────────────────────────────────────────
_rate_info_lock = threading.Lock()
_rate_info: dict = {}
_printed_headers: bool = False

_TRACKED_HEADERS = [
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
]


def _update_rate_info(headers) -> None:
    """Save Groq rate limit headers into module state thread-safely."""
    global _printed_headers
    if not headers:
        return
    headers_dict = {str(k).lower(): str(v) for k, v in headers.items()}

    if not _printed_headers:
        ratelimit_keys = [k for k in headers_dict.keys() if "ratelimit" in k]
        print(f"[llm_client] Groq rate limit headers received: {ratelimit_keys}")
        _printed_headers = True

    with _rate_info_lock:
        for key in _TRACKED_HEADERS:
            if key in headers_dict:
                _rate_info[key] = headers_dict[key]


def get_rate_info() -> dict:
    """Return a snapshot of the latest Groq rate limit headers."""
    with _rate_info_lock:
        return dict(_rate_info)


@functools.lru_cache(maxsize=1)
def _get_active_model_chain() -> list:
    """Return the validated list of Groq model IDs to try in order.

    1. Reads GROQ_MODEL_CHAIN from env (comma-separated) or falls back to
       _DEFAULT_MODEL_CHAIN.
    2. Calls client.models.list() once (cached) to prune IDs that don't exist
       on this Groq account.  If the list call fails for any reason the
       configured chain is kept as-is so behaviour degrades gracefully.
    3. Logs which models are active so it's visible in Streamlit Cloud logs.
    """
    env_chain = os.environ.get("GROQ_MODEL_CHAIN", "").strip()
    if env_chain:
        configured = [m.strip() for m in env_chain.split(",") if m.strip()]
    else:
        configured = list(_DEFAULT_MODEL_CHAIN)

    try:
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        available_ids = {m.id for m in client.models.list().data}
        active = [m for m in configured if m in available_ids]
        pruned = [m for m in configured if m not in available_ids]
        if pruned:
            print(f"[llm_client] Models not found on this Groq account (pruned): {pruned}")
        if not active:
            print("[llm_client] WARNING: no configured models were found via models.list(); "
                  "keeping full chain as fallback.")
            active = configured
    except Exception as e:
        print(f"[llm_client] Could not validate model list ({type(e).__name__}: {e}); "
              f"keeping configured chain.")
        active = configured

    print(f"[llm_client] Active Groq model chain: {active}")
    return active


def get_groq_client() -> Groq:
    """Instantiate a fresh Groq client using GROQ_API_KEY from the environment."""
    return Groq(api_key=os.environ["GROQ_API_KEY"])


def generate_text(
    prompt: str,
    model: str = "openai/gpt-oss-120b",
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Send a text prompt to Groq and return the completion string.

    Tries the requested model first, then every model in the active chain
    returned by _get_active_model_chain().  If every attempt fails or returns
    empty content, raises LLMUnavailableError so callers can show a friendly
    message instead of a blank UI.

    Captures Groq rate-limit headers via `with_raw_response` and enforces per-session
    prompt limits from MAX_PROMPTS_PER_SESSION.
    """
    # ── Per-session prompt limit guard ────────────────────────────────────────
    try:
        from streamlit.runtime import exists as _st_runtime_exists
        if _st_runtime_exists():
            import streamlit as st
            if "prompts_used" not in st.session_state:
                st.session_state.prompts_used = 0
            max_prompts = int(os.environ.get("MAX_PROMPTS_PER_SESSION", 25))
            if st.session_state.prompts_used >= max_prompts:
                msg = f"You have reached your session limit of {max_prompts} prompts. Please refresh the page to start a new session."
                st.warning(f"⚠️ {msg}")
                return msg
            st.session_state.prompts_used += 1
    except Exception:
        pass

    # Build chain: requested model first, then the rest of the active chain.
    active_chain = _get_active_model_chain()
    model_chain = [model] + [m for m in active_chain if m != model]

    client = get_groq_client()
    for attempt_model in model_chain:
        try:
            raw_response = client.chat.completions.with_raw_response.create(
                model=attempt_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            # Capture rate-limit headers
            _update_rate_info(raw_response.headers)
            response = raw_response.parse()
            content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            if content:
                if attempt_model != model:
                    print(f"[generate_text] Used fallback model {attempt_model} (primary returned empty)")
                return content
            # content is None or empty — try next
            print(
                f"[generate_text] {attempt_model} returned empty content, "
                f"finish_reason={finish_reason} — trying next model"
            )
        except Exception as e:
            resp = getattr(e, "response", None)
            if resp is not None and hasattr(resp, "headers"):
                _update_rate_info(resp.headers)
            print(f"[generate_text] {attempt_model} raised {type(e).__name__}: {e} — trying next model")

    raise LLMUnavailableError(
        "All Groq models in the chain failed or returned empty content. "
        f"Chain tried: {model_chain}"
    )
