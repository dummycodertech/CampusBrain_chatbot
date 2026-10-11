"""
Usage meter component displaying shared Groq API quota and per-session prompts
as a sleek, floating glassmorphic widget on the web page.
"""
from __future__ import annotations

import html
import os
import streamlit as st

from services.llm_client import get_rate_info


def render_usage_meter() -> None:
    """Render shared Groq API quota and per-session prompt limits in a floating corner widget."""
    try:
        max_prompts = int(os.environ.get("MAX_PROMPTS_PER_SESSION", 25))
        user_prompts = sum(
            1 for m in st.session_state.get("messages", [])
            if isinstance(m, dict) and m.get("role") == "user"
        )
        raw_prompts = st.session_state.get("prompts_used", 0)
        prompts_used = max(user_prompts, raw_prompts)
        st.session_state["prompts_used"] = prompts_used
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

        if has_data:
            pct_req = max(0.0, min(100.0, (rem_req / limit_req * 100.0) if limit_req > 0 else 0.0))
            if pct_req > 50.0:
                fill_cls = "quota-fill ok"
                dot_cls = "quota-dot ok"
            elif pct_req >= 20.0:
                fill_cls = "quota-fill warn"
                dot_cls = "quota-dot warn"
            else:
                fill_cls = "quota-fill low"
                dot_cls = "quota-dot low"

            is_warn = (pct_req < 10.0) or (p_used >= max_p)
            card_warn_cls = " warn-state" if is_warn else ""

            req_line_esc = html.escape(f"{rem_req:,} of {limit_req:,} requests left today")

            tok_val = "—"
            if rem_tokens is not None:
                try:
                    tok_val = f"{int(float(rem_tokens)):,}"
                except Exception:
                    tok_val = html.escape(str(rem_tokens))
            reset_val = html.escape(str(reset_tokens)) if reset_tokens is not None else "soon"
            token_line_esc = html.escape(f"Tokens/min: {tok_val} · Resets: {reset_val}")
            warn_html = '<div class="quota-warn-msg">⚠️ Quota low, answers may be delayed</div>' if is_warn else ""
            badge_text = html.escape(f"{rem_req:,} req · {p_used}/{max_p}")

            floater_html = (
                f'<div class="quota-floater-root">'
                f'<details class="quota-floater-details">'
                f'<summary class="quota-floater-btn">'
                f'<span class="{dot_cls}"></span>'
                f'<span class="quota-btn-title">⚡ Quota</span>'
                f'<span class="quota-pill-badge">{badge_text}</span>'
                f'<span class="quota-arrow">▾</span>'
                f'</summary>'
                f'<div class="quota-floater-card{card_warn_cls}">'
                f'<div class="quota-card-header">'
                f'<div class="quota-card-header-title"><span>⚡ AI Quota & Limits</span></div>'
                f'<span class="quota-badge-pill">Shared Pool</span>'
                f'</div>'
                f'<div class="quota-metric-block">'
                f'<div class="quota-metric-header"><span>Daily API Requests</span><span class="quota-metric-val">{pct_req:.0f}% left</span></div>'
                f'<div class="quota-track" style="height:7px;"><div class="{fill_cls}" style="width:{pct_req:.1f}%;"></div></div>'
                f'<div class="quota-sub">{req_line_esc}</div>'
                f'</div>'
                f'<div class="quota-metric-block">'
                f'<div class="quota-metric-header"><span>Your Prompts</span><span class="quota-metric-val">{p_used} / {max_p}</span></div>'
                f'<div class="quota-track" style="height:6px;"><div class="quota-fill session" style="width:{session_fill:.1f}%;"></div></div>'
                f'<div class="quota-sub" style="font-size:0.68rem; color:#71717a;">Per-session student limit</div>'
                f'</div>'
                f'<div style="font-size:0.68rem;color:#71717a;margin-top:0.4rem;padding-top:0.35rem;border-top:1px solid rgba(255,255,255,0.06);">{token_line_esc}</div>'
                f'{warn_html}'
                f'<div class="quota-footer"><span>Auto-refreshes on query</span><span>Click or hover</span></div>'
                f'</div>'
                f'</details>'
                f'</div>'
            )
        else:
            floater_html = (
                f'<div class="quota-floater-root">'
                f'<details class="quota-floater-details">'
                f'<summary class="quota-floater-btn">'
                f'<span class="quota-dot idle"></span>'
                f'<span class="quota-btn-title">⚡ Quota</span>'
                f'<span class="quota-pill-badge">{p_used}/{max_p} prompts</span>'
                f'<span class="quota-arrow">▾</span>'
                f'</summary>'
                f'<div class="quota-floater-card">'
                f'<div class="quota-card-header">'
                f'<div class="quota-card-header-title"><span>⚡ AI Quota & Limits</span></div>'
                f'<span class="quota-badge-pill">Groq Cloud</span>'
                f'</div>'
                f'<div class="quota-metric-block">'
                f'<div class="quota-metric-header"><span>Daily API Requests</span><span class="quota-metric-val">Live Limits</span></div>'
                f'<div class="quota-track" style="height:7px;"><div class="quota-fill empty" style="width:0%;"></div></div>'
                f'<div class="quota-sub">Ask a question to see live limits</div>'
                f'</div>'
                f'<div class="quota-metric-block">'
                f'<div class="quota-metric-header"><span>Your Prompts</span><span class="quota-metric-val">{p_used} / {max_p}</span></div>'
                f'<div class="quota-track" style="height:6px;"><div class="quota-fill session" style="width:{session_fill:.1f}%;"></div></div>'
                f'<div class="quota-sub" style="font-size:0.68rem; color:#71717a;">Per-session student limit</div>'
                f'</div>'
                f'<div class="quota-footer"><span>Auto-refreshes on query</span><span>Click or hover</span></div>'
                f'</div>'
                f'</details>'
                f'</div>'
            )

        st.markdown(floater_html, unsafe_allow_html=True)

    except Exception as e:
        print(f"[usage_meter] Error rendering usage meter: {e}")
