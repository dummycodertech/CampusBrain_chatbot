"""
Action buttons for Campus Brain.

Buttons in order:
  Row 1: Summarize | Quiz Me | Flashcards | Clear Chat
  Row 2: Topic Heatmap | Top 5 Topics | Exam Predictor | Check Answer | Export Chat
  Row 3: Mock Paper

Panels are rendered inline below the buttons via session-state flags.
"""
import io
import datetime
import streamlit as st
from generation.summary import summarize_paper
from generation.quiz import generate_quiz
from generation.flashcards import generate_flashcards
from generation.answer_checker import check_answer
from services.llm_client import LLMUnavailableError


# ── helpers ───────────────────────────────────────────────────────────────────

def _render_heatmap(paper_text: str, subject: str = "") -> None:
    """Render the topic frequency bar chart + detail table."""
    import pandas as pd
    from storage.cache_store import CacheStore
    from generation.topic_tagger import tag_paper_topics
    from generation.topic_heatmap import build_heatmap_from_rows

    store = CacheStore()
    paper_id = st.session_state.get("current_paper_id", "")
    sub = (subject or "").strip()
    if not sub or sub.lower() == "unknown":
        if paper_id:
            sub = store.get_paper_subject(paper_id) or ""
    if not sub or sub.lower() == "unknown":
        sub = "General"

    with st.spinner("Detecting topics (once per paper)..."):
        try:
            rows, used_llm = tag_paper_topics(paper_id, sub, paper_text)
        except Exception as e:
            st.error(f"Could not generate heatmap: {e}")
            return

    if not used_llm:
        from generation.topic_tagger import get_last_notice
        notice = get_last_notice(paper_id) or "AI topic detection was unavailable. Try again in a minute."
        st.warning(notice)
        return

    data = build_heatmap_from_rows(rows)
    topics = data.get("topics", [])
    if not topics:
        st.warning("No topics extracted — try a different paper.")
        return

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "📊 Topic Frequency Heatmap</p>",
        unsafe_allow_html=True,
    )
    st.caption("Topics are detected by AI once per paper and then saved, so repeat views are free.")

    df = pd.DataFrame(topics).set_index("topic")
    chart_col = "questions"
    st.bar_chart(df[[chart_col]], height=280)

    display_df = df[["questions", "marks", "description"]].rename(
        columns={"questions": "Questions", "marks": "Marks", "description": "What it covers"}
    )
    st.dataframe(display_df, use_container_width=True)


