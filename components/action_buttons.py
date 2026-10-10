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
from generation.flashcards import generate_flashcards
from generation.topic_heatmap import generate_topic_heatmap
from generation.answer_checker import check_answer
from services.llm_client import LLMUnavailableError


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


def _render_top_topics(paper_text: str, subject: str = "") -> None:
    """Render top 5 topics with exact questions and marks across past papers."""
    import re
    import pandas as pd
    from storage.cache_store import CacheStore
    from generation.topic_questions import top_topics_with_questions

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "🏆 Top 5 Topics & Past Questions</p>",
        unsafe_allow_html=True,
    )

    store = CacheStore()
    papers = []
    if subject and subject.strip() and subject.lower() != "unknown":
        papers = store.get_subject_papers(subject)

    # Fallback to current paper if no subject papers found in cache
    if not papers and paper_text and paper_text.strip():
        m = re.search(r"20\d{2}", paper_text[:1000])
        curr_year = m.group(0) if m else "Uploaded"
        papers = [("current", curr_year, paper_text)]

    if len(papers) == 1:
        st.info("ℹ️ Only 1 paper available; open more years of this subject to see trends.")

    with st.spinner("Extracting top recurring topics and past questions..."):
        try:
            top_topics = top_topics_with_questions(papers, n=5, per_topic=4)
        except Exception as e:
            st.error(f"Could not extract top topics: {e}")
            return

    if not top_topics:
        st.warning("No questions could be matched to recurring topics in available papers.")
        return

    for t in top_topics:
        topic_name = t.get("topic", "Topic")
        count = t.get("count", 0)
        total_marks = t.get("total_marks", 0)
        years_list = t.get("years", [])
        years_str = ", ".join(str(y) for y in years_list) if years_list else "Recent"
        expander_title = f"{topic_name} · asked {count}× · {total_marks} marks · {years_str}"

        with st.expander(expander_title, expanded=False):
            q_rows = []
            for q in t.get("questions", []):
                q_rows.append({
                    "Year": q.get("year", ""),
                    "Q.No": q.get("q_no", ""),
                    "Marks": q.get("marks", 0),
                    "Question": q.get("text", ""),
                })
            if q_rows:
                df = pd.DataFrame(q_rows)
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.write("No questions available for this topic.")


def _render_predictor(paper_text: str, subject: str = "") -> None:
    """Render exam predictor: ranked topic table and repeated past questions."""
    import re
    import pandas as pd
    from storage.cache_store import CacheStore
    from generation.predictor import predict_topics, find_repeated_questions
    from generation.topic_questions import _year_num

    store = CacheStore()
    papers = []
    if subject and subject.strip() and subject.lower() != "unknown":
        papers = store.get_subject_papers(subject)

    # If no subject papers found in cache, check current paper
    if not papers and paper_text and paper_text.strip():
        m = re.search(r"20\d{2}", paper_text[:1000])
        curr_year = m.group(0) if m else "Uploaded"
        papers = [("current", curr_year, paper_text)]

    if len(papers) < 2:
        st.info("Open at least 2 years of this subject for predictions")
        return

    # Extract all distinct years
    all_years = []
    for p in papers:
        y_str = str(p[1]) if len(p) > 1 else ""
        m = re.search(r"20\d{2}", y_str)
        yr_clean = m.group(0) if m else y_str
        if yr_clean and yr_clean not in all_years:
            all_years.append(yr_clean)
    all_years.sort(key=_year_num, reverse=True)

    selected_years = st.multiselect(
        "Select years for prediction:",
        options=all_years,
        default=all_years,
    )

    if not selected_years or len(selected_years) < 2:
        st.info("Open at least 2 years of this subject for predictions")
        return

    filtered_papers = [
        p for p in papers
        if any(str(yr) in str(p[1]) for yr in selected_years)
    ]

    if len(filtered_papers) < 2:
        st.info("Open at least 2 years of this subject for predictions")
        return

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "🎯 Likely topics (heuristic, not a guarantee)</p>",
        unsafe_allow_html=True,
    )

    with st.spinner("Analysing multi-year exam trends..."):
        try:
            topic_preds = predict_topics(filtered_papers)
            repeat_questions = find_repeated_questions(filtered_papers)
        except Exception as e:
            st.error(f"Could not compute predictions: {e}")
            return

    # 1. Ranked table of topics (Topic | Score | Years | Due?)
    topic_rows = []
    for t in topic_preds:
        topic_rows.append({
            "Topic": t.get("topic", ""),
            "Score": t.get("score", 0.0),
            "Years": ", ".join(t.get("years", [])),
            "Due?": "🔥 Yes" if t.get("due") else "—",
        })

    if topic_rows:
        df_topics = pd.DataFrame(topic_rows)
        st.dataframe(df_topics, use_container_width=True, hide_index=True)
    else:
        st.write("No distinct topic signals found in selected papers.")

    # 2. List of repeated questions with their years
    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.0rem; margin-top:1rem; margin-bottom:0.5rem;">'
        "🔁 Repeated Questions Across Years</p>",
        unsafe_allow_html=True,
    )

    if repeat_questions:
        q_rows = []
        for q in repeat_questions:
            q_rows.append({
                "Years Asked": ", ".join(q.get("years", [])),
                "Marks": q.get("marks", 0),
                "Question": q.get("text", ""),
            })
        df_q = pd.DataFrame(q_rows)
        st.dataframe(df_q, use_container_width=True, hide_index=True)
    else:
        st.write("No repeated questions found across the selected years.")


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

