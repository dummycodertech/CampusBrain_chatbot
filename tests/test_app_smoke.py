"""
Smoke tests for app.py in upload mode (no URL query params).

Uses streamlit.testing.v1.AppTest to run the full app entry-point.
Verifies the app reaches the landing page without raising an exception,
and that a file-upload element is present on the page.

Run with:
    pytest tests/test_app_smoke.py -v
"""
import sys
import pathlib
import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_dummy_key_for_smoke_test")


def _get_apptest():
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("streamlit.testing.v1 not available (need Streamlit >= 1.18)")
    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=30)
    at.run()
    return at


def test_app_starts_in_upload_mode():
    """App must render the upload landing page without raising an exception.

    In upload mode (no query params) the app renders a hero page then calls
    st.stop() waiting for a file -- that surfaces as a clean stop, not an error.
    """
    at = _get_apptest()
    assert not at.exception, (
        f"app.py raised an exception in upload mode:\n{at.exception}"
    )


def test_app_upload_mode_has_upload_element():
    """The landing page must contain a file-upload widget (any element type).

    In Streamlit 1.38 the file_uploader renders as an 'UnknownElement' in the
    test harness but it IS present in at.main.  We detect it by checking that
    the main block contains at least one element beyond the text-only Markdown
    nodes (i.e. a widget element of any concrete or unknown type).

    If st.testing ever adds direct .file_uploader support we can tighten this.
    """
    at = _get_apptest()

    # Count non-Markdown elements (the uploader, glass-panel containers, etc.)
    try:
        from streamlit.testing.v1.element_tree import Markdown
        non_text = [e for e in at.main if not isinstance(e, Markdown)]
    except ImportError:
        non_text = list(at.main)

    assert len(non_text) >= 1, (
        "Expected at least one non-Markdown element (file uploader / widget) "
        f"on the landing page, but found only: {[type(e).__name__ for e in at.main]}"
    )
