"""
Lightweight keyword-based intent detection for the free-text box only.
The Summarize/Quiz buttons bypass this entirely -- this only runs when the
student types something instead of clicking a button.

Keyword matching is deliberately used instead of an LLM classifier: there are
only three output shapes, and the trigger words are predictable. An LLM
router would be solving a harder problem than actually exists here.
"""

QUIZ_KEYWORDS = ["quiz", "test me", "mcq", "questions on", "generate questions"]
SUMMARY_KEYWORDS = ["summar", "important topic", "overview", "key point", "most repeated"]


def route_intent(user_text: str) -> str:
    text = user_text.lower()
    if any(word in text for word in QUIZ_KEYWORDS):
        return "quiz"
    if any(word in text for word in SUMMARY_KEYWORDS):
        return "summary"
    return "qa"
