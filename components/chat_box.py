from __future__ import annotations

import html
import re
from typing import Optional, Tuple
import streamlit as st
from router.intent_router import route_intent
from generation.qa import answer_question, knowledge_answer
from generation.summary import summarize_paper
from generation.quiz import generate_quiz, is_fallback_quiz
# Flashcards: renders term/definition pairs produced by generate_flashcards()
from generation.flashcards import generate_flashcards


def _extract_letter_and_text(opt_str: str) -> Tuple[Optional[str], str]:
    """Extract option letter (e.g. 'A', 'B') and remaining text from an option string."""
    s = str(opt_str).strip()
    if not s:
        return None, ""
    m_single = re.match(r"^(?:option\s+)?\(?([A-Da-d])\)?$", s, re.IGNORECASE)
    if m_single:
        return m_single.group(1).upper(), ""
    m_prefix = re.match(r"^(?:option\s+)?(?:\(([A-Da-d])\)\s*|([A-Da-d])\s*[.):-]\s*)(.*)$", s, re.IGNORECASE)
    if m_prefix:
        letter = (m_prefix.group(1) or m_prefix.group(2)).upper()
        text = m_prefix.group(3).strip().lower()
        return letter, text
    return None, s.lower()


def check_quiz_answer(selected: str, correct: str) -> bool:
    if not selected or not correct:
        return False
    sel_letter, sel_text = _extract_letter_and_text(selected)
    cor_letter, cor_text = _extract_letter_and_text(correct)
    if sel_letter and cor_letter:
        return sel_letter == cor_letter
    return " ".join(sel_text.split()) == " ".join(cor_text.split())


def render_chat_box(paper_text: str) -> None:
    # Chat history
    for msg_idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"], avatar="🧠" if msg["role"] == "assistant" else "🙋"):
            if msg.get("type") == "quiz":
                _render_quiz(msg["content"], msg_idx=msg_idx, paper_text=paper_text)
            elif msg.get("type") == "flashcards":
                # Flashcard messages use a dedicated card-flip renderer
                _render_flashcards(msg["content"])
            else:
                if msg.get("scope") == "general":
                    st.markdown(
                        '<div class="scope-pill">ℹ️ Not related to your exam material, but here\'s an answer anyway.</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(msg["content"])

    # Empty state
    if not st.session_state.messages:
        st.markdown(
            '<div style="text-align:center; padding: 3rem 0; color: #3f3f46;"><div style="font-size: 2rem; margin-bottom: 0.5rem;">✦</div><div style="font-size: 0.9rem; letter-spacing: 1px; text-transform: uppercase;">Ask anything about this paper</div></div>',
            unsafe_allow_html=True,
        )

    # Input
    question = st.chat_input("Ask a question about this paper...")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question, "type": "text"})

    intent = route_intent(question, paper_text=paper_text)
    scope = None
    with st.spinner("Thinking..."):
        if intent == "quiz":
            try:
                content, msg_type = generate_quiz(paper_text), "quiz"
            except Exception as _qe:
                content = f"Sorry, I couldn't generate a quiz right now: {_qe}"
                msg_type = "text"
        elif intent == "summary":
            content, msg_type = summarize_paper(paper_text), "text"
        elif intent == "flashcards":
            # Route typed requests like "make flashcards" or "give me cards"
            content, msg_type = generate_flashcards(paper_text), "flashcards"
        elif intent == "knowledge":
            content, scope = knowledge_answer(question)
            msg_type = "text"
        else:
            content, msg_type = answer_question(paper_text, question), "text"

    assistant_msg = {"role": "assistant", "content": content, "type": msg_type}
    if scope:
        assistant_msg["scope"] = scope
    st.session_state.messages.append(assistant_msg)
    st.rerun()


