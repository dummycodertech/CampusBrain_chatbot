"""
Thin wrappers around the Groq LLM provider used by Campus Brain.

All text generation (Q&A, summaries, quizzes,
topic ranking, flashcards) goes through Groq only.

Provider:
  Text → Groq openai/gpt-oss-120b (fast inference, free tier)
         with fallback chain → gpt-oss-20b → configurable via GROQ_MODEL_CHAIN
"""
from __future__ import annotations
import functools
import os
import threading
from typing import Optional
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

# Module flag: remember if API rejected reasoning_effort
_reasoning_effort_rejected: bool = False
_last_finish_reason: Optional[str] = None

_TRACKED_HEADERS = [
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
]


def _update_rate_info(model_or_headers, headers=None) -> None:
    """Save Groq rate limit headers into module state thread-safely, keyed by model."""
    global _printed_headers
    if headers is None:
        raw_headers = model_or_headers
        active = _get_active_model_chain()
        model = active[0] if active else _DEFAULT_MODEL_CHAIN[0]
    else:
        model = str(model_or_headers)
        raw_headers = headers

    if not raw_headers:
        return
    headers_dict = {str(k).lower(): str(v) for k, v in raw_headers.items()}

    if not _printed_headers:
        ratelimit_keys = [k for k in headers_dict.keys() if "ratelimit" in k]
        print(f"[llm_client] Groq rate limit headers received: {ratelimit_keys}")
        _printed_headers = True

    with _rate_info_lock:
        if model not in _rate_info:
            _rate_info[model] = {}
        for key in _TRACKED_HEADERS:
            if key in headers_dict:
                _rate_info[model][key] = headers_dict[key]


_last_probe_time: float = 0.0


