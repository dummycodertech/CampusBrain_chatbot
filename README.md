# 🧠 Campus Brain — PYQ AI Assistant

> **AI-powered Previous Year Question (PYQ) study assistant** built with Streamlit, Gemini Vision, and Groq.
> Drop any exam paper and get instant summaries, practice quizzes, and grounded answers on demand.

---

## ✨ Features

| Feature | Description |
|---|---|
| 📄 **Smart PDF Ingestion** | Hybrid pipeline: direct text extraction (PyMuPDF) with Gemini Vision OCR fallback for scanned pages |
| 🗺️ **Subject Tagging** | Automatically detects and tags each page to its subject using configurable semester curricula |
| 💬 **Two-path Q&A** | Concept questions → LLM knowledge base; paper-specific questions → grounded in extracted text |
| 📝 **Summarize** | One-click paper summary highlighting key topics and section weights |
| 🧪 **Quiz Generator** | Fixed JSON-schema multiple-choice quiz — regenerates fresh questions each time |
| 📊 **Topic Ranker** | Cross-year frequency analysis showing which topics appear most in exams |
| 🌐 **Zero-backend integration** | Embeds into any website via `<iframe>` or `<a>` link — no API calls back to the host site |
| 📤 **Local Upload** | Drag-and-drop any PDF directly from the landing page without a website integration |

---

## 🏗️ Architecture

```
Campus Brain
├── app.py                   # Streamlit entrypoint (URL-param + local-upload mode)
├── ingestion/
│   ├── pdf_to_images.py     # Hybrid PyMuPDF + Gemini Vision OCR pipeline
│   ├── cache_writer.py      # Ingestion orchestrator (idempotent, SQLite-backed)
│   └── subject_reference.py # Loads expected subject list for a branch/semester
├── storage/
│   └── cache_store.py       # SQLite cache of extracted, tagged page text
├── retrieval/
│   ├── paper_lookup.py      # Look up full text for a paperId
│   └── subject_lookup.py    # Cross-paper lookup by subject name
├── generation/
│   ├── qa.py                # Two-path Q&A (knowledge vs. paper-grounded)
│   ├── summary.py           # Paper summarizer
│   ├── quiz.py              # Quiz generator (fixed JSON schema)
│   └── topic_ranker.py      # Cross-year topic frequency ranking
├── router/
│   └── intent_router.py     # Keyword-based intent detection for the chat box
├── services/
│   └── llm_client.py        # Gemini (vision/OCR) + Groq (text) wrappers
├── components/
│   ├── theme.py             # Stitch-style premium dark CSS + aurora animations
│   ├── action_buttons.py    # Summarize / Quiz / Topic Rank buttons
│   └── chat_box.py          # Chat UI with intent routing
└── data/
    └── subjects_by_semester.json   # Curriculum reference (branch-semester → subjects)
```

---

## ⚡ Quick Start

### Prerequisites
- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/app/apikey) (free tier works)
- A [Groq API key](https://console.groq.com/) (free tier works)

### Setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/dummycodertech/CampusBrain_chatbot.git
cd CampusBrain_chatbot

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env
# Edit .env and fill in GEMINI_API_KEY and GROQ_API_KEY
# For multiple Gemini keys (key rotation): GEMINI_API_KEYS=key1,key2,key3

# 5. Run the app
streamlit run app.py
```

---

## 🔌 Website Integration Contract

The website passes everything the app needs via URL query params.
**This app never calls back into the website's backend at runtime.**

### Query string format

```
?paperId=<unique-id>
 &pdfUrl=<public-PDF-URL>
 &subject=<subject-name>
 &year=<year>
 &branch=<branch>           # e.g. IT, CS, MECH
 &semester=<semester>       # e.g. 3, 5, 7
```

### Embed as iframe

```html
<iframe
  src="https://<app-url>/?paperId=cs5-ds-2024&pdfUrl=https://cdn.example.com/paper.pdf&subject=Data+Structures&year=2024&branch=CS&semester=5"
  width="100%"
  height="800"
  frameborder="0">
</iframe>
```

### Hyperlink fallback

```html
<a href="https://<app-url>/?paperId=...&pdfUrl=...&subject=...&year=..."
   target="_blank">Open AI Assistant</a>
```

> **⚠️ Breaking change warning**: if either side renames `paperId`, `pdfUrl`, `subject`, or `year`, the other breaks silently (wrong param names are just ignored). Coordinate before renaming.

---

## 🧪 Testing Without the Website

You can test the full pipeline with any public PDF URL before the website is ready:

```
http://localhost:8501/?paperId=test1&pdfUrl=<your-pdf-url>&subject=Data+Structures&year=2024&branch=CS&semester=5
```

Any publicly reachable PDF works (Supabase Storage, Cloudinary, direct-download Google Drive, etc.).

---

## 📚 Subject Reference (`data/subjects_by_semester.json`)

Since PYQ PDFs are semester-wise bundles mixing several subjects, ingestion needs to know the full expected subject list for a bundle to tag pages correctly — not just the single subject the student is currently viewing.

```json
{
  "IT-3": ["Data Structures", "Digital Electronics", "Object Oriented Programming", "..."],
  "CS-5": ["Operating Systems", "Computer Networks", "Database Management Systems", "..."]
}
```

- Fill this from your official curriculum **once**.
- The key format is `"<branch>-<semester>"` (e.g. `"IT-3"`).
- `ingest_paper` looks it up automatically via `branch`/`semester` params.
- If a branch+semester isn't mapped, tagging falls back to open-ended header detection — naming may be less consistent, so fill the reference for any branch/semester you plan to demo.

---

## 🔑 Multi-Key API Rotation (Gemini)

To avoid hitting free-tier daily quotas on large batches of papers, you can supply multiple Gemini API keys:

```env
GEMINI_API_KEYS=AIzaSy...key1,AIzaSy...key2,AIzaSy...key3
```

The client automatically:
- Rotates to the next key on per-minute rate limits (honours the API's `retryDelay`)
- Permanently skips keys that have hit daily quotas
- Falls back to `gemini-2.5-flash-lite` (separate quota pool) if all keys for the primary model are exhausted

---

## 🚀 Deployment (Streamlit Cloud)

1. Push to GitHub (this repo)
2. Connect to [share.streamlit.io](https://share.streamlit.io)
3. Add your secrets in **App Settings → Secrets**:
   ```toml
   GEMINI_API_KEY = "AIzaSy..."
   GROQ_API_KEY = "gsk_..."
   ```
4. Deploy — the app is publicly accessible at `https://<your-app>.streamlit.app`

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | Streamlit |
| PDF Parsing | PyMuPDF (fitz) |
| Vision OCR | Gemini 2.5 Flash (`google-genai` SDK) |
| Text Generation | Groq — Llama 3.3 70B Versatile |
| Cache / Storage | SQLite (via Python `sqlite3`) |
| Styling | Custom CSS injected via `st.markdown` — Inter font, aurora animations |
