"""CSV exporters: a tidy per-eye table and the original SpikeFinder 58-column "Dump" format (for existing R scripts)."""
from __future__ import annotations

import csv
import re

import numpy as np

from ._exe_header import EXE_COLUMNS
from .detect import MARKER_NAMES
from .session import EyeRecord


def _fmt(v):
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else (int(v) if float(v).is_integer() else round(float(v), 4))


def write_tidy_csv(records: list[EyeRecord], path: str) -> None:
    """One row per eye. Columns: file, subject, eye, timestamp, hint, n_scans, status, needs_review, flags, profile,
    then <marker>_x / _y / _conf for each of the 13 markers. No names or birth dates are ever written."""
    cols = ["file", "subject", "eye", "exam_timestamp", "subject_hint", "n_scans", "status", "reviewer", "needs_review",
            "flags", "profile", "notes"]
    for n in MARKER_NAMES:
        cols += [f"{n}_x", f"{n}_y", f"{n}_conf"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in records:
            row = [r.source.replace("\\", "/").split("/")[-1], r.subject_key, r.eye, r.exam_ts, r.hint, r.n_scans, r.status,
                   r.reviewer, int(r.detection.needs_review and r.status == "auto"), ";".join(r.flags), r.detection.profile,
                   r.notes]
            for i in range(13):
                row += [_fmt(r.x[i]), _fmt(r.y_at(i)), _fmt(float(r.detection.conf[i]))]
            w.writerow(row)


def _exam_date(ts: str) -> str:
    m = re.match(r"(\d{4})[./-](\d{2})[./-](\d{2})[ -T]?(\d{2}):(\d{2}):(\d{2})", ts)
    return f"{m[1]}.{m[2]}.{m[3]} {m[4]}:{m[5]}:{m[6]}" if m else ts


def write_exe_csv(records: list[EyeRecord], path: str) -> int:
    """Original-format dump (phakic block, legacy marker names/columns so existing R scripts keep working).
    Slots 5/6 are the legacy "Anterior/Posterior Nucleus Nadir" columns but hold CHOROID and SCLERA (see detect.py).
    Markers that are not placed (e.g. lens-interior ones, which are not auto-placed) leave blanks in their columns and in any
    value derived from them. First Name / DOB are empty on purpose; Last Name carries the (safe) subject id.
    Confidence column: confirmed->High, edited->Medium, auto->Low (the original column was the operator's own confidence).
    Eyes without the core markers (cornea, lens front, lens back, RPE) are skipped; returns the number written.
    """
    n = 0
    conf_txt = {"confirmed": "High", "edited": "Medium", "auto": "Low"}
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write("PHAKIC EYES (PSEUDOPHAKIC EYES ARE ON THE BOTTOM)\n")
        w = csv.writer(fh)
        w.writerow(EXE_COLUMNS)
        for r in records:
            if np.isnan(r.x[[0, 2, 9, 12]]).any():
                continue
            have = lambda *idx: not any(np.isnan(r.x[i]) for i in idx)
            X = lambda i: int(r.x[i])
            Y = lambda i: float(r.avg[X(i)])

            def spike(a, b):
                if not have(a, b):
                    return ["", "", ""]
                rise, run = Y(b) - Y(a), X(b) - X(a)
                return [rise, run, rise / run if run else ""]

            def auc(a, b):
                return float(np.sum(r.avg[X(a):X(b)])) if have(a, b) else ""

            # Legacy derived values (lens cortex/nucleus AUCs, spikes) assume slots 3-8 are LENS landmarks. In chick data slots
            # 5/6 hold choroid/sclera, so these are only meaningful when all lens-interior markers (3,4,7,8) were placed
            # AND slots 5/6 are lens-like; we blank them otherwise instead of exporting a misleading eye-wide sum.
            lens_ok = have(1, 2, 3, 4, 5, 6, 7, 8, 9, 10) and bool(r.x[5] < r.x[7])
            blank = ["", "", ""]
            ant, post, nuc = (auc(1, 5), auc(6, 10), auc(5, 6)) if lens_ok else ("", "", "")
            row = ["", r.subject_key, "", _exam_date(r.exam_ts), r.eye, conf_txt[r.status], r.n_scans, ant]
            if lens_ok:
                row += spike(1, 2) + spike(1, 3) + spike(4, 5) + [post] + spike(6, 7) + spike(8, 10) + spike(9, 10)
            else:
                row += blank * 3 + [post] + blank * 3
            total = (ant + post) if "" not in (ant, post) else ""
            row += [total, nuc, total / nuc if total != "" and nuc not in ("", 0) else ""]
            for i in range(11):
                row += [X(i), Y(i)] if have(i) else ["", ""]
            row += [X(11) if have(11) else -1, X(12), Y(12), X(12) - 1000, r.notes, "PHAKIC"]
            assert len(row) == len(EXE_COLUMNS), (len(row), len(EXE_COLUMNS))
            w.writerow(row)
            n += 1
    return n
