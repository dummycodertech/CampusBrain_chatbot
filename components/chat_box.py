"""Free-text chat input, routed through the keyword intent router."""
import streamlit as st
from router.intent_router import route_intent
from generation.qa import answer_question, knowledge_answer
from generation.summary import summarize_paper
from generation.quiz import generate_quiz
# Flashcards: renders term/definition pairs produced by generate_flashcards()
from generation.flashcards import generate_flashcards


def render_chat_box(paper_text: str) -> None:
    # Chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="🧠" if msg["role"] == "assistant" else "🙋"):
            if msg.get("type") == "quiz":
                _render_quiz(msg["content"])
            elif msg.get("type") == "flashcards":
                # Flashcard messages use a dedicated card-flip renderer
                _render_flashcards(msg["content"])
            else:
                st.markdown(msg["content"])

    # Empty state
    if not st.session_state.messages:
        st.markdown(
            """
            <div style="text-align:center; padding: 3rem 0; color: #3f3f46;">
                <div style="font-size: 2rem; margin-bottom: 0.5rem;">✦</div>
                <div style="font-size: 0.9rem; letter-spacing: 1px; text-transform: uppercase;">
                    Ask anything about this paper
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Input
    question = st.chat_input("Ask a question about this paper...")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question, "type": "text"})

    intent = route_intent(question)
    with st.spinner("Thinking..."):
        if intent == "quiz":
            content, msg_type = generate_quiz(paper_text), "quiz"
        elif intent == "summary":
            content, msg_type = summarize_paper(paper_text), "text"
        elif intent == "flashcards":
            # Route typed requests like "make flashcards" or "give me cards"
            content, msg_type = generate_flashcards(paper_text), "flashcards"
        elif intent == "knowledge":
            content, msg_type = knowledge_answer(question), "text"
        else:
            content, msg_type = answer_question(paper_text, question), "text"

    st.session_state.messages.append({"role": "assistant", "content": content, "type": msg_type})
    st.rerun()


def _render_quiz(quiz_data: dict) -> None:
    questions = quiz_data.get("quiz", [])
    st.markdown(
        f'<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:1rem;">'
        f'✦ Quiz — {len(questions)} Questions</p>',
        unsafe_allow_html=True,
    )
    for i, q in enumerate(questions, start=1):
        with st.expander(f"Q{i}.  {q['question']}", expanded=(i == 1)):
            for opt in q["options"]:
                st.markdown(f"- {opt}")
            st.markdown(
                f"""<div style="margin-top:0.8rem; padding: 0.8rem 1rem;
                    background: rgba(124,58,237,0.1); border-left: 2px solid #7c3aed;
                    border-radius: 8px; color: #c4b5fd; font-weight: 500;">
                    ✓ &nbsp;{q['correct_answer']}
                </div>""",
                unsafe_allow_html=True,
            )


def _render_flashcards(cards_data: dict) -> None:
    """Render flashcard term/definition pairs in an expandable card layout.

    Each card shows the term as the expander header (the 'question' side)
    and reveals the definition when opened (the 'answer' side), mimicking
    the physical act of flipping a revision card.
    """
    cards = cards_data.get("flashcards", [])
    st.markdown(
        f'<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:1rem;">'
        f'🃏 Flashcards — {len(cards)} Cards</p>',
        unsafe_allow_html=True,
    )
    for i, card in enumerate(cards, start=1):
        with st.expander(f"Card {i}:  {card['term']}", expanded=(i == 1)):
            st.markdown(
                f"""<div style="padding: 0.9rem 1rem;
                    background: rgba(124,58,237,0.08);
                    border-left: 2px solid #a78bfa;
                    border-radius: 8px;
                    color: #e4e4e7;
                    line-height: 1.65;
                    font-size: 0.95rem;">
                    {card['definition']}
                </div>""",
                unsafe_allow_html=True,
            )
