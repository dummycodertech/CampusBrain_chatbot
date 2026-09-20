"""Summary generator for Campus Brain.

The input is a Previous Year Question (PYQ) paper — questions only, no answers.
The prompt is written for this reality: it extracts topics, marks distribution,
and revision priorities from the questions themselves, which is genuinely
useful exam intelligence even without an answer sheet.
"""
from services.llm_client import generate_text

SUMMARY_PROMPT = """You are an expert exam coach helping a student prepare for their university exam.
The text below is a Previous Year Question (PYQ) paper — it contains ONLY exam questions,
not answers or marking schemes.

--- PYQ PAPER TEXT ---
{paper_text}
--- END PYQ PAPER TEXT ---

Analyse the questions and produce a revision-focused summary with these sections:

**1. Topics & Chapters Covered** (bullet list)
List every distinct topic or chapter this paper tests. Be specific (e.g. "OS: Deadlocks & Banker's Algorithm", not just "Operating Systems").

**2. Question Type Breakdown**
How many questions are: Theory / Numerical / Derivation / Diagram / Code-based? Give approximate counts.

**3. Marks Weightage** (if marks are visible in the paper)
Which topics carry the most marks? List top 3-5.

**4. Top Questions to Master**
Pick the 5 most important questions a student must be able to answer — quote them briefly and explain why they matter.

**5. Last-Minute Revision Checklist**
Give 5-7 specific things a student should study the night before, based purely on what this paper asks."""


def summarize_paper(paper_text: str) -> str:
    return generate_text(SUMMARY_PROMPT.format(paper_text=paper_text))
