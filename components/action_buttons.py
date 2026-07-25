"""Action chips styled like Stitch's bottom toolbar."""
import streamlit as st
from generation.summary import summarize_paper
from generation.quiz import generate_quiz


def render_action_buttons(paper_text: str) -> None:
    # Render as horizontal chip row inside a glass panel
    st.markdown('<div class="glass-panel">', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1, 1], gap="small")

    with col1:
        if st.button("📝  Summarize", use_container_width=True):
            with st.spinner("Summarizing..."):
                summary = summarize_paper(paper_text)
            st.session_state.messages.append({"role": "assistant", "content": summary, "type": "text"})
            st.rerun()

    with col2:
        if st.button("🧠  Quiz Me", use_container_width=True):
            with st.spinner("Building quiz..."):
                quiz = generate_quiz(paper_text)
            st.session_state.messages.append({"role": "assistant", "content": quiz, "type": "quiz"})
            st.rerun()

    with col3:
        if st.button("🗑  Clear", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