def render_action_buttons(paper_text: str, subject: str = "") -> None:
    st.markdown(
        '<div style="font-family:\'Space Grotesk\', sans-serif; color:var(--text-secondary); '
        'margin-bottom: 0.5rem; text-transform:uppercase; letter-spacing:1px; font-size:0.8rem;">'
        "Controls</div>",
        unsafe_allow_html=True,
    )

    # ── Row 1: core actions ───────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    paper_id = st.session_state.get("current_paper_id", "")

    with col1:
        c1, c2 = st.columns([3, 2])
        btn_summary = c1.button("📝 Summarize", use_container_width=True)
        regen_summary = c2.button("Regenerate", key="regen_summary", use_container_width=True, help="Regenerate summary (bypass cache)")
        if btn_summary or regen_summary:
            bypass = bool(regen_summary)
            if not paper_text or len(paper_text.strip()) < 100:
                st.warning(
                    "⚠️ **Not enough text was extracted from this paper** to generate a summary.\n\n"
                    "This can happen when the subject has very few papers or the PDF is mostly images/diagrams. "
                    "Try opening the paper directly to verify the text was captured."
                )
            else:
                spinner_msg = "Regenerating summary..." if bypass else "Summarizing..."
                with st.spinner(spinner_msg):
                    summary = summarize_paper(paper_text, paper_id=paper_id, bypass_cache=bypass)
                # Cache for heatmap reuse
                st.session_state["cached_summary"] = summary
                st.session_state.messages.append(
                    {"role": "assistant", "content": summary, "type": "text"}
                )
                st.session_state.show_heatmap = False
                st.session_state.show_top_topics = False
                st.session_state.show_predictor = False
                st.session_state.show_checker = False
                st.rerun()

    with col2:
        c1, c2 = st.columns([3, 2])
        btn_quiz = c1.button("🧠 Quiz Me", use_container_width=True)
        regen_quiz = c2.button("Regenerate", key="regen_quiz", use_container_width=True, help="Regenerate quiz (bypass cache)")
        if btn_quiz or regen_quiz:
            bypass = bool(regen_quiz)
            if not paper_text or len(paper_text.strip()) < 100:
                st.warning(
                    "⚠️ **Not enough text was extracted from this paper** to generate a quiz.\n\n"
                    "This can happen when the subject has very few papers or the PDF is mostly images/diagrams. "
                    "Try opening the paper directly to verify the text was captured."
                )
            else:
                spinner_msg = "Regenerating quiz..." if bypass else "Building quiz..."
                with st.spinner(spinner_msg):
                    try:
                        quiz = generate_quiz(paper_text, paper_id=paper_id, bypass_cache=bypass)
                    except Exception as _qe:
                        st.error(f"Could not generate quiz: {_qe}")
                        quiz = None
                if quiz:
                    st.session_state.messages.append(
                        {"role": "assistant", "content": quiz, "type": "quiz"}
                    )
                    st.session_state.show_heatmap = False
                    st.session_state.show_top_topics = False
                    st.session_state.show_predictor = False
                    st.session_state.show_checker = False
                    st.rerun()

    with col3:
        c1, c2 = st.columns([3, 2])
        btn_flashcards = c1.button("🃏 Flashcards", use_container_width=True)
        regen_flashcards = c2.button("Regenerate", key="regen_flashcards", use_container_width=True, help="Regenerate flashcards (bypass cache)")
        if btn_flashcards or regen_flashcards:
            bypass = bool(regen_flashcards)
            if not paper_text or len(paper_text.strip()) < 100:
                st.warning(
                    "⚠️ **Not enough text was extracted from this paper** to generate flashcards.\n\n"
                    "This can happen when the subject has very few papers or the PDF is mostly images/diagrams. "
                    "Try opening the paper directly to verify the text was captured."
                )
            else:
                spinner_msg = "Regenerating flashcards..." if bypass else "Generating flashcards..."
                with st.spinner(spinner_msg):
                    try:
                        cards = generate_flashcards(paper_text, paper_id=paper_id, bypass_cache=bypass)
                    except Exception as _fe:
                        st.error(f"Could not generate flashcards: {_fe}")
                        cards = None
                if cards:
                    st.session_state.messages.append(
                        {"role": "assistant", "content": cards, "type": "flashcards"}
                    )
                    st.session_state.show_heatmap = False
                    st.session_state.show_top_topics = False
                    st.session_state.show_predictor = False
                    st.session_state.show_checker = False
                    st.rerun()

    with col4:
        if st.button("🗑 Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.show_heatmap = False
            st.session_state.show_top_topics = False
            st.session_state.show_predictor = False
            st.session_state.show_checker = False
            st.rerun()

    st.markdown("<div style='margin-bottom: 0.4rem;'></div>", unsafe_allow_html=True)

    # ── Row 2: analytics & tools ──────────────────────────────────────────────
    col4, col5, col6, col7, col8 = st.columns(5)

    with col4:
        if st.button("📊 Topic Heatmap", use_container_width=True):
            st.session_state.show_heatmap = not st.session_state.get("show_heatmap", False)
            st.session_state.show_top_topics = False
            st.session_state.show_predictor = False
            st.session_state.show_checker = False

    with col5:
        if st.button("🏆 Top 5 Topics", use_container_width=True):
            st.session_state.show_top_topics = not st.session_state.get("show_top_topics", False)
            st.session_state.show_heatmap = False
            st.session_state.show_predictor = False
            st.session_state.show_checker = False

    with col6:
        if st.button("🎯 Exam Predictor", use_container_width=True):
            st.session_state.show_predictor = not st.session_state.get("show_predictor", False)
            st.session_state.show_heatmap = False
            st.session_state.show_top_topics = False
            st.session_state.show_checker = False

    with col7:
        if st.button("✅ Check Answer", use_container_width=True):
            st.session_state.show_checker = not st.session_state.get("show_checker", False)
            st.session_state.show_heatmap = False
            st.session_state.show_top_topics = False
            st.session_state.show_predictor = False

    with col8:
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

    if st.session_state.get("show_top_topics"):
        st.markdown("---")
        _render_top_topics(paper_text, subject=subject)

    if st.session_state.get("show_predictor"):
        st.markdown("---")
        _render_predictor(paper_text, subject=subject)

    if st.session_state.get("show_checker"):
        st.markdown("---")
        _render_answer_checker(paper_text)

    st.markdown("---")
