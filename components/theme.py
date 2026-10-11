"""
Stitch-style premium dark UI for Campus Brain — full CSS recreation.

Design notes
------------
- Background: three overlapping radial-gradient dot grids at 24 / 72 / 160 px
  spacing create depth without any image asset.  The offset background-position
  stagger prevents the dots from aligning into a single grid plane.
- Aurora blobs: two fixed radial-gradient ellipses (purple/indigo) are blurred
  with filter:blur(90px) and animated with a slow scale+translate keyframe.
  Using two blobs at alternate-reverse timing produces natural-looking movement
  without a JavaScript animation loop.
- Chat messages use a fadeUp keyframe (translateY 8px -> 0) timed at 0.3s to
  make each new response feel responsive and alive.
- All selectors target Streamlit's internal data-testid attributes because
  Streamlit's class names are unstable across versions (they're generated).
- Fonts: Inter from Google Fonts — loaded via @import in the injected <style>
  block.  No separate <link> tag needed.
"""
import streamlit as st

STITCH_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

/* ─── Reset & base ───────────────────────────────────────── */
* { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #root, [data-testid="stApp"],
[data-testid="stAppViewContainer"] {
    font-family: 'Inter', sans-serif !important;
    background: #090909 !important;
    color: #f5f5f5 !important;
}

/* hide streamlit chrome & sidebar drawer */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
section[data-testid="stSidebar"],
footer,
#MainMenu { display: none !important; }

/* ─── Aurora + dot-grid background (varied sizes) ───────── */
[data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed;
    inset: 0;
    /* Layer 1: tiny dense dots  Layer 2: medium dots  Layer 3: large sparse dots */
    background-image:
        radial-gradient(circle, rgba(255,255,255,0.18) 1px,  transparent 1px),
        radial-gradient(circle, rgba(255,255,255,0.08) 2px,  transparent 2px),
        radial-gradient(circle, rgba(255,255,255,0.04) 3.5px, transparent 3.5px);
    background-size:
        24px 24px,
        72px 72px,
        160px 160px;
    background-position:
        0 0,
        12px 12px,
        40px 40px;
    pointer-events: none;
    z-index: 0;
}

/* Aurora blobs */
.aurora-left {
    position: fixed;
    left: -180px;
    bottom: -80px;
    width: 680px;
    height: 520px;
    border-radius: 50%;
    background: radial-gradient(ellipse at center,
        #7c3aed 0%,
        #4f46e5 30%,
        #1e40af 60%,
        transparent 80%);
    filter: blur(90px);
    opacity: 0.55;
    pointer-events: none;
    z-index: 0;
    animation: aurora-drift 10s ease-in-out infinite alternate;
}
.aurora-right {
    position: fixed;
    right: -180px;
    bottom: -80px;
    width: 620px;
    height: 480px;
    border-radius: 50%;
    background: radial-gradient(ellipse at center,
        #6d28d9 0%,
        #2563eb 40%,
        #1e40af 65%,
        transparent 80%);
    filter: blur(90px);
    opacity: 0.45;
    pointer-events: none;
    z-index: 0;
    animation: aurora-drift 12s ease-in-out infinite alternate-reverse;
}
@keyframes aurora-drift {
    from { transform: scale(1) translate(0, 0); }
    to   { transform: scale(1.12) translate(20px, -20px); }
}

/* ─── Main content centering ─────────────────────────────── */
[data-testid="stMainBlockContainer"],
[data-testid="block-container"] {
    max-width: 860px !important;
    padding: 0 2rem !important;
    position: relative;
    z-index: 1;
}

/* ─── Hide all st decoration except what we want ─────────── */
[data-testid="stVerticalBlock"] > div:empty { display: none; }

/* ─── Typography hero ────────────────────────────────────── */
.hero-label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #a1a1aa;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.08);
    padding: 0.3rem 0.9rem;
    border-radius: 99px;
    margin-bottom: 2rem;
}

.hero-title {
    font-size: clamp(2.8rem, 7vw, 5.5rem);
    font-weight: 700;
    line-height: 1.08;
    letter-spacing: -2px;
    color: #ffffff;
    text-align: center;
    margin-bottom: 1.2rem;
}

