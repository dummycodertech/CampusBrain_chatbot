"""
Action buttons for Campus Brain.

Buttons in order:
  Row 1: Summarize | Quiz Me | Clear Chat
  Row 2: Topic Heatmap | Answer Checker | Export Chat

Topic Heatmap and Answer Checker are rendered inline below the buttons via
session-state flags so they don't interfere with the chat history scroll.
"""
import io
import datetime
import streamlit as st
from generation.summary import summarize_paper
from generation.quiz import generate_quiz
from generation.topic_heatmap import generate_topic_heatmap
from generation.answer_checker import check_answer


# ── helpers ───────────────────────────────────────────────────────────────────

def _render_heatmap(paper_text: str) -> None:
    """Render the topic frequency bar chart + detail table."""
    with st.spinner("Analysing topic distribution..."):
        try:
            data = generate_topic_heatmap(paper_text)
        except Exception as e:
            st.error(f"Could not generate heatmap: {e}")
            return

    topics = data.get("topics", [])
    if not topics:
        st.warning("No topics extracted — try a different paper.")
        return

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "📊 Topic Frequency Heatmap</p>",
        unsafe_allow_html=True,
    )

    # Bar chart — st.bar_chart is zero-cost (pure frontend)
    import pandas as pd
    df = pd.DataFrame(topics).set_index("topic")

    # Show questions column as the bar chart (always present)
    chart_col = "questions"
    st.bar_chart(df[[chart_col]], height=280)

    # Detail table
    display_df = df[["questions", "marks", "description"]].rename(
        columns={"questions": "Questions", "marks": "Marks", "description": "What it covers"}
    )
    st.dataframe(display_df, use_container_width=True)


def _render_answer_checker(paper_text: str) -> None:
    """Render the answer checker input form."""
    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "✅ Answer Checker</p>",
        unsafe_allow_html=True,
    )
    with st.form("answer_checker_form", clear_on_submit=False):
        question_input = st.text_area(
            "Question you attempted",
            placeholder="Paste or type the exact exam question here…",
            height=90,
        )
        answer_input = st.text_area(
            "Your answer",
            placeholder="Write your answer here…",
            height=160,
        )
        submitted = st.form_submit_button("Grade my answer ✦", use_container_width=True)

    if submitted:
        if not question_input.strip() or not answer_input.strip():
            st.warning("Please fill in both the question and your answer.")
            return
        with st.spinner("Grading your answer..."):
            try:
                feedback = check_answer(paper_text, question_input, answer_input)
            except Exception as e:
                st.error(f"Could not grade answer: {e}")
                return
        # Push feedback into chat so it persists in history
        st.session_state.messages.append(
            {"role": "assistant", "content": feedback, "type": "text"}
        )
        st.session_state.show_checker = False
        st.rerun()


def _build_export_text() -> str:
    """Serialise the chat history to a plain-text string."""
    lines = [
        "Campus Brain — Chat Export",
        f"Exported: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        "",
    ]
    for msg in st.session_state.messages:
        role = "You" if msg["role"] == "user" else "Campus Brain"
        content = msg.get("content", "")

        # Pretty-print structured types
        if msg.get("type") == "quiz":
            quiz_lines = [f"{role}:", "  [Quiz]"]
            for i, q in enumerate(content.get("quiz", []), 1):
                quiz_lines.append(f"  Q{i}. {q['question']}")
                for opt in q["options"]:
                    quiz_lines.append(f"       {opt}")
                quiz_lines.append(f"       Answer: {q['correct_answer']}")
            lines.extend(quiz_lines)

        elif msg.get("type") == "flashcards":
            fc_lines = [f"{role}:", "  [Flashcards]"]
            for card in content.get("flashcards", []):
                fc_lines.append(f"  Term: {card['term']}")
                fc_lines.append(f"  Def:  {card['definition']}")
                fc_lines.append("")
            lines.extend(fc_lines)

        else:
            lines.append(f"{role}:")
            for line in str(content).splitlines():
                lines.append(f"  {line}")

        lines.append("")  # blank line between messages

    return "\n".join(lines)


# ── main renderer ─────────────────────────────────────────────────────────────

def render_action_buttons(paper_text: str) -> None:
    st.markdown(
        '<div style="font-family:\'Space Grotesk\', sans-serif; color:var(--text-secondary); '
        'margin-bottom: 0.5rem; text-transform:uppercase; letter-spacing:1px; font-size:0.8rem;">'
        "Controls</div>",
        unsafe_allow_html=True,
    )

    # ── Row 1: core actions ───────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("📝 Summarize", use_container_width=True):
            with st.spinner("Summarizing..."):
                summary = summarize_paper(paper_text)
            st.session_state.messages.append(
                {"role": "assistant", "content": summary, "type": "text"}
            )
            st.session_state.show_heatmap = False
            st.session_state.show_checker = False
            st.rerun()

    with col2:
        if st.button("🧠 Quiz Me", use_container_width=True):
            with st.spinner("Building quiz..."):
                quiz = generate_quiz(paper_text)
            st.session_state.messages.append(
                {"role": "assistant", "content": quiz, "type": "quiz"}
            )
            st.session_state.show_heatmap = False
            st.session_state.show_checker = False
            st.rerun()

    with col3:
        if st.button("🗑 Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.show_heatmap = False
            st.session_state.show_checker = False
            st.rerun()

    st.markdown("<div style='margin-bottom: 0.4rem;'></div>", unsafe_allow_html=True)

    # ── Row 2: new features ───────────────────────────────────────────────────
    col4, col5, col6 = st.columns(3)

    with col4:
        if st.button("📊 Topic Heatmap", use_container_width=True):
            st.session_state.show_heatmap = not st.session_state.get("show_heatmap", False)
            st.session_state.show_checker = False

    with col5:
        if st.button("✅ Check Answer", use_container_width=True):
            st.session_state.show_checker = not st.session_state.get("show_checker", False)
            st.session_state.show_heatmap = False

    with col6:
        if st.session_state.get("messages"):
            export_bytes = io.BytesIO(_build_export_text().encode("utf-8"))
            st.download_button(
                label="💾 Export Chat",
                data=export_bytes,
                file_name=f"campus_brain_chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
                help="Download the full conversation as a .txt file",
            )
        else:
            st.button(
                "💾 Export Chat",
                disabled=True,
                use_container_width=True,
                help="Start a conversation first to enable export.",
            )

    # ── Inline panels (toggled by buttons above) ──────────────────────────────
    if st.session_state.get("show_heatmap"):
        st.markdown("---")
        _render_heatmap(paper_text)

    if st.session_state.get("show_checker"):
        st.markdown("---")
        _render_answer_checker(paper_text)

    st.markdown("---")