def _render_top_topics(paper_text: str, subject: str = "") -> None:
    """Render top 5 topics with exact questions and marks across past papers."""
    import re
    import pandas as pd
    from storage.cache_store import CacheStore
    from generation.topic_tagger import ensure_tagged, tag_paper_topics
    from generation.topic_questions import top_topics_from_rows

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "🏆 Top 5 Topics & Past Questions</p>",
        unsafe_allow_html=True,
    )
    st.caption("Topics are detected by AI once per paper and then saved, so repeat views are free.")

    store = CacheStore()
    current_paper_id = st.session_state.get("current_paper_id", "")
    sub = (subject or "").strip()
    if not sub or sub.lower() == "unknown":
        if current_paper_id:
            sub = store.get_paper_subject(current_paper_id) or ""
    if not sub or sub.lower() == "unknown":
        sub = "General"

    papers = store.get_subject_papers(sub) if sub != "General" else []
    if not papers and paper_text and paper_text.strip():
        m = re.search(r"20\d{2}", paper_text[:1000])
        curr_year = m.group(0) if m else "Uploaded"
        papers = [(current_paper_id or "current", curr_year, paper_text)]

    if len(papers) == 1:
        st.info("ℹ️ Only 1 paper available; open more years of this subject to see trends.")

    total_p = len(papers)
    prog = st.progress(0, text=f"Tagging paper 1 of {total_p}...")
    def _on_prog(done, total):
        pct = done / total if total > 0 else 1.0
        prog.progress(pct, text=f"Tagging paper {done} of {total}...")

    tagged_results = ensure_tagged(papers, sub, max_new=6, on_progress=_on_prog)
    prog.empty()

    tagged = [(year, rows) for pid, year, rows, used_llm in tagged_results if rows]
    untagged_count = sum(1 for pid, year, rows, used_llm in tagged_results if not rows)
    if untagged_count > 0:
        st.info(f"{untagged_count} paper(s) not tagged yet; click again to continue.")

    if not tagged:
        with st.spinner("Detecting topics (once per paper)..."):
            cur_rows, cur_used = tag_paper_topics(current_paper_id or "current", sub, paper_text)
        if not cur_used:
            st.warning("AI topic detection was unavailable, so these topics may be incomplete. Try again in a minute.")
        if cur_rows:
            m = re.search(r"20\d{2}", paper_text[:1000])
            curr_year = m.group(0) if m else "Uploaded"
            tagged = [(curr_year, cur_rows)]
        else:
            return

    try:
        top_topics = top_topics_from_rows(tagged, n=5, per_topic=4)
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
    from collections import Counter
    from storage.cache_store import CacheStore
    from generation.topic_tagger import ensure_tagged
    from generation.predictor import predict_topics_from_rows, find_repeated_questions
    from generation.topic_questions import _year_num

    store = CacheStore()
    current_paper_id = st.session_state.get("current_paper_id", "")
    sub = (subject or "").strip()
    if not sub or sub.lower() == "unknown":
        if current_paper_id:
            sub = store.get_paper_subject(current_paper_id) or ""
    if not sub or sub.lower() == "unknown":
        sub = "General"

    papers = store.get_subject_papers(sub) if sub != "General" else []
    if not papers and paper_text and paper_text.strip():
        m = re.search(r"20\d{2}", paper_text[:1000])
        curr_year = m.group(0) if m else "Uploaded"
        papers = [(current_paper_id or "current", curr_year, paper_text)]

    if len(papers) < 2:
        st.info("Open at least 2 papers of this subject for predictions")
        return

    year_counts = Counter(str(p[1]) for p in papers)

    paper_labels = []
    label_to_paper = {}
    for p in papers:
        pid = str(p[0])
        yr = str(p[1])
        label = yr if year_counts[yr] == 1 else f"{yr} · {pid[:6]}"
        paper_labels.append(label)
        label_to_paper[label] = p

    selected_labels = st.multiselect(
        "Select papers for prediction:",
        options=paper_labels,
        default=paper_labels,
    )

    if not selected_labels or len(selected_labels) < 2:
        st.info("Open at least 2 papers of this subject for predictions")
        return

    filtered_papers = [label_to_paper[lbl] for lbl in selected_labels if lbl in label_to_paper]

    if len(filtered_papers) < 2:
        st.info("Open at least 2 papers of this subject for predictions")
        return

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "🎯 Likely topics (heuristic, not a guarantee)</p>",
        unsafe_allow_html=True,
    )
    st.caption("Topics are detected by AI once per paper and then saved, so repeat views are free.")

    total_p = len(filtered_papers)
    prog = st.progress(0, text=f"Tagging paper 1 of {total_p}...")
    def _on_prog(done, total):
        pct = done / total if total > 0 else 1.0
        prog.progress(pct, text=f"Tagging paper {done} of {total}...")

    tagged_results = ensure_tagged(filtered_papers, sub, max_new=6, on_progress=_on_prog)
    prog.empty()

    tagged = [(pid, year, rows) for pid, year, rows, used_llm in tagged_results if rows]
    untagged_count = sum(1 for pid, year, rows, used_llm in tagged_results if not rows)
    if untagged_count > 0:
        st.info(f"{untagged_count} paper(s) not tagged yet; click again to continue.")

    if len(tagged) < 2:
        st.info("Open at least 2 papers of this subject for predictions")
        return

    with st.spinner("Analysing multi-year exam trends..."):
        try:
            topic_preds = predict_topics_from_rows(tagged)
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


