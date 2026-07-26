"""
Lightweight keyword-based intent detection for the free-text box only.
The Summarize/Quiz buttons bypass this entirely -- this only runs when the
student types something instead of clicking a button.

Four intents:
- quiz       → generate MCQ quiz from paper
- summary    → summarize paper topics
- knowledge  → explain a concept / answer an exam question from general knowledge
- qa         → answer something about the paper's structure/content
"""
import re

QUIZ_KEYWORDS = ["quiz", "test me", "mcq", "questions on", "generate questions"]
SUMMARY_KEYWORDS = ["summar", "important topic", "overview", "key point", "most repeated"]

# Questions asking for concept explanations / exam answers — should use
# intrinsic knowledge, NOT be grounded in the paper text.
_KNOWLEDGE_PATTERNS = re.compile(
    r"^(what is|what are|what do you mean|what does|define |explain |how does|how do|why is|why are"
    r"|describe |tell me about|give me|can you explain|difference between|compare |contrast "
    r"|answer q\d|ans q\d|solve q\d|write (a |an |short |long |brief )?note)",
    re.IGNORECASE,
)


def route_intent(user_text: str) -> str:
    text = user_text.strip().lower()
    if any(word in text for word in QUIZ_KEYWORDS):
        return "quiz"
    if any(word in text for word in SUMMARY_KEYWORDS):
        return "summary"
    if _KNOWLEDGE_PATTERNS.match(user_text.strip()):
        return "knowledge"
    return "qa"
