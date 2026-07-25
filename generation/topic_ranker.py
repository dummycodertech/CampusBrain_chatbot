"""
Cross-year topic ranking for a subject: "what's the most important/repeated
topic". Filters by subject (deterministic, already tagged at ingestion), then
asks the model to rank recurring topics across the filtered set -- this is
aggregation over a known corpus, not similarity search.
"""
from typing import List, Tuple
from services.llm_client import generate_text

RANK_PROMPT = """Below are exam papers for the same subject across multiple years.
Identify which topics/questions repeat most often across years, and rank them
by how frequently they appear. Cite which years each topic showed up in.

{papers_block}

Return a ranked list, most important/most repeated topic first."""


def rank_topics(subject_corpus: List[Tuple[str, str]]) -> str:
    """subject_corpus: [(year, text), ...] from retrieval.subject_lookup"""
    papers_block = "\n\n".join(
        f"--- YEAR {year} ---\n{text}" for year, text in subject_corpus
    )
    return generate_text(RANK_PROMPT.format(papers_block=papers_block))
