"""
Answer checker for Campus Brain.

Design choices for free-tier efficiency:
- Single LLM call per check — student's answer + question + relevant paper
  context are sent together.
- Paper text is truncated to 4000 chars: the checker only needs to verify
  whether the answer is consistent with what the paper implies, not read
  the whole document.
- Temperature 0.2 — deterministic grading, not creative.
- Returns a plain string (no JSON parsing needed), so there's zero risk of
  parse failure causing a crash.
"""
from services.llm_client import generate_text

_MAX_PAPER_CHARS = 4000

CHECKER_PROMPT = """You are a strict but fair university exam grader.

A student has attempted to answer an exam question. Your job is to:
1. Evaluate whether their answer is correct, partially correct, or incorrect.
2. Explain what they got right and what they missed or got wrong.
3. Give them a score out of 10.
4. Provide a model answer they can learn from.

--- EXAM PAPER CONTEXT ---
{paper_context}
--- END CONTEXT ---

Question the student attempted:
{question}

Student's answer:
{student_answer}

Respond in this exact format:

**Score: X/10**

**Verdict:** [Correct / Partially Correct / Incorrect]

**What you got right:**
[bullet points]

**What you missed or got wrong:**
[bullet points, or "Nothing — well done!" if fully correct]

**Model Answer:**
[a complete, exam-ready answer the student can compare against]"""


def check_answer(paper_text: str, question: str, student_answer: str) -> str:
    """Grade a student's answer against the paper and LLM knowledge.

    Args:
        paper_text:     Full OCR'd paper text (will be truncated internally).
        question:       The specific question the student is answering.
        student_answer: The student's written response.

    Returns:
        A formatted markdown string with score, verdict, feedback, and model answer.
    """
    # Truncate paper to keep token usage low
    paper_context = paper_text[:_MAX_PAPER_CHARS]
    if len(paper_text) > _MAX_PAPER_CHARS:
        paper_context += "\n[... paper truncated ...]"

    prompt = CHECKER_PROMPT.format(
        paper_context=paper_context,
        question=question.strip(),
        student_answer=student_answer.strip(),
    )
    return generate_text(prompt, temperature=0.2)