def _render_mock_paper(paper_text: str, subject: str = "") -> None:
    """Render the Mock Paper panel: structure editor, generate, download."""
    import re
    import pandas as pd
    from storage.cache_store import CacheStore
    from generation.topic_tagger import ensure_tagged, get_last_notice
    from generation.mock_paper import (
        DEFAULT_STRUCTURE, build_mock_paper, to_text,
    )

    st.markdown(
        '<p style="color:#c4b5fd; font-weight:600; font-size:1.05rem; margin-bottom:0.5rem;">'
        "📄 Mock Paper Generator</p>",
        unsafe_allow_html=True,
    )
    st.caption("Built from real past questions, weighted by topic frequency. Not a prediction.")

    store = CacheStore()
    current_paper_id = st.session_state.get("current_paper_id", "")
    sub = (subject or "").strip()
    if not sub or sub.lower() == "unknown":
        if current_paper_id:
            sub = store.get_paper_subject(current_paper_id) or ""
    if not sub or sub.lower() == "unknown":
        sub = "General"

    papers = store.get_subject_papers(sub) if sub != "General" else []
    if not papers and paper_text and paper_text.strip():
        m = re.search(r"20\d{2}", paper_text[:1000])
        curr_year = m.group(0) if m else "Uploaded"
        papers = [(current_paper_id or "current", curr_year, paper_text)]

    if not papers:
        st.info("Open the heatmap or Top 5 first, or upload more papers of this subject.")
        return

    # Tag papers
    total_p = len(papers)
    prog = st.progress(0, text="Preparing topics...")
    def _on_prog(done, total):
        pct = done / total if total > 0 else 1.0
        prog.progress(pct, text=f"Tagging paper {done} of {total}...")

    tagged_results = ensure_tagged(papers, sub, max_new=6, on_progress=_on_prog)
    prog.empty()

    # Keep only entries with rows
    tagged = [(year, rows) for pid, year, rows, used_llm in tagged_results if rows]

    if not tagged:
        notice = None
        for pid, year, rows, used_llm in tagged_results:
            n = get_last_notice(pid)
            if n:
                notice = n
                break
        msg = notice or "No tagged questions yet. Open the heatmap or Top 5 first."
        st.info(msg)
        return

    # Structure editor
    st.markdown("**Paper structure** (edit rows as needed):")
    default_df = pd.DataFrame(DEFAULT_STRUCTURE)
    struct_df = st.data_editor(
        default_df,
        column_config={
            "section": st.column_config.TextColumn("Section"),
            "marks":   st.column_config.NumberColumn("Marks",  min_value=1, max_value=20, step=1),
            "count":   st.column_config.NumberColumn("Count",  min_value=1, max_value=15, step=1),
        },
        num_rows="dynamic",
        use_container_width=True,
        key="mock_structure_editor",
    )

    col_gen, col_shuf = st.columns([2, 1])
    with col_gen:
        generate_clicked = st.button("Generate Mock Paper", use_container_width=True)
    with col_shuf:
        shuffle_clicked = st.button("🔀 Shuffle", use_container_width=True)

    if shuffle_clicked:
        import random as _rnd
        st.session_state["mock_seed"] = _rnd.randint(0, 2**31)

    if generate_clicked or shuffle_clicked or st.session_state.get("mock_paper") is not None:
        if generate_clicked or shuffle_clicked:
            structure = struct_df.to_dict(orient="records") if struct_df is not None and not struct_df.empty else DEFAULT_STRUCTURE
            seed = st.session_state.get("mock_seed")
            paper = build_mock_paper(tagged, structure=structure, seed=seed)
            st.session_state["mock_paper"] = paper
        else:
            paper = st.session_state["mock_paper"]

        # Show warnings
        for w in paper.get("warnings", []):
            st.warning(w)

        # Render paper inline
        st.markdown(f"**Total Marks: {paper['total_marks']}**")
        global_n = 1
        for sec in paper.get("sections", []):
            st.markdown(f"**{sec['section']}** — {sec['marks']} marks each")
            for q in sec.get("questions", []):
                adj_note = " *(marks adjusted)*" if q.get("adjusted") else ""
                st.markdown(f"{global_n}. {q['text']}  `[{q['marks']} marks]`{adj_note}")
                global_n += 1

        # PDF download (with text fallback if reportlab missing)
        _pdf_ok = True
        try:
            from generation.mock_paper import to_pdf_bytes
            pdf_bytes = to_pdf_bytes(paper, title=f"Mock Paper — {sub}")
        except ImportError:
            _pdf_ok = False
            st.info("PDF export unavailable; using text export.")

        text_bytes = to_text(paper, title=f"Mock Paper — {sub}").encode("utf-8")

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            if _pdf_ok:
                st.download_button(
                    label="⬇ Download PDF",
                    data=pdf_bytes,
                    file_name="mock_paper.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.download_button(
                    label="⬇ Download Text",
                    data=text_bytes,
                    file_name="mock_paper.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
        with dl_col2:
            st.download_button(
                label="📋 Download Plain Text",
                data=text_bytes,
                file_name="mock_paper.txt",
                mime="text/plain",
                use_container_width=True,
            )


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
            st.session_state.show_mock = False
            st.session_state.pop("mock_paper", None)
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
            st.session_state.show_mock = False

    with col5:
        if st.button("🏆 Top 5 Topics", use_container_width=True):
            st.session_state.show_top_topics = not st.session_state.get("show_top_topics", False)
            st.session_state.show_heatmap = False
            st.session_state.show_predictor = False
            st.session_state.show_checker = False
            st.session_state.show_mock = False

    with col6:
        if st.button("🎯 Exam Predictor", use_container_width=True):
            st.session_state.show_predictor = not st.session_state.get("show_predictor", False)
            st.session_state.show_heatmap = False
            st.session_state.show_top_topics = False
            st.session_state.show_checker = False
            st.session_state.show_mock = False

    with col7:
        if st.button("✅ Check Answer", use_container_width=True):
            st.session_state.show_checker = not st.session_state.get("show_checker", False)
            st.session_state.show_heatmap = False
            st.session_state.show_top_topics = False
            st.session_state.show_predictor = False
            st.session_state.show_mock = False

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

    # ── Row 3: mock paper ─────────────────────────────────────────────────────
    st.markdown("<div style='margin-bottom: 0.4rem;'></div>", unsafe_allow_html=True)
    mock_col, _ = st.columns([1, 4])
    with mock_col:
        if st.button("📄 Mock Paper", use_container_width=True):
            st.session_state.show_mock = not st.session_state.get("show_mock", False)
            st.session_state.show_heatmap = False
            st.session_state.show_top_topics = False
            st.session_state.show_predictor = False
            st.session_state.show_checker = False

    # ── Inline panels (toggled by buttons above) ──────────────────────────────
    if st.session_state.get("show_heatmap"):
        st.markdown("---")
        _render_heatmap(paper_text, subject=subject)

    if st.session_state.get("show_top_topics"):
        st.markdown("---")
        _render_top_topics(paper_text, subject=subject)

    if st.session_state.get("show_predictor"):
        st.markdown("---")
        _render_predictor(paper_text, subject=subject)

    if st.session_state.get("show_checker"):
        st.markdown("---")
        _render_answer_checker(paper_text)

    if st.session_state.get("show_mock"):
        st.markdown("---")
        _render_mock_paper(paper_text, subject=subject)

    st.markdown("---")
