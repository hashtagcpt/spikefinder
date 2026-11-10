"""Parse hand-marked SpikeFinder export CSVs (the exe's "Dump" output; 58 columns, phakic block).

Positional layout (from MainWindow.DumpCsv in the decompiled exe). Many lab copies have the header row stripped or
extra title rows, so we parse by position and detect data rows by shape, not by header text.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass

from spikefinder.esx import PHAKIC_MARKERS

META = ["first", "last", "dob", "exam_date", "eye", "confidence", "total_scans"]
CONF = {"low": 0, "medium": 1, "high": 2, "skip": -1}

# column index of each marker's X (and Y) in the 58-col phakic row
_XY_START = 30
MARKER_COLS: dict[str, tuple[int, int | None]] = {}
for i, (name, _opt) in enumerate(PHAKIC_MARKERS[:11]):
    MARKER_COLS[name] = (_XY_START + 2 * i, _XY_START + 2 * i + 1)
MARKER_COLS["Retina"] = (52, None)
MARKER_COLS["RPE"] = (53, 54)
OPL_COL, NOTES_COL, MODE_COL = 55, 56, 57

_TS = re.compile(r"^\d{4}[./-]\d{2}[./-]\d{2}")


@dataclass
class LabelRow:
    first: str
    last: str          # animal id in lab data (e.g. '6654')
    dob: str
    exam_date: str     # 'YYYY.MM.DD HH:MM:SS' (matches ESX EXAMINATION timestamp, after normalisation)
    eye: str
    confidence: int | None
    total_scans: int | None
    x: dict[str, float | None]    # marker -> sample index
    y: dict[str, float | None]    # marker -> linear avg value at that index
    opl: float | None
    notes: str
    source: str = ""


def _f(s):
    try:
        v = float(s)
        return v
    except (TypeError, ValueError):
        return None


def parse_rows(rows: list[list[str]], source: str = "") -> list[LabelRow]:
    out = []
    for r in rows:
        if len(r) < 56:
            continue
        # data row: DOB-ish col 2 and exam date col 3 look like dates
        if not ((_TS.match(r[2].strip()) or r[2].strip() == "") and _TS.match(r[3].strip())):   # DOB may be blank (privacy exports)
            continue
        x, y = {}, {}
        for name, (cx, cy) in MARKER_COLS.items():
            x[name] = _f(r[cx]) if cx < len(r) else None
            y[name] = _f(r[cy]) if cy is not None and cy < len(r) else None
        conf = CONF.get(r[5].strip().lower())
        out.append(LabelRow(
            first=r[0].strip(), last=r[1].strip(), dob=r[2].strip(), exam_date=r[3].strip(), eye=r[4].strip(),
            confidence=conf, total_scans=int(_f(r[6])) if _f(r[6]) is not None else None,
            x=x, y=y, opl=_f(r[OPL_COL]), notes=r[NOTES_COL] if len(r) > NOTES_COL else "", source=source))
    return out


def load_label_csv(path: str) -> list[LabelRow]:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))
    return parse_rows(rows, source=path)


def norm_ts(ts: str) -> str:
    """Normalise '2016.05.31 12:37:24' / '2025.04.17-19:18:35-0' -> '2016-05-31 12:37:24'."""
    m = re.match(r"(\d{4})[./-](\d{2})[./-](\d{2})[ -T]?(\d{2}):(\d{2}):(\d{2})", ts.strip())
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}:{m[6]}" if m else ts.strip()
