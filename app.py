"""
Entrypoint for Campus Brain — the AI-powered PYQ study assistant.

Design principles
-----------------
- URL-param first: the website passes paperId, pdfUrl, subject, year, branch,
  semester directly in the query string.  This app never calls the website's
  backend at runtime; all it needs is a publicly reachable PDF.
- Local-upload fallback: when no query params are present the landing hero is
  shown and the student can drag-drop any PDF directly into the app.
- Ingestion is idempotent: calling ingest_paper() on an already-cached paper
  is a no-op (SQLite cache check inside CacheStore), so page refreshes are
  instant after the first load.
- Session isolation: st.session_state.messages is flushed whenever the active
  paper changes so chat history never leaks between papers.
"""
from dotenv import load_dotenv
load_dotenv()  # works locally
import html
import os
import shutil
import streamlit as st

# On Streamlit Cloud, secrets live in st.secrets (not os.environ).
# Copy them into os.environ so every module that uses os.environ.get() works
# identically in both local and cloud environments.
# Handles both flat secrets and nested [section] tables.
def _copy_secrets_to_env():
    """Recursively copy st.secrets into os.environ.

    Supports:
    - Flat string secrets:  GROQ_API_KEY = "gsk_..."
    - Nested sections:      [groq]\n  api_key = "gsk_..."
    """
    import streamlit as _st

    def _flatten(mapping, prefix=""):
        for k, v in mapping.items():
            full_key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
            if isinstance(v, str):
                os.environ[full_key.upper()] = v
            elif hasattr(v, "items"):  # nested section / AttrDict
                _flatten(v, prefix=full_key.upper())

    try:
        _flatten(_st.secrets)
    except Exception as _se:
        print(f"[app] Warning: could not copy st.secrets to env: {_se}")

_copy_secrets_to_env()

# Startup logging (visible in server / Streamlit Cloud logs, never in UI, never print key values).
_tesseract_found = bool(shutil.which("tesseract"))
if not _tesseract_found:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        _tesseract_found = True
    except Exception:
        pass

_groq_key_set = bool(os.environ.get("GROQ_API_KEY", "").strip())
_env_chain = os.environ.get("GROQ_MODEL_CHAIN", "").strip()
_model_chain = [m.strip() for m in _env_chain.split(",") if m.strip()] if _env_chain else ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
_tavily_present = bool(os.environ.get("TAVILY_API_KEY", "").strip())
_tagging_model = os.environ.get("TAGGING_MODEL", "").strip() or "openai/gpt-oss-20b"

print(f"[app] Tesseract binary: {'found' if _tesseract_found else 'not found'}")
print(f"[app] Active Groq model chain: {', '.join(_model_chain)}")
print(f"[app] GROQ_API_KEY set: {'yes' if _groq_key_set else 'no'}")
print(f"[app] Tavily web search: {'on' if _tavily_present else 'off'}")
print(f"[app] Tagging model: {_tagging_model}")
print("[app] Storage: local SQLite (cleared on redeploy/restart)")

from components.theme import inject_stitch_theme
from ingestion.cache_writer import ingest_paper
from ingestion.subject_reference import get_branches_and_semesters, get_expected_subjects
from retrieval.paper_lookup import get_paper_text
from components.action_buttons import render_action_buttons
from components.chat_box import render_chat_box
from components.usage_meter import render_usage_meter

st.set_page_config(
    page_title="Campus Brain",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="auto",
)

if not _groq_key_set:
    st.error("GROQ_API_KEY is missing. Please add GROQ_API_KEY to your Streamlit secrets (.streamlit/secrets.toml) or environment variables.")
    st.stop()

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
is_other = False
typed_subject = ""

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

    if not branch or not semester:
        branches, semesters = get_branches_and_semesters()
        branch_options = branches + ["Other / not listed"]
        semester_options = semesters + ["Other / not listed"]

        col1, col2 = st.columns(2)
        with col1:
            b_idx = branch_options.index(branch) if branch in branch_options else 0
            selected_branch = st.selectbox(
                "Branch",
                options=branch_options,
                index=b_idx,
                key="upload_branch",
            )
        with col2:
            if selected_branch == "Other / not listed":
                selected_semester = "Other / not listed"
                st.selectbox(
                    "Semester",
                    options=["Other / not listed"],
                    disabled=True,
                    key="upload_semester",
                )
            else:
                s_idx = semester_options.index(semester) if semester in semester_options else 0
                selected_semester = st.selectbox(
                    "Semester",
                    options=semester_options,
                    index=s_idx,
                    key="upload_semester",
                )

        if selected_branch == "Other / not listed" or selected_semester == "Other / not listed":
            is_other = True
            typed_subject = st.text_input(
                "Subject name",
                placeholder="Enter subject name",
                key="upload_typed_subject",
            )
        else:
            branch = selected_branch
            semester = selected_semester

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

    if is_other and not typed_subject.strip():
        st.warning("Please enter the subject name above.")
        st.stop()

    import hashlib
    file_bytes = uploaded_file.getvalue()
    paper_id       = hashlib.md5(file_bytes).hexdigest()
    subject        = typed_subject.strip() if is_other else uploaded_file.name
    year           = "Uploaded"
    is_local_upload = True

    if not is_other:
        from storage.cache_store import CacheStore
        store = CacheStore()
        if store.is_cached(paper_id):
            with store._connect() as conn:
                row = conn.execute(
                    "SELECT subject FROM pages WHERE paper_id = ? AND subject != 'Unknown' LIMIT 1",
                    (paper_id,),
                ).fetchone()
                if row and row[0]:
                    subject = row[0]