def _render_quiz(quiz_data: dict, msg_idx: int = 0, paper_text: str = "") -> None:
    # 1. Fallback object handling
    if is_fallback_quiz(quiz_data):
        err_card = quiz_data.get("quiz", [{}])[0] if isinstance(quiz_data, dict) else {}
        err_msg = err_card.get("question", "⚠️ Quiz could not be generated from the AI response.")
        st.warning(err_msg)
        if st.button("🔄 Retry quiz", key=f"retry_quiz_{msg_idx}"):
            with st.spinner("Retrying quiz generation..."):
                try:
                    new_quiz = generate_quiz(paper_text, bypass_cache=True)
                    st.session_state.messages[msg_idx]["content"] = new_quiz
                    st.rerun()
                except Exception as e:
                    st.error(f"Retry failed: {e}")
        return

    questions = quiz_data.get("quiz", [])
    total = len(questions)

    # 2. State management keyed by message index
    state_key = f"quiz_state_{msg_idx}"
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            "checked": {},   # q_idx -> bool
            "answers": {},   # q_idx -> selected string
            "results": {},   # q_idx -> bool (is_correct)
        }
    q_state = st.session_state[state_key]

    correct_count = sum(1 for is_correct in q_state["results"].values() if is_correct)
    answered_count = len(q_state["checked"])

    # 3. Header and running score
    col_hdr1, col_hdr2 = st.columns([3, 2])
    with col_hdr1:
        st.markdown(
            f'<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.4rem;">'
            f'✦ Interactive Quiz — {html.escape(str(total))} Questions</p>',
            unsafe_allow_html=True,
        )
    with col_hdr2:
        st.markdown(
            f'<div style="text-align:right; font-weight:600; color:#a78bfa; font-size:1.0rem;">'
            f'Score: {html.escape(str(correct_count))} / {html.escape(str(total))}</div>',
            unsafe_allow_html=True,
        )

    # 4. Render questions
    for i, q in enumerate(questions, start=1):
        q_idx = i - 1
        st.markdown(f"**Q{i}. {q.get('question', '')}**")
        options = q.get("options", [])
        is_checked = q_state["checked"].get(q_idx, False)
        saved_answer = q_state["answers"].get(q_idx)

        current_idx = None
        if is_checked and saved_answer in options:
            current_idx = options.index(saved_answer)

        radio_key = f"quiz_radio_{msg_idx}_{q_idx}"
        selected = st.radio(
            f"Select answer for Q{i}:",
            options=options,
            index=current_idx,
            key=radio_key,
            disabled=is_checked,
            label_visibility="collapsed",
        )

        if not is_checked:
            if st.button("Check answer", key=f"check_btn_{msg_idx}_{q_idx}"):
                if selected is None:
                    st.warning("Please select an option before checking.")
                else:
                    is_correct = check_quiz_answer(selected, q.get("correct_answer", ""))
                    q_state["checked"][q_idx] = True
                    q_state["answers"][q_idx] = selected
                    q_state["results"][q_idx] = is_correct
                    st.rerun()
        else:
            is_correct = q_state["results"].get(q_idx, False)
            correct_ans = q.get("correct_answer", "")
            explanation = q.get("explanation", "")

            if is_correct:
                st.success(f"**Correct!** {correct_ans}")
            else:
                st.error(f"**Incorrect.** Correct answer: **{correct_ans}**")
            if explanation:
                st.caption(f"💡 {explanation}")

        st.markdown("<div style='margin-bottom: 0.7rem;'></div>", unsafe_allow_html=True)

    # 5. Final summary when all questions are answered
    if answered_count == total and total > 0:
        pct = int(round(correct_count / total * 100))
        st.metric(label="Final Score", value=f"{correct_count} / {total}", delta=f"{pct}%")
        if pct >= 70:
            msg = "🏆 **100%** — Perfect score! Outstanding mastery of these topics." if pct == 100 else f"🎉 **{pct}%** — Great job! Strong understanding of the core concepts."
            st.success(msg)
        elif pct >= 40:
            st.info(f"📚 **{pct}%** — Good effort! Revise the missed topics before the exam.")
        else:
            st.warning(f"💪 **{pct}%** — Keep practicing! Review the explanations and retry.")


def _render_flashcards(cards_data: dict) -> None:
    """Render flashcard term/definition pairs in an expandable card layout.

    Each card shows the term as the expander header (the 'question' side)
    and reveals the definition when opened (the 'answer' side), mimicking
    the physical act of flipping a revision card.
    """
    cards = cards_data.get("flashcards", [])
    st.markdown(
        f'<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:1rem;">'
        f'🃏 Flashcards — {html.escape(str(len(cards)))} Cards</p>',
        unsafe_allow_html=True,
    )
    for i, card in enumerate(cards, start=1):
        with st.expander(f"Card {i}:  {card['term']}", expanded=(i == 1)):
            def_esc = html.escape(str(card.get('definition', '')))
            st.markdown(
                f'<div style="padding: 0.9rem 1rem; background: rgba(124,58,237,0.08); border-left: 2px solid #a78bfa; border-radius: 8px; color: #e4e4e7; line-height: 1.65; font-size: 0.95rem;">{def_esc}</div>',
                unsafe_allow_html=True,
            )
