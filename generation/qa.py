"""
Grounded Q&A over a single paper. Full-context stuffing, not vector retrieval:
one paper's OCR'd text is small enough to hand the model whole, and this
avoids the false negatives an embedding similarity miss could cause.

The model uses the paper as primary context but answers exam questions from
its own academic knowledge (papers contain questions, not answers).
"""
from services.llm_client import generate_text

QA_PROMPT = """You are an expert academic tutor helping a student prepare for their university exams.
You have the student's exam paper text below — use it to understand what topics are covered.

=== HOW TO ANSWER ===

TYPE A — Student asks about paper structure (e.g. "how many questions?", "what are the marks?", "list all topics"):
→ Answer directly from the paper text. Be concise.

TYPE B — Student asks you to EXPLAIN or ANSWER an exam question (e.g. "explain ACID properties", "what is recursion?", "answer Q3"):
→ The paper only contains QUESTIONS, not answers. Use your own deep academic knowledge.
→ Write a thorough, exam-ready answer of 250-350 words minimum.
→ Use structure: definition → explanation → example → significance.
→ Use bullet points or numbered steps where helpful.
→ Do NOT say "the paper doesn't contain the answer" — just answer the question directly.

TYPE C — Student asks something general related to the subject (not in the paper at all):
→ Answer fully from your academic knowledge, 200-300 words minimum.
→ Relate it back to exam context where possible.

=== EXAM PAPER TEXT ===
{paper_text}
=== END EXAM PAPER ===

Student question: {question}

Answer (be thorough, structured, and exam-ready):"""


def answer_question(paper_text: str, question: str) -> str:
    prompt = QA_PROMPT.format(paper_text=paper_text, question=question)
    return generate_text(prompt, temperature=0.4)
