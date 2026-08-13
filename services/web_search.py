"""
Web search service for Campus Brain — powered by Tavily.

Why Tavily over raw Google/Bing scraping?
- One clean API call returns pre-extracted text snippets (no HTML parsing)
- `search_depth="advanced"` fetches and parses the full page content, giving
  the LLM much richer context than a snippet-only search
- `include_answer=True` requests Tavily's own extractive summary, which is a
  useful fallback when individual page snippets are thin

Quota: Tavily free tier = 1,000 searches/month (~33/day).
Each student question that routes to `knowledge_answer()` uses one search.

Failure modes — all silently return [] so the caller falls back gracefully:
- TAVILY_API_KEY not set in environment
- Tavily API returns an error (network, rate limit, invalid key)
- Search returns zero results for a very niche query
"""
import os
from typing import List, Dict


def search_web(query: str, max_results: int = 3) -> List[Dict]:
    """Search the web via Tavily and return the top results as plain dicts.

    Each result dict has:
      - "title"   : page title
      - "url"     : source URL
      - "content" : extracted page text (can be several hundred words)
      - "score"   : Tavily relevance score (float, higher = more relevant)

    Returns an empty list [] if:
      - TAVILY_API_KEY is not in the environment
      - The search call raises any exception (network, quota, etc.)
    This ensures callers always get a safe fallback.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        print("[web_search] TAVILY_API_KEY not set — skipping web search.")
        return []

    try:
        from tavily import TavilyClient  # imported lazily so missing package doesn't crash startup
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            search_depth="advanced",   # full page content, not just snippets
            max_results=max_results,
            include_answer=True,       # Tavily's own extractive summary
            include_raw_content=False, # we don't need raw HTML
        )
        results = response.get("results", [])
        print(f"[web_search] Tavily returned {len(results)} result(s) for: {query!r}")
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content", ""),
                "score":   r.get("score", 0.0),
            }
            for r in results
            if r.get("content")  # skip results with no extracted text
        ]

    except ImportError:
        print("[web_search] tavily-python not installed — skipping web search.")
        return []
    except Exception as exc:
        print(f"[web_search] Search failed ({type(exc).__name__}: {exc}) — skipping.")
        return []
