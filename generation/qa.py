"""
Grounded Q&A over a single paper. Full-context stuffing, not vector retrieval:
one paper's OCR'd text is small enough to hand the model whole, and this
avoids the false negatives an embedding similarity miss could cause.

The model uses the paper as primary context but falls back to general
knowledge for concept explanations (exam papers contain questions, not
answers, so students often need both).
"""
from services.llm_client import generate_text

QA_PROMPT = """You are a helpful academic assistant helping a student study for exams.
You have access to the student's exam paper text below.

Your behaviour:
1. If the student's question can be answered FROM the paper text (e.g. asking about
   specific questions, marks, topics listed), answer using the paper and cite the
   question number or section.
2. If the question asks you to EXPLAIN a concept or ANSWER an exam question
   (which are questions IN the paper, not answered BY the paper), use your general
   academic knowledge to provide a clear, helpful explanation. Mention that you are
   drawing on general knowledge, not the paper itself.
3. Keep answers concise, student-friendly, and well-structured.

--- EXAM PAPER TEXT ---
{paper_text}
--- END EXAM PAPER TEXT ---

Student question: {question}

Answer:"""


def answer_question(paper_text: str, question: str) -> str:
    prompt = QA_PROMPT.format(paper_text=paper_text, question=question)
    return generate_text(prompt)
