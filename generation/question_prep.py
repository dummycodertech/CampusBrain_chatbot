"""
Question preparation and sanitisation engine for Campus Brain.

Prepares and cleans exam question text extracted from PYQ papers:
- Normalises OCR in question labels (e.g. Ql -> Q1)
- Strips exam header/footer boilerplate and instructions
- Splits and cleans question text, removing marks tokens and stray symbols
- Tracks hierarchical question numbers (e.g. Q9(a))

No Streamlit dependencies.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from generation.topic_heatmap import extract_marks, split_into_questions

QUESTION_VERBS = {
    "explain", "define", "what", "differentiate", "describe",
    "write", "derive", "discuss", "list", "state", "compare",
    "draw", "calculate", "find", "why", "how",
}

STRAY_CHARS = set(";:'‘’~|_,")

BOILERPLATE_PATTERNS = [
    r"p\.?t\.?o\.?",
    r"please write your exam roll",
    r"exam roll(?: no)?",
    r"end term examination",
    r"paper code",
    r"maximum marks",
    r"time\s*:\s*\d+",
    r"note\s*:\s*attempt",
    r"attempt\s+(?:any|five|all)",
    r"select\s+one\s+question",
]
_BP_REGEX = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)
_CUT_REGEX = re.compile(r"(?i)(?:p\.?t\.?o\.?|exam roll|end term|paper code)")
_INST_REGEX = re.compile(
    r"(?i)(?:short\s*(?:answer\s*)?questions?|compulsory|instructions?|note:|\b\d+\s*[x*×]\s*\d+\s*=\s*\d+\b)"
)


def prepare_questions(text: str) -> List[Dict[str, Any]]:
    """Clean and split paper text into normalised question dictionaries.

    Returns:
        List of dicts with keys: 'q_no', 'text', 'marks'.
    """
    if not text or not text.strip():
        return []

    # a. Normalise OCR in labels before splitting: "Ql", "QI", "Q|" -> "Q1"
    raw_text = re.sub(r"(?i)\bQ[lI](?=[.:\s\)\d-]|$)", "Q1", text)
    raw_text = re.sub(r"(?i)Q\|(?=[.:\s\)\d-]|$)", "Q1", raw_text)

    # b. Remove boilerplate lines (case-insensitive)
    lines = raw_text.splitlines()
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append(line)
            continue
        # page-number-only lines: e.g. "1", "Page 2", "Page 1 of 3"
        if re.match(r"^(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?$", stripped, re.IGNORECASE):
            continue
        if _BP_REGEX.search(stripped):
            continue
        clean_lines.append(line)
    text_cleaned = "\n".join(clean_lines)

    # c. Split with existing split_into_questions
    raw_chunks = split_into_questions(text_cleaned)

    results: List[Dict[str, Any]] = []
    last_main = ""
    fallback_idx = 1

    for orig_chunk in raw_chunks:
        chunk = orig_chunk.strip()
        if not chunk:
            continue

        # c. Drop chunks that are instructions
        if _INST_REGEX.search(chunk) and len(chunk) < 150 and "?" not in chunk:
            if not any(re.search(rf"\b{re.escape(v)}\b", chunk, re.IGNORECASE) for v in QUESTION_VERBS):
                continue

        # Extract marks from the ORIGINAL chunk before cutting or stripping
        marks = extract_marks(orig_chunk)

        # b. Cut at first occurrence of P.T.O / Exam Roll / END TERM / Paper Code
        cut_m = _CUT_REGEX.search(chunk)
        if cut_m:
            chunk = chunk[:cut_m.start()].strip()

        if not chunk:
            continue

        # f. Question numbers: track last main question (Q1, Q2...); sub-parts -> Q9(a) or (a)
        m_both = re.match(
            r"^\s*Q\.?\s*(\d+)\s*[.\s]*\(([a-zA-Z])\)|^\s*(\d+)\s*[.\s]*\(([a-zA-Z])\)",
            chunk,
            re.IGNORECASE,
        )
        m_sub = re.match(
            r"^\s*(?:\(([a-zA-Z])\)|([a-zA-Z])[.)])",
            chunk,
            re.IGNORECASE,
        )
        m_main = re.match(
            r"^\s*(?:Q\.?\s*(\d+[a-zA-Z]?)|(\d+)[.)])",
            chunk,
            re.IGNORECASE,
        )

        if m_both:
            p_num = m_both.group(1) or m_both.group(3)
            letter = (m_both.group(2) or m_both.group(4)).lower()
            last_main = f"Q{p_num}"
            q_no = f"{last_main}({letter})"
        elif m_sub:
            letter = (m_sub.group(1) or m_sub.group(2)).lower()
            if last_main:
                q_no = f"{last_main}({letter})"
            else:
                q_no = f"({letter})"
        elif m_main:
            num = m_main.group(1) or m_main.group(2)
            last_main = f"Q{num}"
            q_no = last_main
        else:
            q_no = last_main if last_main else f"Q{fallback_idx}"

        # e. Clean text:
        # Strip leading label like "Q1(a)", "1.", "b)", "(a)", "Q.1"
        cleaned = re.sub(
            r"^\s*(?:Q\.?\s*\d+\s*[.\s]*(?:\([a-zA-Z\d]+\)|[a-zA-Z][.)])?|(?:\d+|[a-zA-Z])[.)]\s*|\([a-zA-Z\d]+\)\s*|Q\.?\s*\d+[a-zA-Z]?\s*)",
            "",
            chunk,
            flags=re.IGNORECASE,
        )

        # Remove marks tokens: [2], (5), [10M], "(6 marks)", 10 Marks
        cleaned = re.sub(
            r"(?:\[|\()\s*\d{1,2}\s*(?:marks?|m)?\s*(?:\]|\))|\b\d{1,2}\s*marks?\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        # Remove tokens made only of punctuation or stray OCR symbols (; : ' ‘ ’ ~ | _ ,)
        words = cleaned.split()
        filtered_words = []
        for w in words:
            if all(c in STRAY_CHARS for c in w):
                continue
            if not any(c.isalnum() for c in w) and not any(c in "?!" for c in w):
                continue
            filtered_words.append(w)
        cleaned = " ".join(filtered_words)

        # Collapse whitespace
        cleaned = " ".join(cleaned.split()).strip()

        # d. Drop chunks with fewer than 4 words or letters < 60% of non-space chars
        w_list = cleaned.split()
        if len(w_list) < 4:
            continue
        non_space = [c for c in cleaned if not c.isspace()]
        if not non_space:
            continue
        letters = [c for c in non_space if c.isalpha()]
        if len(letters) / len(non_space) < 0.60:
            continue

        # Cap at 450 characters, cutting at a sentence end if possible
        if len(cleaned) > 450:
            sub = cleaned[:451]
            last_punct = -1
            for p in (".", "?", "!"):
                pos = sub.rfind(p)
                if pos > last_punct and pos >= 100:
                    last_punct = pos
            if last_punct != -1:
                cleaned = sub[:last_punct + 1].strip()
            else:
                last_space = sub[:450].rfind(" ")
                cleaned = sub[:last_space].strip() if last_space > 200 else sub[:450].strip()

        results.append({
            "q_no": q_no,
            "text": cleaned,
            "marks": marks,
        })
        fallback_idx += 1

    return results