.hero-sub {
    font-size: 1.15rem;
    font-weight: 400;
    color: #a1a1aa;
    text-align: center;
    margin-bottom: 2.8rem;
    line-height: 1.6;
}

/* ─── Frosted glass panel (wraps upload + chat) ──────────── */
.glass-panel {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    padding: 1.5rem 1.5rem 1rem;
    margin-bottom: 1.2rem;
    position: relative;
    z-index: 2;
}

/* ─── File uploader restyle ──────────────────────────────── */
[data-testid="stFileUploader"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
}

[data-testid="stFileUploaderDropzone"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px dashed rgba(255,255,255,0.15) !important;
    border-radius: 14px !important;
    color: #a1a1aa !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
    padding: 1.5rem !important;
    transition: all 0.25s ease;
}

[data-testid="stFileUploaderDropzone"]:hover {
    border-color: rgba(124, 58, 237, 0.5) !important;
    background: rgba(124, 58, 237, 0.04) !important;
}

[data-testid="stFileUploader"] label {
    color: #a1a1aa !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.92rem !important;
}

[data-testid="stFileUploader"] button {
    background: rgba(124, 58, 237, 0.2) !important;
    color: #c4b5fd !important;
    border: 1px solid rgba(124, 58, 237, 0.35) !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}

[data-testid="stFileUploader"] button:hover {
    background: rgba(124, 58, 237, 0.35) !important;
}

/* ─── Chat input restyle ─────────────────────────────────── */
[data-testid="stChatInput"] {
    border-radius: 14px !important;
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    backdrop-filter: blur(12px) !important;
}

[data-testid="stChatInput"] textarea {
    background: transparent !important;
    border: none !important;
    color: #f5f5f5 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 1rem !important;
    caret-color: #a78bfa;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: #52525b !important;
}

[data-testid="stChatInput"] button {
    background: #7c3aed !important;
    border: none !important;
    border-radius: 10px !important;
    color: white !important;
    transition: all 0.2s ease !important;
}

[data-testid="stChatInput"] button:hover {
    background: #6d28d9 !important;
    box-shadow: 0 0 20px rgba(124, 58, 237, 0.5) !important;
}

/* ─── Action chips row ───────────────────────────────────── */
.chip-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.8rem;
    flex-wrap: wrap;
}

.chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.82rem;
    font-weight: 500;
    font-family: 'Inter', sans-serif;
    color: #d4d4d8;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 0.35rem 0.75rem;
    cursor: pointer;
    transition: all 0.2s ease;
    white-space: nowrap;
}

.chip:hover {
    background: rgba(124, 58, 237, 0.15);
    border-color: rgba(124, 58, 237, 0.4);
    color: #c4b5fd;
}

.chip-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.5;
}

/* ─── Buttons + Download Button ──────────────────── */
[data-testid="stHorizontalBlock"] {
    gap: 0.6rem !important;
}

.stButton > button,
[data-testid="stDownloadButton"] > button {
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    background: rgba(255,255,255,0.06) !important;
    color: #d4d4d8 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important;
    padding: 0.4rem 0.6rem !important;
    min-height: 3rem !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    text-align: center !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.1px;
    width: 100%;
}

.stButton > button:hover,
[data-testid="stDownloadButton"] > button:hover {
    background: rgba(124, 58, 237, 0.15) !important;
    border-color: rgba(124, 58, 237, 0.4) !important;
    color: #c4b5fd !important;
    transform: none !important;
}

.stButton > button:disabled {
    opacity: 0.4 !important;
    cursor: not-allowed !important;
}

/* ─── Quota Floater Button & Dropdown ─────────────────────── */
.quota-floater-root {
    position: fixed;
    top: 1.15rem;
    right: 1.5rem;
    z-index: 99999;
    user-select: none;
    font-family: 'Inter', sans-serif !important;
}

.quota-floater-details {
    position: relative;
}

.quota-floater-details summary {
    list-style: none;
    outline: none;
}

.quota-floater-details summary::-webkit-details-marker {
    display: none;
}

.quota-floater-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.42rem 0.85rem;
    background: rgba(18, 18, 24, 0.82);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 999px;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    cursor: pointer;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4), 0 0 12px rgba(124, 58, 237, 0.12);
    transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
    color: #f4f4f5;
    font-size: 0.78rem;
    font-weight: 500;
}

