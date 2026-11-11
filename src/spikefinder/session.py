"""Data model shared by the CLI and the GUI: one EyeRecord per eye per exam, plus review persistence.

Review files are JSON, one per .esx (`<stem>.spikefinder.json`). They never contain names or birth dates: records are
keyed by the *safe* subject id (animal id as-is; anything human-likely/unknown is a short hash).
"""
from __future__ import annotations

import datetime as _dt
import json
import hashlib
import os
from dataclasses import dataclass, field

import numpy as np

from . import __version__
from .detect import Detection, MARKER_NAMES, Profile, detect, load_profile
from .esx import load_esx

STATUSES = ("auto", "edited", "confirmed")


@dataclass
class EyeRecord:
    source: str                 # .esx path
    exam_ts: str
    subject_key: str            # safe id (animal id or hash) -> used in files
    subject_label: str          # what the UI shows (== subject_key unless the user asked to show identifiers)
    hint: str                   # animal_likely | human_likely | unknown
    eye: str
    n_scans: int
    avg: np.ndarray
    cursors: dict
    detection: Detection
    x: np.ndarray               # current marker positions (13, NaN = absent)
    status: str = "auto"
    notes: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    device_results: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.subject_key}|{self.eye}|{self.exam_ts}"

    @property
    def flags(self) -> list[str]:
        return self.detection.flags

    @property
    def needs_review(self) -> bool:
        return self.status == "auto" and self.detection.needs_review

    def y_at(self, i: int):
        v = self.x[i]
        return float("nan") if np.isnan(v) else float(self.avg[int(v)])

    def set_marker(self, i: int, pos: float | None) -> None:
        new = np.nan if pos is None else float(np.clip(round(pos), 0, len(self.avg) - 1))
        old = self.x[i]
        if (np.isnan(new) and np.isnan(old)) or new == old:
            return
        self.x[i] = new
        if self.status != "confirmed":
            self.status = "edited"
        else:
            self.status = "edited"          # editing a confirmed eye invalidates the confirmation

    def reset(self) -> None:
        self.x = self.detection.x.copy()
        self.status = "auto"
        self.reviewed_at = ""

    def confirm(self, reviewer: str = "") -> None:
        self.status = "confirmed"
        self.reviewer = reviewer or self.reviewer
        self.reviewed_at = _dt.datetime.now().isoformat(timespec="seconds")


def process_file(path: str, profile: Profile | None = None, show_identifiers: bool = False, progress=None,
                 on_record=None) -> list[EyeRecord]:
    """Load an .esx, detect landmarks for each eye; returns the records (and calls on_record for each as it is made)."""
    profile = profile or load_profile()
    out: list[EyeRecord] = []
    for exam in load_esx(path, progress=progress):
        hint = exam.subject_hint
        safe = exam.display_id(False)
        label = exam.display_id(show_identifiers)
        for eye, es in sorted(exam.eyes.items()):
            avg = es.average
            det = detect(avg, es.n, hint, profile, es.device_cursors)
            rec = EyeRecord(path, exam.timestamp, safe, label, hint, eye, es.n, avg, es.device_cursors, det, det.x.copy())
            rec.device_results = es.device_results
            out.append(rec)
            if on_record:
                on_record(rec)
    return out


# ------------------------------------------------------------------ review persistence
def review_path(outdir: str, source: str) -> str:
    stem = os.path.splitext(os.path.basename(source))[0]
    token = hashlib.sha256(os.path.normcase(os.path.abspath(source)).encode()).hexdigest()[:12]
    return os.path.join(outdir, f"{stem}.{token}.spikefinder.json")


def _nan_to_none(a):
    return [None if np.isnan(v) else int(v) for v in a]


def save_review(records: list[EyeRecord], outdir: str, only_reviewed: bool = False) -> list[str]:
    """Write one review JSON per source file (only files with an edited/confirmed eye if only_reviewed)."""
    os.makedirs(outdir, exist_ok=True)
    by_src: dict[str, list[EyeRecord]] = {}
    for r in records:
        by_src.setdefault(r.source, []).append(r)
    written = []
    for src, recs in by_src.items():
        if only_reviewed and all(r.status == "auto" for r in recs):
            continue
        doc = {"spikefinder_version": __version__, "source_file": os.path.basename(src),
               "saved": _dt.datetime.now().isoformat(timespec="seconds"), "marker_names": MARKER_NAMES, "eyes": []}
        for r in recs:
            doc["eyes"].append({"key": r.key, "subject": r.subject_key, "eye": r.eye, "exam_timestamp": r.exam_ts,
                                "subject_hint": r.hint, "n_scans": r.n_scans, "profile": r.detection.profile,
                                "status": r.status, "reviewer": r.reviewer, "reviewed_at": r.reviewed_at, "notes": r.notes,
                                "flags": r.flags, "auto_x": _nan_to_none(r.detection.x), "x": _nan_to_none(r.x),
                                "auto_conf": [round(float(c), 3) for c in r.detection.conf]})
        p = review_path(outdir, src)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        os.replace(tmp, p)
        written.append(p)
    return written


def apply_review(records: list[EyeRecord], outdir: str) -> int:
    """Merge previously saved human edits into freshly detected records. Returns the number restored."""
    n = 0
    cache: dict[str, dict] = {}
    for r in records:
        p = review_path(outdir, r.source)
        if p not in cache:
            try:
                if not os.path.exists(p):
                    legacy = os.path.join(outdir, os.path.splitext(os.path.basename(r.source))[0] + ".spikefinder.json")
                    p = legacy
                with open(p, encoding="utf-8") as fh:
                    doc = json.load(fh)
                    cache[review_path(outdir, r.source)] = {e["key"]: e for e in doc.get("eyes", [])}
            except (OSError, ValueError):
                cache[review_path(outdir, r.source)] = {}
        e = cache[review_path(outdir, r.source)].get(r.key)
        if e and e.get("status") in ("edited", "confirmed") and len(e.get("x", [])) == 13:
            try:
                positions = np.array([np.nan if v is None else float(v) for v in e["x"]])
            except (ValueError, TypeError):
                continue
            if any(not np.isnan(v) and (not np.isfinite(v) or v < 0 or v >= len(r.avg) or v != int(v)) for v in positions):
                continue
            r.x = positions
            r.status, r.notes = e["status"], e.get("notes", "")
            r.reviewer, r.reviewed_at = e.get("reviewer", ""), e.get("reviewed_at", "")
            n += 1
    return n
