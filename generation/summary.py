"""Fixed-template summary of a single paper -- the "Summarize" button, no typing required."""
from services.llm_client import generate_text

SUMMARY_PROMPT = """Summarize this exam paper for a student revising for the exam.
Only use the text below.

--- PAPER TEXT ---
{paper_text}
--- END PAPER TEXT ---

Give:
1. The key topics/chapters this paper covers (bullet list)
2. Which question types appear most (numerical / theory / diagram-based, etc.)
3. Anything a student should specifically revise, based on what's asked"""


def summarize_paper(paper_text: str) -> str:
    return generate_text(SUMMARY_PROMPT.format(paper_text=paper_text))
