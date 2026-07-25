"""
Entrypoint. Reads paperId/pdfUrl/subject/year straight from the URL query
params -- set by the website via iframe or hyperlink, see README for the
contract. This means the app has zero runtime dependency on the website's
backend: it only needs a fetchable PDF URL and metadata from the query string.

Ingests the paper on first view if not already cached, then shows the
Summarize/Quiz buttons plus a free-text chat box.
"""
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from components.theme import inject_stitch_theme
from ingestion.cache_writer import ingest_paper
from retrieval.paper_lookup import get_paper_text
from components.action_buttons import render_action_buttons
from components.chat_box import render_chat_box

st.set_page_config(
    page_title="Campus Brain",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)

inject_stitch_theme()

# ─── URL param mode ───────────────────────────────────────────
params = st.query_params
paper_id   = params.get("paperId")
pdf_url    = params.get("pdfUrl")
subject    = params.get("subject", "Unknown")
year       = params.get("year", "Unknown")
branch     = params.get("branch", "")
semester   = params.get("semester", "")

is_local_upload = False

if not paper_id or not pdf_url:
    # ─── Landing hero ─────────────────────────────────────────
    st.markdown(
        """
        <div style="text-align:center; padding: 4rem 0 0; position: relative; z-index: 1;">
            <div class="hero-label">
                🧠 &nbsp; Campus Brain &nbsp; ✦
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="hero-title">Study smarter,<br>not harder.</div>
        <div class="hero-sub">
            Drop any exam paper and get instant summaries,<br>
            practice quizzes, and answers on demand.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ─── Frosted glass upload panel ───────────────────────────
    st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "",
        type=["pdf"],
        label_visibility="collapsed",
    )
    st.markdown(
        """
        <div class="chip-row">
            <span class="chip">📝 Summarize</span>
            <span class="chip">🧠 Quiz</span>
            <span class="chip">💬 Ask Anything</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if not uploaded_file:
        st.stop()

    import hashlib
    file_bytes = uploaded_file.getvalue()
    paper_id       = hashlib.md5(file_bytes).hexdigest()
    subject        = uploaded_file.name
    year           = "Uploaded"
    is_local_upload = True

# ─── Session reset on new paper ───────────────────────────────
if "messages" not in st.session_state or st.session_state.get("current_paper_id") != paper_id:
    st.session_state.messages = []
    st.session_state.current_paper_id = paper_id

# ─── Paper header ─────────────────────────────────────────────
badge = "✦ UPLOADED" if is_local_upload else f"✦ {year}"
title = subject if is_local_upload else f"{subject} — {year}"

st.markdown(
    f"""
    <div style="padding: 3rem 0 0.5rem; text-align: center; position: relative; z-index: 1;">
        <div class="paper-badge">
            <div class="live-dot"></div>
            {badge}
        </div>
    </div>
    <div class="hero-title" style="font-size: 2.2rem; letter-spacing: -1px; margin-bottom: 1.5rem;">
        {title}
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── Ingest paper ─────────────────────────────────────────────
with st.spinner("Scanning document..."):
    if is_local_upload:
        from storage.cache_store import CacheStore
        store = CacheStore()
        if not store.is_cached(paper_id):
            import tempfile, os
            from pathlib import Path
            from ingestion.cache_writer import ingest_local_paper
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)
            try:
                ingest_local_paper(paper_id, tmp_path, year=year, known_subjects=[subject])
            finally:
                os.remove(tmp_path)
    else:
        ingest_paper(paper_id=paper_id, pdf_url=pdf_url, year=year, branch=branch, semester=semester)

    paper_text = get_paper_text(paper_id)

if not paper_text:
    st.error("Could not extract text from this paper.")
    st.stop()

# ─── Actions + Chat ───────────────────────────────────────────
render_action_buttons(paper_text)
render_chat_box(paper_text)
