"""
Usage meter component displaying shared Groq API quota and per-session prompts.
"""
from __future__ import annotations

import html
import os
import streamlit as st

from services.llm_client import get_rate_info


def render_usage_meter() -> None:
    """Render shared Groq API quota and per-session prompt limits in a compact card."""
    try:
        max_prompts = int(os.environ.get("MAX_PROMPTS_PER_SESSION", 25))
        prompts_used = st.session_state.get("prompts_used", 0)
        rate_info = get_rate_info()

        limit_req_str = rate_info.get("x-ratelimit-limit-requests")
        rem_req_str = rate_info.get("x-ratelimit-remaining-requests")
        rem_tokens = rate_info.get("x-ratelimit-remaining-tokens")
        reset_tokens = rate_info.get("x-ratelimit-reset-tokens")

        has_data = False
        limit_req = 0
        rem_req = 0
        try:
            if limit_req_str is not None and rem_req_str is not None:
                limit_req = int(float(limit_req_str))
                rem_req = int(float(rem_req_str))
                has_data = (limit_req > 0)
        except Exception:
            has_data = False

        try:
            max_p = int(float(max_prompts))
            p_used = int(float(prompts_used))
        except Exception:
            max_p = 25
            p_used = 0

        session_fill = max(0.0, min(100.0, (p_used / max_p * 100.0) if max_p > 0 else 0.0))
        session_label_esc = html.escape(f"Your prompts {p_used} / {max_p}")

        if has_data:
            pct_req = max(0.0, min(100.0, (rem_req / limit_req * 100.0) if limit_req > 0 else 0.0))
            if pct_req > 50.0:
                fill_cls = "quota-fill ok"
            elif pct_req >= 20.0:
                fill_cls = "quota-fill warn"
            else:
                fill_cls = "quota-fill low"

            is_warn = (pct_req < 10.0) or (p_used >= max_p)
            card_cls = "quota-card warn-state" if is_warn else "quota-card"

            req_line_esc = html.escape(f"{rem_req:,} of {limit_req:,} requests left today")

            tok_val = "—"
            if rem_tokens is not None:
                try:
                    tok_val = f"{int(float(rem_tokens)):,}"
                except Exception:
                    tok_val = html.escape(str(rem_tokens))
            reset_val = html.escape(str(reset_tokens)) if reset_tokens is not None else "soon"
            token_line_esc = f"tokens this minute: {tok_val} · resets {reset_val}"
            warn_html = '<div class="quota-warn-msg">⚠️ Quota low, answers may be delayed</div>' if is_warn else ""

            card_html = (
                f'<div class="{card_cls}">'
                f'<div class="quota-head"><span>⚡ AI QUOTA</span><span>shared by all users</span></div>'
                f'<div class="quota-track" style="height:8px;"><div class="{fill_cls}" style="width:{pct_req:.1f}%;"></div></div>'
                f'<div class="quota-sub">{req_line_esc}</div>'
                f'<div style="font-size:0.72rem;color:#d4d4d8;margin-bottom:0.25rem;">{session_label_esc}</div>'
                f'<div class="quota-track" style="height:5px;"><div class="quota-fill session" style="width:{session_fill:.1f}%;"></div></div>'
                f'<div style="font-size:0.68rem;color:#71717a;margin-top:0.25rem;">{token_line_esc}</div>'
                f'{warn_html}'
                f'</div>'
            )
        else:
            card_html = (
                f'<div class="quota-card">'
                f'<div class="quota-head"><span>⚡ AI QUOTA</span><span>shared by all users</span></div>'
                f'<div class="quota-track" style="height:8px;"><div class="quota-fill empty" style="width:0%;"></div></div>'
                f'<div class="quota-sub">Ask a question to see live limits</div>'
                f'<div style="font-size:0.72rem;color:#d4d4d8;margin-bottom:0.25rem;">{session_label_esc}</div>'
                f'<div class="quota-track" style="height:5px;"><div class="quota-fill session" style="width:{session_fill:.1f}%;"></div></div>'
                f'</div>'
            )

        with st.sidebar:
            st.markdown(card_html, unsafe_allow_html=True)

        if has_data:
            st.caption(f"⚡ {rem_req:,} requests left · prompts {p_used}/{max_p}")
        else:
            st.caption("⚡ AI quota: ask a question to see live limits")

    except Exception as e:
        print(f"[usage_meter] Error rendering usage meter: {e}")
