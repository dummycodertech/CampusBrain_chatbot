"""
Static, locally-maintained reference of expected subjects per branch+semester,
so ingestion never depends on the frontend supplying a subject array. Fill
data/subjects_by_semester.json from your official curriculum once -- it
doesn't change per upload, so there's no ongoing coordination cost.

If a branch+semester isn't mapped, ingestion falls back to open-ended
detection: Gemini still extracts whatever header text it finds, it just has
no canonical list to snap the naming to.
"""
import json
from pathlib import Path
from typing import List

REFERENCE_PATH = Path(__file__).parent.parent / "data" / "subjects_by_semester.json"


def get_expected_subjects(branch: str, semester: str) -> List[str]:
    if not REFERENCE_PATH.exists():
        return []
    data = json.loads(REFERENCE_PATH.read_text())
    return data.get(f"{branch}-{semester}", [])