.quota-floater-btn:hover,
.quota-floater-details[open] .quota-floater-btn {
    background: rgba(28, 28, 38, 0.95);
    border-color: rgba(167, 139, 250, 0.45);
    box-shadow: 0 6px 22px rgba(0, 0, 0, 0.5), 0 0 18px rgba(124, 58, 237, 0.28);
    color: #ffffff;
    transform: translateY(-1px);
}

.quota-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}

.quota-dot.ok {
    background: #10b981;
    box-shadow: 0 0 8px rgba(16, 185, 129, 0.7);
    animation: quota-pulse-green 2.5s infinite;
}

.quota-dot.warn {
    background: #f59e0b;
    box-shadow: 0 0 8px rgba(245, 158, 11, 0.7);
    animation: quota-pulse-warn 2s infinite;
}

.quota-dot.low {
    background: #ef4444;
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.7);
    animation: quota-pulse-low 1.5s infinite;
}

.quota-dot.idle {
    background: #a78bfa;
    box-shadow: 0 0 6px rgba(167, 139, 250, 0.6);
}

@keyframes quota-pulse-green {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.9); }
}

@keyframes quota-pulse-warn {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.45; transform: scale(0.85); }
}

@keyframes quota-pulse-low {
    0%, 100% { opacity: 1; transform: scale(1.05); }
    50% { opacity: 0.4; transform: scale(0.85); }
}

.quota-btn-title {
    font-weight: 600;
    letter-spacing: 0.3px;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    color: #f4f4f5;
}

.quota-pill-badge {
    font-size: 0.72rem;
    color: #a1a1aa;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 999px;
    padding: 0.15rem 0.5rem;
    font-weight: 400;
    letter-spacing: 0.2px;
}

.quota-arrow {
    font-size: 0.65rem;
    color: #a1a1aa;
    transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    margin-left: 0.1rem;
}

.quota-floater-details[open] .quota-arrow {
    transform: rotate(180deg);
}

.quota-floater-card {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    width: 320px;
    background: rgba(16, 16, 22, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 16px;
    padding: 1.1rem 1.15rem 1rem;
    box-shadow: 0 20px 48px -8px rgba(0, 0, 0, 0.8), 0 0 28px rgba(124, 58, 237, 0.15);
    backdrop-filter: blur(28px);
    -webkit-backdrop-filter: blur(28px);
    opacity: 0;
    visibility: hidden;
    transform: translateY(-8px);
    transition: opacity 0.22s cubic-bezier(0.16, 1, 0.3, 1), transform 0.22s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.22s;
    pointer-events: none;
    z-index: 100000;
}

/* Invisible bridge so mouse hover doesn't break between button and card */
.quota-floater-card::before {
    content: '';
    position: absolute;
    top: -12px;
    left: 0;
    right: 0;
    height: 12px;
}

.quota-floater-card.warn-state {
    border-color: #ef4444 !important;
    box-shadow: 0 20px 48px -8px rgba(0, 0, 0, 0.8), 0 0 24px rgba(239, 68, 68, 0.25) !important;
}

.quota-floater-details[open] .quota-floater-card {
    opacity: 1;
    visibility: visible;
    transform: translateY(0);
    pointer-events: auto;
}

@media (hover: hover) {
    .quota-floater-root:hover .quota-floater-card {
        opacity: 1;
        visibility: visible;
        transform: translateY(0);
        pointer-events: auto;
    }
    .quota-floater-root:hover .quota-arrow {
        transform: rotate(180deg);
    }
}

.quota-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.85rem;
    padding-bottom: 0.55rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}

.quota-card-header-title {
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #f4f4f5;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

.quota-badge-pill {
    font-size: 0.65rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #c4b5fd;
    background: rgba(124, 58, 237, 0.16);
    border: 1px solid rgba(124, 58, 237, 0.3);
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
}

.quota-metric-block {
    margin-bottom: 0.75rem;
}

.quota-metric-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.74rem;
    color: #e4e4e7;
    margin-bottom: 0.35rem;
    font-weight: 500;
}