# ─── Session reset on new paper ───────────────────────────────
# Guard: clear the chat history whenever the active paper changes so
# responses from a previous paper don't bleed into the new one.
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
            {html.escape(str(badge))}
        </div>
    </div>
    <div class="hero-title" style="font-size: 2.2rem; letter-spacing: -1px; margin-bottom: 1.5rem;">
        {html.escape(str(title))}
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── Ingest paper ─────────────────────────────────────────────
_ocr_warnings: list = []
try:
    with st.spinner("Scanning document..."):
        if is_local_upload:
            from storage.cache_store import CacheStore
            store = CacheStore()
            if not store.is_cached(paper_id):
                import tempfile
                from pathlib import Path
                from ingestion.cache_writer import ingest_local_paper
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(file_bytes)
                    tmp_path = Path(tmp.name)
                try:
                    if is_other:
                        known_subjects = [subject] if subject else ["Unknown"]
                    else:
                        known_subjects = get_expected_subjects(branch, semester)
                    _ocr_warnings = ingest_local_paper(
                        paper_id, tmp_path, year=year, known_subjects=known_subjects
                    )
                finally:
                    os.remove(tmp_path)

                if not is_other:
                    with store._connect() as conn:
                        row = conn.execute(
                            "SELECT subject FROM pages WHERE paper_id = ? AND subject != 'Unknown' LIMIT 1",
                            (paper_id,),
                        ).fetchone()
                        if row and row[0]:
                            subject = row[0]
        else:
            _ocr_warnings = ingest_paper(
                paper_id=paper_id,
                pdf_url=pdf_url,
                year=year,
                branch=branch,
                semester=semester,
            )

        paper_text = get_paper_text(paper_id)

except Exception as _ingest_err:
    _msg = str(_ingest_err)
    _msg_lower = _msg.lower()

    if "password" in _msg_lower or "encrypted" in _msg_lower or "cannot open" in _msg_lower:
        st.error(
            "🔒 **Password-protected or encrypted PDF.**\n\n"
            "This PDF requires a password to open. Please use an unlocked version of the file."
        )
    elif "tesseract" in _msg_lower and ("not found" in _msg_lower or "not installed" in _msg_lower):
        st.error(
            "🔍 **Tesseract OCR is not installed.**\n\n"
            "This PDF appears to be scanned (image-only) and requires Tesseract to read.\n\n"
            "**What to try:**\n"
            "- Use a PDF with selectable text — it works without Tesseract\n"
            "- If on Streamlit Cloud: ensure `packages.txt` contains `tesseract-ocr`\n"
            "- Locally: install Tesseract via your OS package manager"
        )
    elif "fileerror" in _msg_lower or "cannot open" in _msg_lower or "no objects" in _msg_lower:
        st.error(
            "🗂️ **Corrupt or unreadable PDF.**\n\n"
            "This file could not be parsed. It may be corrupted or not a valid PDF. "
            "Try re-downloading or re-exporting the file."
        )
    else:
        st.error(
            f"❌ **Failed to process this paper:**\n\n"
            f"```\n{_msg}\n```\n\n"
            f"Check the Streamlit Cloud logs for the full error."
        )
    st.stop()

# ─── Non-blocking OCR warnings ───────────────────────────────
# Shown after ingestion; don't block the UI — the student can still use
# the text that WAS extracted successfully.
if _ocr_warnings:
    _tesseract_missing = any(
        w.startswith("TESSERACT_MISSING") for w in _ocr_warnings
    )
    if _tesseract_missing:
        st.error(
            "🔍 **Tesseract OCR is not installed — scanned pages cannot be read.**\n\n"
            "Digital-text PDFs still work normally. To enable OCR:\n"
            "- Streamlit Cloud: ensure `packages.txt` contains `tesseract-ocr`\n"
            "- Local: install Tesseract via your OS package manager"
        )
    else:
        for w in _ocr_warnings:
            st.warning(f"⚠️ **{w}** — some questions may be missing or inaccurate.")

# ─── Guard: paper text could be empty if all pages had failed OCR ─────────
if not paper_text or not paper_text.strip():
    st.error(
        "⚠️ **No text could be extracted from this PDF.**\n\n"
        "This usually happens when:\n"
        "- The PDF contains only scanned images and OCR failed\n"
        "- Tesseract OCR is not installed or the page quality is too low\n"
        "- The PDF is corrupted or uses an unsupported image format\n\n"
        "**What to try:**\n"
        "- Use a PDF with selectable text instead of a scanned image\n"
        "- Ensure Tesseract OCR is installed on the server (`packages.txt` should list `tesseract-ocr`)\n"
        "- Re-download or re-export the PDF and try again"
    )
    st.stop()

# ─── Actions + Chat ───────────────────────────────────────────
render_action_buttons(paper_text, subject=subject)
render_chat_box(paper_text)
render_usage_meter()
