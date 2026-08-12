"""
Two-path Q&A routing for Campus Brain:

1. knowledge_answer() — concept/theory questions ("What is X?", "Explain Y"):
   Routes to the LLM's intrinsic knowledge with NO paper text attached.
   Higher temperature (0.5) gives richer, more discursive academic prose.
   Comprehensive 300+ word answers, exam-ready structure.

2. answer_question() — paper-grounded questions ("Which topics are in section A?"):
   Injects the full extracted exam paper text into the prompt so the model
   stays strictly grounded in what the paper actually says.
   Low temperature (0.2) keeps it factual and deterministic.

The router (router/intent_router.py) decides which path to call based on
keyword matching on the student's free-text input.
"""
from services.llm_client import generate_text

# ── Path 1: Pure knowledge answer ─────────────────────────────────────────────
KNOWLEDGE_PROMPT = """You are an expert university-level academic tutor.
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


def knowledge_answer(question: str) -> str:
    """Answer a concept/theory question purely from intrinsic LLM knowledge.

    Uses temperature=0.5 so the model produces richer explanatory prose
    while still staying academically accurate (higher than 0.2 but not
    creative enough to hallucinate facts).
    """
    prompt = KNOWLEDGE_PROMPT.format(question=question)
    return generate_text(prompt, temperature=0.5)


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
