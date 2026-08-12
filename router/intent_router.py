"""
Lightweight keyword-based intent detection for the free-text box only.
The Summarize / Quiz / Flashcards buttons bypass this entirely -- this only
runs when the student types something instead of clicking a button.

Five intents:
- quiz        → generate MCQ quiz from paper
- summary     → summarize paper topics
- flashcards  → generate Anki-style term/definition revision cards
- knowledge   → explain a concept / answer an exam question from general knowledge
- qa          → answer something about the paper's structure/content
"""
import re

QUIZ_KEYWORDS = ["quiz", "test me", "mcq", "questions on", "generate questions"]
SUMMARY_KEYWORDS = ["summar", "important topic", "overview", "key point", "most repeated"]
# Flashcard keywords: cover natural phrasings students might type
FLASHCARD_KEYWORDS = [
    "flashcard", "flash card", "flash cards", "revision card",
    "make cards", "create cards", "give me cards", "study cards",
    "term", "key terms", "definitions",
]

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
    # Check flashcards before the knowledge pattern so "give me flashcards"
    # isn't swallowed by the broad "give me" knowledge trigger.
    if any(word in text for word in FLASHCARD_KEYWORDS):
        return "flashcards"
    if _KNOWLEDGE_PATTERNS.match(user_text.strip()):
        return "knowledge"
    return "qa"
