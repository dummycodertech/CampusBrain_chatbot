"""
Tests for combined multi-paper PDF splitting and multi-file subject aggregation
across Predictor, Mock Paper, and Top 5 Topics.
"""
from pathlib import Path
from unittest.mock import patch

try:
    import fitz
except ImportError:
    import pymupdf as fitz

from components.action_buttons import _get_papers_for_action
from generation.mock_paper import build_mock_paper
from generation.predictor import find_repeated_questions
from ingestion.cache_writer import ingest_local_paper, ingest_paper
from storage.cache_store import CacheStore, split_paper_pages


def test_combined_5_page_pdf_splits_into_5_papers(tmp_path):
    """A 5-page merged PYQ PDF should split into 5 sub-papers with distinct IDs/labels."""
    db_file = tmp_path / "merged.db"
    pdf_file = tmp_path / "electrical_science_merged.pdf"

    pages_content = [
        (
            "END TERM EXAMINATION\nJANUARY 2024\n"
            "Paper Code: ES-101\nSubject: Electrical Science\n"
            "Time: 3 Hours\nMaximum Marks: 75\nNote: Attempt any five questions.\n"
            "Q1. State and prove Thevenin theorem with an example. [10M]"
        ),
        (
            "END TERM EXAMINATION\n"
            "Exam Roll No: ________\nSubject: Electrical Science\n"
            "Maximum Marks: 75\nNote: Attempt all questions from Part A.\n"
            "Q1. Explain Norton equivalent circuit and superposition theorem. [10M]"
        ),
        (
            "MID TERM EXAMINATION\nAPRIL 2024\n"
            "B.Tech Semester 1\nSubject: Electrical Science\nMax. Marks: 30\n"
            "Q1. Derive the condition for maximum power transfer in DC circuits. [10M]"
        ),
        (
            "END TERM EXAMINATION\nJUNE 2024\n"
            "Paper Code: ES-101\nSubject: Electrical Science\nMaximum Marks: 75\n"
            "Note: Attempt any five questions.\n"
            "Q1. State and prove Thevenin theorem for linear bilateral networks. [10M]"
        ),
        (
            "END TERM EXAMINATION\nJULY 2023\n"
            "Exam Roll No: ________\nSubject: Electrical Science\nMaximum Marks: 75\n"
            "Q1. Explain resonance in series RLC circuit and derive quality factor. [10M]"
        ),
    ]

    doc = fitz.open()
    for text in pages_content:
        p = doc.new_page()
        p.insert_text((40, 50), text)
    doc.save(str(pdf_file))
    doc.close()

    store = CacheStore(db_path=db_file)
    with patch("ingestion.cache_writer.CacheStore", return_value=store):
        ingest_local_paper(
            paper_id="merged_es_5",
            pdf_path=pdf_file,
            year="Uploaded",
            known_subjects=["Electrical Science"],
        )

    sub_papers = store.get_subject_papers("Electrical Science")
    assert len(sub_papers) == 5
    assert [p[1] for p in sub_papers] == [
        "Jan 2024",
        "Paper 2",
        "Mid Apr 2024",
        "Jun 2024",
        "Jul 2023",
    ]
    assert len({p[0] for p in sub_papers}) == 5

    # Also verify _get_papers_for_action works even if subject fell back to 'General'
    action_papers = _get_papers_for_action(
        store,
        sub="General",
        current_paper_id="merged_es_5",
        paper_text=store.get_paper_text("merged_es_5") or "",
    )
    assert len(action_papers) == 5


def test_single_multi_page_paper_does_not_split():
    """A normal 2-page exam paper with P.T.O. or PART B continuation must stay 1 paper."""
    page_rows = [
        (
            1,
            "END TERM EXAMINATION MAY 2024\n"
            "Exam Roll No: ____\nSubject: Data Structures\nMaximum Marks: 75\n"
            "Q1. Define linked list and its types. [5M]\n"
            "Q2. Convert infix expression to postfix. [10M]\nP.T.O.",
        ),
        (
            2,
            "PART B\nPaper Code: ETCS-209\n"
            "Q3. Explain AVL tree rotations with diagrams. [15M]\n"
            "Q4. Write Dijkstra shortest path algorithm. [15M]",
        ),
    ]
    splits = split_paper_pages("single_ds", page_rows, stored_year="2024")
    assert len(splits) == 1
    assert splits[0][0] == "single_ds"
    assert splits[0][1] == "2024"


