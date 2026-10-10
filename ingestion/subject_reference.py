"""
Static, locally-maintained reference of expected subjects per branch+semester,
so ingestion never depends on the frontend supplying a subject array. Fill
data/subjects_by_semester.json from your official curriculum once -- it
doesn't change per upload, so there's no ongoing coordination cost.

If a branch+semester isn't mapped, ingestion falls back to open-ended
detection: OCR/regex still extracts whatever header text it finds, it just has
no canonical list to snap the naming to.
"""
import json
from pathlib import Path
from typing import List, Tuple, Optional

REFERENCE_PATH = Path(__file__).parent.parent / "data" / "subjects_by_semester.json"


def get_expected_subjects(branch: str, semester: str) -> List[str]:
    if not REFERENCE_PATH.exists():
        return []
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    return data.get(f"{branch}-{semester}", [])


def get_branches_and_semesters() -> Tuple[List[str], List[str]]:
    """Parse existing keys in subjects_by_semester.json (e.g. 'IT-3') into unique branches and semesters."""
    if not REFERENCE_PATH.exists():
        return [], []
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    branches: List[str] = []
    semesters: List[str] = []
    for key in data.keys():
        if key.startswith("_") or "-" not in key:
            continue
        b, s = key.split("-", 1)
        if b not in branches:
            branches.append(b)
        if s not in semesters:
            semesters.append(s)
    semesters.sort(key=lambda x: int(x) if x.isdigit() else x)
    return branches, semesters


def get_available_branches() -> List[str]:
    branches, _ = get_branches_and_semesters()
    return branches


def get_available_semesters(branch: Optional[str] = None) -> List[str]:
    if not branch or not REFERENCE_PATH.exists():
        _, semesters = get_branches_and_semesters()
        return semesters
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    semesters: List[str] = []
    for key in data.keys():
        if key.startswith("_") or "-" not in key:
            continue
        b, s = key.split("-", 1)
        if b == branch and s not in semesters:
            semesters.append(s)
    semesters.sort(key=lambda x: int(x) if x.isdigit() else x)
    return semesters
