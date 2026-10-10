"""
Lightweight keyword-based intent detection for the free-text box only.
The Summarize / Quiz / Flashcards buttons bypass this entirely -- this only
runs when the student types something instead of clicking a button.

Six intents:
- quiz        → generate MCQ quiz from paper
- summary     → summarize paper topics
- flashcards  → generate Anki-style term/definition revision cards
- knowledge   → explain a concept / answer an exam question using web search
                + LLM intrinsic knowledge (math, code, theorems, definitions)
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

# Math / numerical problem keywords — these need web-augmented answers,
# NOT paper-grounded QA (the paper only has questions, not solutions).
MATH_KEYWORDS = [
    "solve", "calculate", "compute", "find the value", "find the",
    "evaluate", "integrate", "differentiate", "derive", "prove",
    "proof", "simplify", "factorise", "factorize", "expand",
    "numerical", "formula for", "equation",
]

# Code / algorithm keywords — same reasoning: need real knowledge, not paper text.
CODE_KEYWORDS = [
    "write a program", "write code", "write an algorithm",
    "implement", "algorithm for", "pseudocode", "code for",
    "program to", "function to", "write a function",
    "flowchart", "data structure",
]

# Questions asking for concept explanations / exam answers — should use
# web search + intrinsic knowledge, NOT be grounded in the paper text.
_KNOWLEDGE_PATTERNS = re.compile(
    r"^(what is|what are|what do you mean|what does|define |explain |how does|how do|why is|why are"
    r"|describe |tell me about|give me|can you explain|difference between|compare |contrast "
    r"|answer q\d|ans q\d|solve q\d|write (a |an |short |long |brief )?note"
    r"|state the|state and |enlist|list the|advantages of|disadvantages of"
    r"|types of|applications of|uses of|working of|principle of|concept of)",
    re.IGNORECASE,
)

_STOPWORDS = {
    "about", "above", "after", "again", "against", "also", "been", "before", "being",
    "below", "between", "both", "cannot", "could", "does", "doing", "down", "during",
    "each", "from", "further", "have", "having", "here", "into", "itself", "more",
    "most", "myself", "other", "ought", "ours", "ourselves", "over", "same", "should",
    "some", "such", "than", "that", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "under", "until", "very",
    "were", "what", "when", "where", "which", "while", "with", "would", "your",
    "yours", "yourself", "yourselves", "tell", "give", "show", "find",
}


def route_intent(user_text: str, paper_text: str = "") -> str:
    """Route user query to an intent handler.

    If paper_text is supplied and user_text shares no meaningful words (lowercase,
    ignoring stopwords and words < 4 letters) with paper_text in the final fallback,
    routes to 'knowledge' instead of 'qa'.
    """
    text = user_text.strip().lower()
    if any(word in text for word in QUIZ_KEYWORDS):
        return "quiz"
    if any(word in text for word in SUMMARY_KEYWORDS):
        return "summary"
    # Check flashcards before the knowledge pattern so "give me flashcards"
    # isn't swallowed by the broad "give me" knowledge trigger.
    if any(word in text for word in FLASHCARD_KEYWORDS):
        return "flashcards"
    # Math and code questions need web search — route to knowledge path.
    if any(word in text for word in MATH_KEYWORDS):
        return "knowledge"
    if any(word in text for word in CODE_KEYWORDS):
        return "knowledge"
    if _KNOWLEDGE_PATTERNS.match(user_text.strip()):
        return "knowledge"

    # Final fallback: if paper_text is provided, check for shared meaningful words
    if paper_text and paper_text.strip():
        q_words = {
            w for w in re.findall(r"\b[a-z]{4,}\b", text)
            if w not in _STOPWORDS
        }
        p_words = set(re.findall(r"\b[a-z]{4,}\b", paper_text.lower()))
        if q_words and not (q_words & p_words):
            return "knowledge"

    return "qa"