def test_multiple_url_1_page_papers_group_by_explicit_subject(tmp_path):
    """Opening multiple 1-page PDFs with URL subject param (unlisted in JSON) groups them."""
    db_file = tmp_path / "url_1p.db"

    def make_pdf_bytes(text: str) -> bytes:
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((40, 50), text)
        data = doc.tobytes()
        doc.close()
        return data

    pdf1 = make_pdf_bytes(
        "END TERM JAN 2024\nExam Paper\n"
        "Q1. State and explain Kirchhoff voltage law and Kirchhoff current law with neat circuit diagrams. [10M]"
    )
    pdf2 = make_pdf_bytes(
        "MID TERM APR 2024\nExam Paper\n"
        "Q1. State and explain Kirchhoff voltage law and Kirchhoff current law with circuit diagrams. [10M]"
    )

    store = CacheStore(db_path=db_file)
    with patch("ingestion.cache_writer.CacheStore", return_value=store), \
         patch("ingestion.cache_writer.fetch_pdf_bytes", side_effect=[pdf1, pdf2]):
        ingest_paper(
            paper_id="es_jan_2024",
            pdf_url="https://example.com/jan2024.pdf",
            year="2024",
            branch="IT",
            semester="1",
            subject="Electrical Science",
        )
        ingest_paper(
            paper_id="es_apr_2024",
            pdf_url="https://example.com/apr2024.pdf",
            year="2024",
            branch="IT",
            semester="1",
            subject="Electrical Science",
        )

    papers = store.get_subject_papers("Electrical Science")
    assert len(papers) == 2

    repeated = find_repeated_questions(papers)
    assert len(repeated) == 1
    assert repeated[0]["count"] == 2


def test_mock_paper_recognizes_multiple_papers_in_same_year():
    """Mock paper should not emit 'Only 1 paper was available' when >=2 distinct papers exist."""
    tagged = [
        (
            "pid#p1",
            "2024",
            [
                {
                    "q_no": "Q1",
                    "text": "Explain Thevenin theorem with an example circuit.",
                    "marks": 5,
                    "topic": "Network Theorems",
                }
            ],
        ),
        (
            "pid#p2",
            "2024",
            [
                {
                    "q_no": "Q1",
                    "text": "Explain Norton theorem with an example circuit.",
                    "marks": 5,
                    "topic": "Network Theorems",
                }
            ],
        ),
    ]
    mock = build_mock_paper(tagged, structure=[{"section": "Section A", "marks": 5, "count": 2}], seed=42)
    assert not any("Only 1 paper was available" in w for w in mock["warnings"])


def test_find_repeated_questions_matches_rephrased_and_cluttered_questions():
    """Rephrased PYQs with UNIT/asterisk clutter should still match across papers."""
    papers = [
        (
            "p1",
            "Jan 2024",
            "Q1. State and explain Norton's theorem. Show that Thevenin's and Norton's theorems are dual to each other. **** --- UNIT-II [5M]",
        ),
        (
            "p2",
            "Jun 2024",
            "Q1. Explain Norton theorem and show duality between Thevenin and Norton theorems. [10M]",
        ),
    ]
    repeated = find_repeated_questions(papers)
    assert len(repeated) == 1
    assert repeated[0]["count"] == 2
    assert "****" not in repeated[0]["text"]


def test_ensure_tagged_continues_after_empty_page(tmp_path):
    """If one sub-paper has zero extracted questions, ensure_tagged must still tag remaining papers."""
    from generation.topic_tagger import ensure_tagged, normalize_label
    from storage.cache_store import CacheStore

    assert normalize_label("Thevenin's Theorem", ["Thevenin Theorem"]) == "Thevenin Theorem"

    store = CacheStore(db_path=tmp_path / "ensure.db")
    papers = [
        ("p1", "Mar 2025", "Q1. Write a Java program to demonstrate multithreading using Runnable interface. [10M]"),
        ("p2", "Mar 2025", "Blank"),  # no extractable questions
        ("p3", "Apr 2024", "Q1. Explain exception handling with try, catch, and finally blocks in Java. [10M]"),
    ]
    with patch("generation.topic_tagger.CacheStore", return_value=store), \
         patch("generation.topic_tagger.quota_ok", return_value=True), \
         patch(
             "generation.topic_tagger.generate_text",
             side_effect=['{"1": "Multithreading"}', '{"1": "Exception Handling"}'],
         ):
        res = ensure_tagged(papers, "Programming in Java", max_new=6)

    tagged_ok = [r for r in res if r[2]]
    assert len(tagged_ok) == 2