def fetch_live_rate_info(force: bool = False) -> dict:
    """Fetch live Groq rate limit headers dynamically using a fast probe call.

    Throttled to avoid unnecessary API calls if probed within the last 30 seconds.
    """
    global _last_probe_time
    import time
    now = time.time()
    if not force and (now - _last_probe_time < 30.0):
        with _rate_info_lock:
            for m, data in _rate_info.items():
                if data and data.get("x-ratelimit-remaining-requests") is not None:
                    return dict(data)
            return {}

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return {}

    try:
        active = _get_active_model_chain()
        target_model = active[0] if active else _DEFAULT_MODEL_CHAIN[0]
        client = get_groq_client()
        raw_resp = client.chat.completions.with_raw_response.create(
            model=target_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        _last_probe_time = now
        _update_rate_info(target_model, raw_resp.headers)
        with _rate_info_lock:
            return dict(_rate_info.get(target_model, {}))
    except Exception as e:
        print(f"[llm_client] fetch_live_rate_info: {e}")
        with _rate_info_lock:
            for m, data in _rate_info.items():
                if data and data.get("x-ratelimit-remaining-requests") is not None:
                    return dict(data)
            return {}


def get_rate_info(model: str | None = None) -> dict:
    """Return a snapshot of the latest Groq rate limit headers for a model.

    If no rate info is cached, dynamically probes Groq for live quota.
    """
    with _rate_info_lock:
        if model and model in _rate_info and _rate_info[model]:
            return dict(_rate_info[model])
        for m, data in _rate_info.items():
            if data and data.get("x-ratelimit-remaining-requests") is not None:
                return dict(data)

    return fetch_live_rate_info()


def quota_ok(model: str | None = None, min_requests: int = 5, min_tokens: int = 2000) -> bool:
    """Check if remaining Groq quota for a model meets the required minimums.

    Uses get_rate_info(model).
    Returns True when there is no data yet or headers are missing or unparseable.
    Returns False if remaining requests < min_requests or remaining tokens < min_tokens.
    """
    info = get_rate_info(model)
    if not info:
        return True

    rem_req_val = info.get("x-ratelimit-remaining-requests")
    rem_tokens_val = info.get("x-ratelimit-remaining-tokens")

    if rem_req_val is not None:
        try:
            if int(rem_req_val) < min_requests:
                return False
        except (ValueError, TypeError):
            pass

    if rem_tokens_val is not None:
        try:
            if int(rem_tokens_val) < min_tokens:
                return False
        except (ValueError, TypeError):
            pass

    return True


def get_last_finish_reason() -> Optional[str]:
    """Return the finish_reason of the most recent LLM completion call."""
    return _last_finish_reason


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


def _chat_once(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    reasoning_effort: str | None = "low",
) -> tuple[str, str | None]:
    """Execute a single chat completion attempt across the fallback chain.

    Returns (content, finish_reason).
    Captures rate-limit headers per model, logs successful calls with completion_tokens,
    and handles reasoning_effort rejection gracefully.
    """
    global _reasoning_effort_rejected, _last_finish_reason

    active_chain = _get_active_model_chain()
    if model:
        model_chain = [model] + [m for m in active_chain if m != model]
    else:
        model_chain = list(active_chain)

    client = get_groq_client()
    for attempt_model in model_chain:
        call_kwargs: dict = {
            "model": attempt_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        send_reasoning = (
            attempt_model.startswith("openai/gpt-oss")
            and not _reasoning_effort_rejected
            and reasoning_effort is not None
        )
        if send_reasoning:
            call_kwargs["reasoning_effort"] = reasoning_effort

        try:
            try:
                raw_response = client.chat.completions.with_raw_response.create(**call_kwargs)
            except Exception as e:
                # If API rejected reasoning_effort, retry once without it and remember flag
                if send_reasoning:
                    err_msg = str(e).lower()
                    status = getattr(e, "status_code", None)
                    if status is None:
                        resp = getattr(e, "response", None)
                        if resp is not None:
                            status = getattr(resp, "status_code", None)
                    if status == 400 or "reasoning_effort" in err_msg or "parameter" in err_msg or "argument" in err_msg or "extra" in err_msg:
                        _reasoning_effort_rejected = True
                        call_kwargs.pop("reasoning_effort", None)
                        raw_response = client.chat.completions.with_raw_response.create(**call_kwargs)
                    else:
                        raise
                else:
                    raise

            _update_rate_info(attempt_model, raw_response.headers)
            response = raw_response.parse()
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
            completion_tokens = getattr(getattr(response, "usage", None), "completion_tokens", None)
            print(f"[generate_text] model={attempt_model} finish={finish_reason} completion_tokens={completion_tokens}")

            if content:
                if model and attempt_model != model:
                    print(f"[generate_text] Used fallback model {attempt_model} (primary returned empty)")
                _last_finish_reason = finish_reason
                return content, finish_reason

            print(
                f"[generate_text] {attempt_model} returned empty content, "
                f"finish_reason={finish_reason} — trying next model"
            )
        except Exception as e:
            resp = getattr(e, "response", None)
            if resp is not None and hasattr(resp, "headers"):
                _update_rate_info(attempt_model, resp.headers)
            print(f"[generate_text] {attempt_model} raised {type(e).__name__}: {e} — trying next model")

    raise LLMUnavailableError(
        "All Groq models in the chain failed or returned empty content. "
        f"Chain tried: {model_chain}"
    )


def generate_text(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    reasoning_effort: str | None = "low",
) -> str:
    """Send a text prompt to Groq and return the completion string.

    Tries the requested model first (if specified), then every model in the active
    chain returned by _get_active_model_chain(). If every attempt fails or returns
    empty content, raises LLMUnavailableError so callers can show a friendly
    message instead of a blank UI.
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

    content, _ = _chat_once(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )
    return content


def generate_text_complete(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    max_continuations: int = 2,
    reasoning_effort: str | None = "low",
) -> str:
    """Generate text and continue automatically if truncated by finish_reason == 'length'.

    Does not increment prompts_used on continuations.
    Returns the accumulated text as a string.
    """
    global _last_finish_reason

    # Per-session prompt limit guard (counted ONCE per user action)
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

    content, finish_reason = _chat_once(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )
    full_content = content
    generate_text_complete.last_finish_reason = finish_reason

    continuations = 0
    while finish_reason == "length" and continuations < max_continuations:
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": full_content},
            {"role": "user", "content": "Continue exactly where you stopped. Do not repeat anything and do not add an introduction."},
        ]
        try:
            next_content, next_finish = _chat_once(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            )
        except Exception as e:
            print(f"[generate_text_complete] Continuation failed ({type(e).__name__}: {e}), returning partial content")
            break

        if not next_content or not next_content.strip():
            break

        full_content += next_content
        finish_reason = next_finish
        generate_text_complete.last_finish_reason = finish_reason
        continuations += 1

    _last_finish_reason = finish_reason
    return full_content


generate_text_complete.last_finish_reason = None
