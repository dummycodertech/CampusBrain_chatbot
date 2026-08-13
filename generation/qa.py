"""
Two-path Q&A routing for Campus Brain:

1. knowledge_answer() — concept/theory/math/code questions:
   Calls Tavily web search first to pull live, accurate source material.
   Injects the top results as [Source N] blocks into the LLM prompt so
   answers are grounded in real web content instead of the model's (possibly
   stale or hallucinated) intrinsic knowledge.
   Falls back to pure-LLM intrinsic knowledge if Tavily is unavailable or
   returns no results — so behaviour degrades gracefully, never breaks.

2. answer_question() — paper-grounded questions ("Which topics are in section A?"):
   Injects the full extracted exam paper text into the prompt so the model
   stays strictly grounded in what the paper actually says.
   Low temperature (0.2) keeps it factual and deterministic.

The router (router/intent_router.py) decides which path to call based on
keyword matching on the student's free-text input.
"""
from services.llm_client import generate_text
from services.web_search import search_web


# ── Path 1a: Web-augmented knowledge answer ───────────────────────────────────
_WEB_KNOWLEDGE_PROMPT = """You are an expert university-level academic tutor.
A student is preparing for their exam and has asked: {question}

Use the web sources below to give an accurate, well-structured answer.
These sources are current and authoritative — prefer them over your training data.

{sources_block}

Rules:
- Write at least 300 words. Never give a short one-paragraph reply.
- Structure your answer clearly:
    • Start with a crisp 1-2 sentence definition or direct answer.
    • Expand with a detailed explanation (mechanisms, steps, types, etc.)
    • Give 1-2 concrete real-world or worked examples where relevant.
    • End with why it matters / exam significance.
- Use bullet points, numbered lists, or subheadings where they aid clarity.
- Cite sources inline as [Source 1], [Source 2] etc. where you use their content.
- At the end, add a "**Sources:**" section listing the URLs you cited.
- Write in a student-friendly but academically rigorous tone.
- Do NOT reference "the paper" or "the exam document" — just answer the question.

Answer:"""


# ── Path 1b: Pure-LLM fallback (no web results) ──────────────────────────────
_INTRINSIC_KNOWLEDGE_PROMPT = """You are an expert university-level academic tutor.
A student is preparing for their exam and has asked you the following question.
Answer it comprehensively from your own academic knowledge.

Rules:
- Write at least 300 words. Never give a short one-paragraph reply.
- Structure your answer clearly:
    • Start with a crisp 1-2 sentence definition.
    • Expand with a detailed explanation (mechanisms, components, types, etc.)
    • Give 1-2 concrete real-world examples.
    • End with why it matters / exam significance.
- Use bullet points, numbered lists, or subheadings where they aid clarity.
- Write in a student-friendly but academically rigorous tone.
- Do NOT reference "the paper" or "the exam document" — just answer the question.

Student's question: {question}

Answer:"""


def _build_sources_block(results: list) -> str:
    """Format Tavily results into a numbered source block for the LLM prompt."""
    lines = []
    for i, r in enumerate(results, start=1):
        # Truncate content to ~800 chars so we don't blow the context window
        snippet = r["content"][:800].strip()
        if len(r["content"]) > 800:
            snippet += "…"
        lines.append(
            f"[Source {i}] {r['title']}\n"
            f"URL: {r['url']}\n"
            f"{snippet}"
        )
    return "\n\n".join(lines)


def knowledge_answer(question: str) -> str:
    """Answer a concept/theory/math/code question.

    Flow:
    1. Call Tavily web search for the student's question.
    2. If results → build a grounded prompt with [Source N] blocks → Groq LLM.
    3. If no results (key missing, quota, niche query) → fall back to pure-LLM
       intrinsic knowledge prompt (original behaviour, zero regression).

    Temperature 0.4 — richer prose than factual QA (0.2) but still accurate.
    """
    results = search_web(question, max_results=3)

    if results:
        sources_block = _build_sources_block(results)
        prompt = _WEB_KNOWLEDGE_PROMPT.format(
            question=question,
            sources_block=sources_block,
        )
        print(f"[qa] Web-augmented answer using {len(results)} Tavily source(s).")
    else:
        prompt = _INTRINSIC_KNOWLEDGE_PROMPT.format(question=question)
        print("[qa] No Tavily results — using intrinsic LLM knowledge.")

    return generate_text(prompt, temperature=0.4)


# ── Path 2: Paper-grounded answer ─────────────────────────────────────────────
PAPER_QA_PROMPT = """You are an academic assistant helping a student navigate their exam paper.
The student wants to know something specific about the paper's content or structure.

Use the exam paper text below to answer accurately. Cite question numbers or sections where relevant.

=== EXAM PAPER TEXT ===
{paper_text}
=== END EXAM PAPER ===

Student question: {question}

Answer:"""


def answer_question(paper_text: str, question: str) -> str:
    """Answer a question grounded in the paper's text (structure, topics, marks, etc.).

    Temperature is intentionally low (0.2) because the model should only
    rephrase what the paper text says, not improvise extra detail.
    """
    prompt = PAPER_QA_PROMPT.format(paper_text=paper_text, question=question)
    return generate_text(prompt, temperature=0.2)

