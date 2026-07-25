# pyq-assistant

RAG chatbot service for the PYQ portal. Reads a paper's PDF, extracts and
subject-tags its text once, then answers questions, summarizes, and generates
quizzes for it. Deployed standalone (Streamlit) and embedded into the MERN
website via iframe (or a plain hyperlink as a fallback).

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY and GROQ_API_KEY
streamlit run app.py
```

Requires Python 3.10+.

## The integration contract (shared with the website repo)

The website passes everything this app needs directly as URL query params.
This app never calls back into the website's backend at runtime -- it only
needs a publicly fetchable PDF URL and metadata from the query string.

```
?paperId=<unique id>&pdfUrl=<public PDF URL>&subject=<subject name>&year=<year>&branch=<branch>&semester=<semester>
```

`branch`/`semester` are just the catalog filter values the website already
tracks -- not a new field to build. They're used to look up the expected
subject list locally (see below), so the frontend never needs to compute or
pass a subject array.

Embedded: `<iframe src="https://<this-app-url>/?embed=true&paperId=...&pdfUrl=...&subject=...&year=..." />`

Hyperlink fallback: `<a href="https://<this-app-url>/?paperId=...&pdfUrl=...&subject=...&year=..." target="_blank">Open AI Assistant</a>`

Both use the exact same params -- switching between iframe and hyperlink is a
frontend-only change, nothing here changes.

**If either side renames a param, the other breaks silently** (a wrong param
name is just ignored, not an error) -- ping before changing `paperId` /
`pdfUrl` / `subject` / `year`.

## Testing without the website

Since the app only needs query params, you can test the entire pipeline with
your own sample PDFs before the website exists:

```
http://localhost:8501/?paperId=test1&pdfUrl=<your-test-pdf-url>&subject=Data+Structures&year=2024
```

Any publicly reachable PDF URL works (a public Supabase/Cloudinary link, a
direct-download Google Drive link, etc.) -- swap in the real URLs once the
website is ready, nothing else in this repo changes.

## Structure

- `ingestion/` -- runs once per paper: fetch PDF, split to page images, OCR +
  subject-tag via Gemini Vision, forward-filling subject across pages with no
  header of their own.
- `storage/` -- SQLite cache of extracted, tagged text. Query-time code only
  ever reads from here.
- `retrieval/` -- deterministic lookups by `paperId` or by `subject` across
  years. No embeddings or vector search: the filter key is always known and
  exact, and each paper is small enough to hand the model in full.
- `generation/` -- the three answer modes: grounded Q&A, summary, quiz (fixed
  JSON schema), plus cross-year topic ranking.
- `router/` -- keyword-based intent detection for the free-text chat box only
  (Summarize/Quiz buttons bypass this entirely).
- `components/` -- Streamlit UI pieces.
- `services/llm_client.py` -- Gemini (vision/OCR) and Groq (text generation)
  wrappers.

## Subject reference (data/subjects_by_semester.json)

Since your source PDFs are semester-wise bundles mixing several subjects,
tagging needs to know the full expected subject list for that bundle -- not
just the one subject a student is currently viewing. Rather than asking the
frontend to compute and pass that array, it's maintained locally here:

- Fill `data/subjects_by_semester.json` from your official curriculum once,
  keyed as `"<branch>-<semester>"` (e.g. `"IT-3"`). It doesn't change per
  upload.
- `ingest_paper` looks it up via `branch`/`semester` automatically
  (`ingestion/subject_reference.py`) -- the frontend only ever passes those
  two plain strings, which it already needs for catalog filtering anyway.
- If a branch+semester isn't mapped, tagging falls back to open-ended header
  detection with no canonical list to snap to -- naming may be less
  consistent across years for that combination, so fill the reference for
  any branch/semester you actually plan to demo.
