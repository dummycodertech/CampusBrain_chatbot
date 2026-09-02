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

/* hide streamlit chrome */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
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
.stButton > button,
[data-testid="stDownloadButton"] > button {
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    background: rgba(255,255,255,0.06) !important;
    color: #d4d4d8 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important;
    padding: 0.45rem 1.1rem !important;
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
</style>

<!-- Aurora blobs -->
<div class="aurora-left"></div>
<div class="aurora-right"></div>
"""

def inject_stitch_theme():
    """Inject the full Stitch-style CSS and aurora decorations."""
    st.markdown(STITCH_CSS, unsafe_allow_html=True)
