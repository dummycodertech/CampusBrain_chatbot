# 🧠 Campus Brain — PYQ AI Study Assistant

> **AI-powered Previous Year Question (PYQ) study assistant** built with Streamlit, Tesseract OCR, and Groq.  
> Drop any exam paper — scanned or digital — and get instant summaries, practice quizzes, flashcards, and grounded answers on demand.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://campusbrain.streamlit.app)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

| Feature | Description |
|---|---|
| 📄 **Smart PDF Ingestion** | Intelligent pipeline: direct text extraction → local Tesseract OCR (with multi-PSM retry and image preprocessing). Zero external API cost. |
| 🗺️ **Subject Tagging** | Automatically detects and tags each page to its subject using regex header matching + configurable semester curricula |
| 💬 **Two-path Q&A** | Concept questions → LLM knowledge base; paper-specific questions → grounded in extracted text |
| 📝 **Summarize** | One-click paper summary highlighting key topics and section weights |
| 🧪 **Quiz Generator** | Strict JSON-schema multiple-choice quiz — regenerates fresh questions each time |
| 🃏 **Flashcard Generator** | Auto-generated topic flashcards for rapid revision |
| 📊 **Topic Ranker** | Cross-year frequency analysis showing which topics appear most in past exams |
| 🌐 **Zero-backend integration** | Embeds into any website via `<iframe>` or `<a>` link — no API calls back to the host site |
| 📤 **Local Upload** | Drag-and-drop any PDF directly from the landing page without website integration |
| 🌍 **Web Search** | Tavily-powered web search for questions that need up-to-date information beyond the paper |

---

## 🏗️ Architecture

### OCR Pipeline (no quota, no API key required)

```
PDF uploaded
    │
    ▼
PyMuPDF — direct text extraction
    │
    ├── ≥ 80 chars extracted?  →  Text page ✅  (free, instant)
    │
    └── < 80 chars (scanned page)
            │
            ▼
        Preprocess (Grayscale → Autocontrast → Median Filter → Threshold)
            │
            ▼
        Tesseract OCR (300 DPI, multi-PSM retry: 6 → 4 → 3)
            │
            └── Done ✅  (zero API cost, line reconstructed)
```

**Result:** Fast, local, memory-safe OCR ingestion running on Tesseract with zero external API quota consumed.

### Text Generation Pipeline

```
Extracted text
    │
    └── Groq LLM (openai/gpt-oss-120b)
            ├── Q&A  (two-path: knowledge vs. paper-grounded)
            ├── Summary
            ├── Quiz  (strict JSON schema)
            ├── Flashcards
            └── Topic Ranking
```

### Project Structure

```
campus-brain/
├── app.py                        # Streamlit entrypoint (URL-param + local-upload modes)
├── packages.txt                  # System dependencies for Streamlit Cloud (tesseract-ocr)
├── requirements.txt              # Python dependencies
│
├── ingestion/
│   ├── pdf_to_images.py          # Hybrid PyMuPDF extraction + image rendering
│   ├── ocr_tagger.py             # Tesseract OCR pipeline with line reconstruction & subject tagging
│   ├── cache_writer.py           # Ingestion orchestrator — idempotent, SQLite-backed
│   └── subject_reference.py      # Loads expected subject list for a branch/semester
│
├── storage/
│   └── cache_store.py            # SQLite cache — only stores pages with real extracted text
│
├── retrieval/
│   ├── paper_lookup.py           # Fetch full text for a paperId
│   └── subject_lookup.py         # Cross-paper lookup by subject name
│
├── generation/
│   ├── qa.py                     # Two-path Q&A (knowledge vs. paper-grounded)
│   ├── summary.py                # Paper summarizer
│   ├── quiz.py                   # Quiz generator (strict JSON schema)
│   ├── flashcards.py             # Flashcard generator
│   └── topic_ranker.py           # Cross-year topic frequency ranking
│
├── router/
│   └── intent_router.py          # Keyword-based intent detection for the chat interface
│
├── services/
│   ├── llm_client.py             # Groq text wrapper with fallback model chain
│   └── web_search.py             # Tavily web search integration
│
├── components/
│   ├── theme.py                  # Premium dark CSS + aurora animations
│   ├── action_buttons.py         # Summarize / Quiz / Flashcards / Topic Rank buttons
│   └── chat_box.py               # Chat UI with intent routing
│
└── data/
    └── subjects_by_semester.json # Curriculum reference (branch-semester → subjects)
```

---

## ⚡ Quick Start

### Prerequisites

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed locally
- A [Groq API key](https://console.groq.com/) — free tier works

### Install Tesseract

```bash
# Ubuntu / Debian / Streamlit Cloud
sudo apt-get install tesseract-ocr

# macOS
brew install tesseract

# Windows — download installer from:
# https://github.com/UB-Mannheim/tesseract/wiki
```

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/dummycodertech/CampusBrain_chatbot.git
cd CampusBrain_chatbot

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Configure environment variables
# Create a .env file with:
GROQ_API_KEY="gsk_..."
TAVILY_API_KEY="tvly-..."          # optional — enables web search

# 5. Run the app
streamlit run app.py
```

---

## 🔌 Website Integration

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

> **⚠️ Breaking change warning**: if either side renames `paperId`, `pdfUrl`, `subject`, or `year`, the other breaks silently. Coordinate before renaming.

---

## 📚 Subject Reference (`data/subjects_by_semester.json`)

PYQ PDFs are semester-wide bundles mixing several subjects. Ingestion needs the full expected subject list for the bundle to correctly tag pages.

```json
{
  "IT-3": ["Data Structures", "Digital Electronics", "Object Oriented Programming", "..."],
  "CS-5": ["Operating Systems", "Computer Networks", "Database Management Systems", "..."]
}
```

- Key format: `"<branch>-<semester>"` (e.g. `"IT-3"`)
- `ingest_paper` looks it up automatically via `branch`/`semester` query params
- If a branch+semester is not mapped, tagging falls back to open-ended header detection

---

## 🚀 Deployment (Streamlit Cloud)

1. Push to GitHub
2. Connect to [share.streamlit.io](https://share.streamlit.io)
3. Streamlit Cloud will auto-install `tesseract-ocr` from `packages.txt` — no manual setup needed
4. Add secrets in **App Settings → Secrets**:

```toml
GROQ_API_KEY = "gsk_..."
TAVILY_API_KEY = "tvly-..."          # optional
```

5. Deploy — app is publicly accessible at `https://<your-app>.streamlit.app`

> **Note:** The SQLite cache lives on Streamlit Cloud's ephemeral filesystem and resets on each redeploy. Users will need to re-process PDFs after a new deployment. For production persistence, migrate `cache_store.py` to an external database (Supabase, PlanetScale, etc.).

---

## 🛠️ Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| UI Framework | Streamlit 1.38 | |
| PDF Parsing | PyMuPDF (fitz) | Text extraction + image rendering |
| OCR | **Tesseract OCR** + pytesseract | Free, local, no quota |
| Text Generation | Groq — `openai/gpt-oss-120b` | With `gpt-oss-20b` + `qwen3.8-27b` fallback chain |
| Web Search | Tavily | Optional |
| Cache / Storage | SQLite (`sqlite3`) | Only stores pages with real extracted text |
| Styling | Custom CSS | Inter font, glassmorphism, aurora gradient animations |

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.
