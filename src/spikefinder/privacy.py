"""Subject-type heuristics and identifier hygiene.

The lab's .esx files are mostly chick eyes, but human exams may be mixed in. Human data are (a) personal data and
(b) anatomically different from the chick eyes this detector was validated on. So we:
  * guess whether an exam is animal- or human-like (never certain -> always shown as a hint, never silently trusted),
  * hide names/birth dates by default everywhere (GUI, CSV, JSON) and show a short hashed id for human-likely exams,
  * flag human-likely/unknown exams so the detector marks them "not validated" and forces human review.

Heuristics (any one is enough for 'human_likely'):
  - PATIENT/FIRSTNAME is non-empty, or NAME contains letters/spaces beyond a short alphanumeric animal id
  - age at exam > 2 years (chick DOB = days/weeks before exam; humans = years)
Animal-like: short id (digits, optional leading letter), no first name, age < 1 year.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

_ANIMAL_ID = re.compile(r"^[A-Za-z]?\d{3,6}[A-Za-z]?$")


def _parse_date(s: str):
    m = re.match(r"(\d{4})[./-](\d{2})[./-](\d{2})", (s or "").strip())
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def age_days(birthday: str, exam_timestamp: str):
    b, e = _parse_date(birthday), _parse_date(exam_timestamp)
    return None if b is None or e is None else (e - b).days


def subject_hint(name: str, firstname: str, birthday: str, exam_timestamp: str) -> str:
    """'animal_likely' | 'human_likely' | 'unknown'."""
    name, firstname = (name or "").strip(), (firstname or "").strip()
    age = age_days(birthday, exam_timestamp)
    if firstname:
        return "human_likely"
    if age is not None and age > 730:
        return "human_likely"
    if name and not _ANIMAL_ID.match(name):
        return "human_likely"
    if _ANIMAL_ID.match(name) and (age is None or age < 365):
        return "animal_likely"
    return "unknown"


def hashed_id(name: str, firstname: str, birthday: str) -> str:
    """Stable short pseudonym; the salt-free hash is for de-duplication, not strong anonymisation."""
    h = hashlib.sha256(f"{name}|{firstname}|{birthday}".encode("utf-8")).hexdigest()[:8]
    return f"H-{h}"


def display_id(name: str, firstname: str, birthday: str, hint: str, show_identifiers: bool = False) -> str:
    """Identifier safe to show/export. Animal ids are shown as-is; anything else is pseudonymised unless overridden."""
    if show_identifiers:
        return (f"{firstname} {name}".strip()) or "?"
    if hint == "animal_likely":
        return name
    return hashed_id(name, firstname, birthday)
