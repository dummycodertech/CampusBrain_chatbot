"""
Usage meter component displaying shared Groq API quota and per-session prompts.
"""
from __future__ import annotations

import os
import streamlit as st

from services.llm_client import get_rate_info


def render_usage_meter() -> None:
    """Render shared Groq API quota and per-session prompt limits.

    Displays:
    - In sidebar: Progress bar "X / Y requests left today", caption "Tokens left this minute: N, resets in T",
      labeled "Shared AI quota", and "Your prompts: n / 25".
    - Under chat input: Small caption summarizing remaining quota and session prompts.
    - Shows "Ask a question to see live limits." before the first call.
    """
    try:
        max_prompts = int(os.environ.get("MAX_PROMPTS_PER_SESSION", 25))
        prompts_used = st.session_state.get("prompts_used", 0)
        rate_info = get_rate_info()

        limit_req_str = rate_info.get("x-ratelimit-limit-requests")
        rem_req_str = rate_info.get("x-ratelimit-remaining-requests")
        rem_tokens = rate_info.get("x-ratelimit-remaining-tokens")
        reset_tokens = rate_info.get("x-ratelimit-reset-tokens")

        has_data = limit_req_str is not None and rem_req_str is not None

        # ── 1. Sidebar Display ───────────────────────────────────────────────
        with st.sidebar:
            st.markdown("### ⚡ Shared AI quota")
            st.caption("*(The key is shared by all students)*")
            if has_data:
                try:
                    limit_req = int(limit_req_str)
                    rem_req = int(rem_req_str)
                    ratio = max(0.0, min(1.0, rem_req / limit_req if limit_req > 0 else 0.0))
                    st.progress(ratio, text=f"{rem_req} / {limit_req} requests left today")
                except Exception:
                    st.write(f"{rem_req_str} / {limit_req_str} requests left today")
                st.caption(f"Tokens left this minute: {rem_tokens}, resets in {reset_tokens}")
            else:
                st.info("Ask a question to see live limits.")
            st.caption(f"Your prompts: {prompts_used} / {max_prompts}")

        # ── 2. Small caption under chat input ────────────────────────────────
        if has_data:
            st.caption(
                f"⚡ **Shared AI quota:** {rem_req_str} / {limit_req_str} requests left today · "
                f"Tokens left this minute: {rem_tokens}, resets in {reset_tokens} · "
                f"Your prompts: {prompts_used} / {max_prompts}"
            )
        else:
            st.caption(
                f"⚡ **Shared AI quota:** Ask a question to see live limits. · "
                f"Your prompts: {prompts_used} / {max_prompts}"
            )
    except Exception as e:
        print(f"[usage_meter] Error rendering usage meter: {e}")