.quota-metric-val {
    font-size: 0.72rem;
    color: #a1a1aa;
    font-weight: 400;
}

.quota-track {
    width: 100%;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 99px;
    overflow: hidden;
    position: relative;
}

.quota-fill {
    height: 100%;
    border-radius: 99px;
    transition: width 0.4s ease;
}

.quota-fill.ok {
    background: #10b981;
    box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
}

.quota-fill.warn {
    background: #f59e0b;
    box-shadow: 0 0 8px rgba(245, 158, 11, 0.4);
}

.quota-fill.low {
    background: #ef4444;
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.4);
}

.quota-fill.session {
    background: linear-gradient(90deg, #7c3aed, #a78bfa);
}

.quota-fill.empty {
    background: rgba(255, 255, 255, 0.15);
}

.quota-sub {
    font-size: 0.7rem;
    color: #a1a1aa;
    margin-top: 0.3rem;
    white-space: nowrap;
}

.quota-warn-msg {
    font-size: 0.7rem;
    color: #f87171;
    margin-top: 0.45rem;
    font-weight: 500;
}

.quota-footer {
    margin-top: 0.65rem;
    padding-top: 0.5rem;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    font-size: 0.66rem;
    color: #71717a;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

@media (max-width: 640px) {
    .quota-floater-root {
        top: 0.75rem !important;
        right: 0.75rem !important;
    }
    .quota-floater-btn {
        padding: 0.35rem 0.65rem !important;
        font-size: 0.74rem !important;
    }
    .quota-pill-badge {
        display: none !important;
    }
    .quota-floater-card {
        width: min(300px, calc(100vw - 1.5rem)) !important;
        right: 0 !important;
    }
}

/* ─── Chat messages ──────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 16px !important;
    padding: 1.1rem 1.3rem !important;
    margin-bottom: 0.7rem !important;
    animation: fadeUp 0.3s ease;
}

@keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: rgba(124, 58, 237, 0.07) !important;
    border-color: rgba(124, 58, 237, 0.15) !important;
}

/* ─── Expander ───────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 12px !important;
    margin-bottom: 0.5rem !important;
}

[data-testid="stExpander"] summary {
    color: #e4e4e7 !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
}

/* ─── Alerts ─────────────────────────────────────────────── */
[data-testid="stAlert"] {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 12px !important;
    color: #d4d4d8 !important;
}

/* ─── Spinner ────────────────────────────────────────────── */
.stSpinner > div > span {
    color: #a78bfa !important;
}

/* ─── Markdown text ──────────────────────────────────────── */
.stMarkdown p, .stMarkdown li {
    color: #d4d4d8 !important;
    line-height: 1.75;
    font-size: 0.95rem;
}

.stMarkdown strong { color: #c4b5fd !important; }

/* ─── Divider ────────────────────────────────────────────── */
hr {
    border: none !important;
    height: 1px !important;
    background: rgba(255,255,255,0.07) !important;
}

/* ─── Paper metadata badge ───────────────────────────────── */
.paper-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 0.8px;
    color: #a78bfa;
    background: rgba(124, 58, 237, 0.1);
    border: 1px solid rgba(124, 58, 237, 0.2);
    padding: 0.3rem 0.9rem;
    border-radius: 99px;
    margin-bottom: 0.6rem;
}

.live-dot {
    width: 5px; height: 5px;
    border-radius: 50%;
    background: #a78bfa;
    animation: pulse-live 2s infinite;
}
@keyframes pulse-live {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.3; }
}

/* ─── Scope pill for off-topic questions ─────────────────── */
.scope-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    font-weight: 500;
    color: #93c5fd;
    background: rgba(59, 130, 246, 0.12);
    border: 1px solid rgba(59, 130, 246, 0.25);
    border-radius: 99px;
    padding: 0.35rem 0.9rem;
    margin-bottom: 0.8rem;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    line-height: 1.4;
}
</style>

<!-- Aurora blobs -->
<div class="aurora-left"></div>
<div class="aurora-right"></div>
"""

def inject_stitch_theme():
    """Inject the full Stitch-style CSS and aurora decorations."""
    st.markdown(STITCH_CSS, unsafe_allow_html=True)
