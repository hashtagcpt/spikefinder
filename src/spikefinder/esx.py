"""Core Lenstar A-scan I/O and SpikeFinder math, ported from LenstarSpikeFinder.exe (C#/WPF).

Original behaviour reproduced here (see docs/ESX_FORMAT.md):
  * SCANDATA blobs are zlib streams of BIG-endian float32 (App.UncompressScanData, SwitchEndian=true).
  * Per-eye average over all ASCANs flagged USED  (CollectiveExamData.Averages).
  * Display curve = max(0, log2(mean)) ** 1.5       (CollectiveExamData.DisplayAverages).
  * Marker X = sample index; marker Y = *linear* average at that index (not the display curve).
  * Rise = avg[end] - avg[start]; run = end - start; slope = rise / run;  AUC = sum(avg[a:b]).
  * OPL (pixels) = RPE_X - 1000.

ESX files are XML (<EYESUITE>) exported from Heidelberg/Haag-Streit EyeSuite.
"""
from __future__ import annotations

import base64
import os
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

# Marker definitions (CurveEditorControl.cs). index -> (name, optional)
PHAKIC_MARKERS = [
    ("Cornea/Aqueous", False),
    ("Aqueous/Lens Baseline", False),
    ("Aqueous/Capsule", False),
    ("Capsule/Cortex", False),
    ("Cortex/Nucleus", False),
    ("Anterior Nucleus Nadir", False),
    ("Posterior Nucleus Nadir", False),
    ("Nucleus/Cortex", False),
    ("Cortex/Capsule", False),
    ("Capsule/Vitreous", False),
    ("Lens/Vitreous Baseline", False),
    ("Retina", True),
    ("RPE", False),
]
PSEUDOPHAKIC_MARKERS = [
    ("Cornea/Aqueous", False),
    ("Anterior IOL", True),
    ("Posterior IOL", True),
    ("Anterior Vitreous Face", True),
    ("Retina", True),
    ("RPE", False),
]

OPL_REFERENCE_SAMPLE = 1000  # "Total OPL in pixels (RPE X - 1000)"


def decode_scandata(b64_or_bytes, n_samples: int | None = None) -> np.ndarray:
    """zlib -> big-endian float32. Zeros stay zero (matches the C# `if (num != 0)`)."""
    raw = base64.b64decode(b64_or_bytes) if isinstance(b64_or_bytes, str) else b64_or_bytes
    arr = np.frombuffer(zlib.decompress(raw), dtype=">f4").astype(np.float64)
    if n_samples is not None and len(arr) != n_samples:
        # C# reads exactly scan_length floats; keep the same contract but don't crash on mismatch.
        arr = arr[:n_samples] if len(arr) > n_samples else np.pad(arr, (0, n_samples - len(arr)))
    return arr


def display_curve(avg: np.ndarray) -> np.ndarray:
    """CollectiveExamData.DisplayAverages: max(0, log2(avg)) ** 1.5."""
    with np.errstate(divide="ignore", invalid="ignore"):
        l = np.log2(avg)
    l = np.where(np.isfinite(l), l, 0.0)
    return np.maximum(0.0, l) ** 1.5


@dataclass
class EyeScans:
    """All used A-scans of one eye in one exam. Only a running sum is kept (a 300 MB .esx holds ~1000 scans)."""
    eye: str                      # 'OD' / 'OS'
    ascans: list[np.ndarray] = field(default_factory=list)   # filled only when load_esx(keep_ascans=True)
    used_flags: list[bool] = field(default_factory=list)
    meas_mode: int | None = None
    lenstar_result: dict | None = None   # device's own BIOMETRYRESULT (dimensions, cursors)
    _sum: np.ndarray | None = None
    _n: int = 0

    def add(self, arr: np.ndarray, keep: bool = False) -> None:
        if self._sum is None:
            self._sum = np.zeros(len(arr), dtype=np.float64)
        if len(arr) != len(self._sum):          # C# threw on mismatched lengths; we skip the odd scan instead
            return
        self._sum += arr
        self._n += 1
        if keep:
            self.ascans.append(arr)

    @property
    def n(self) -> int:
        return self._n

    @property
    def average(self) -> np.ndarray:
        return self._sum / max(self._n, 1)

    @property
    def display(self) -> np.ndarray:
        return display_curve(self.average)

    @property
    def device_cursors(self) -> dict[int, float]:
        """Lenstar's own cursor positions {element: sample}. 1=cornea 4=lens front 5=lens back 6=retina 7=RPE (chick)."""
        out = {}
        for c in (self.lenstar_result or {}).get("cursors", []):
            try:
                out[int(float(c["CURSORELEMENT"]))] = float(c["SCANPOS"])
            except (KeyError, ValueError):
                pass
        return out


@dataclass
class Exam:
    name: str            # PATIENT/NAME   (animal id in the lab data, e.g. '13151')
    firstname: str
    birthday: str
    timestamp: str       # EXAMINATION@timestamp
    eyes: dict[str, EyeScans] = field(default_factory=dict)
    source: str = ""

    @property
    def subject_hint(self) -> str:
        """'animal_likely' | 'human_likely' | 'unknown' (see privacy.py). A hint only."""
        from .privacy import subject_hint
        return subject_hint(self.name, self.firstname, self.birthday, self.timestamp)

    def display_id(self, show_identifiers: bool = False) -> str:
        from .privacy import display_id
        return display_id(self.name, self.firstname, self.birthday, self.subject_hint, show_identifiers)


def _txt(e, tag, default=""):
    c = e.find(tag)
    return (c.text or "").strip() if c is not None and c.text else default


class EsxError(Exception):
    """Raised for files that are not readable EyeSuite exports."""


def load_esx(path: str, only_used: bool = True, keep_ascans: bool = False, progress=None) -> list[Exam]:
    """Stream-parse an EyeSuite .esx export into Exam objects (one per <EXAMINATION>).

    Uses iterparse and clears big elements (images, A-scans) as soon as they are decoded, so 300 MB files need
    only a few hundred MB of RAM. Keeps only A-scans flagged USED unless only_used=False.
    progress(fraction) is called now and then (0..1) so a GUI can show a bar.
    """
    exams: list[Exam] = []
    name = first = bday = ""
    exam: Exam | None = None
    es: EyeScans | None = None
    stack: list[str] = []
    size = max(os.path.getsize(path), 1)
    count = 0
    try:
        with open(path, "rb") as fh:
            for ev, el in ET.iterparse(fh, events=("start", "end")):
                if ev == "start":
                    stack.append(el.tag)
                    if el.tag == "EXAMINATION":
                        exam = Exam(name, first, bday, el.get("timestamp", ""), source=path)
                    elif el.tag == "MEASUREMENT" and exam is not None:
                        eye = el.get("eye", "?")
                        es = exam.eyes.setdefault(eye, EyeScans(eye))
                    continue
                stack.pop()
                parent = stack[-1] if stack else ""
                tag = el.tag
                if parent == "PATIENT" and tag in ("NAME", "FIRSTNAME", "BIRTHDAY"):
                    txt = (el.text or "").strip()
                    if tag == "NAME":
                        name = txt
                    elif tag == "FIRSTNAME":
                        first = txt
                    else:
                        bday = txt
                elif tag == "ASCAN" and es is not None:
                    used = _txt(el, "USED") == "true"
                    if used or not only_used:
                        n = int(_txt(el, "SCANLENGTH") or 0) or None
                        arr = decode_scandata(_txt(el, "SCANDATA"), n)
                        es.add(arr, keep=keep_ascans)
                        if keep_ascans:
                            es.used_flags.append(used)
                    el.clear()
                    count += 1
                    if progress and count % 25 == 0:
                        progress(min(fh.tell() / size, 1.0))
                elif tag == "BIOMETRYRESULT" and es is not None:
                    es.lenstar_result = parse_biometry_result(el)
                    el.clear()
                elif tag in ("KERIMAGE", "FULLIMAGE", "KERATOMRESULT") and parent == "MEASUREMENT":
                    el.clear()
                elif tag == "EXAMINATION" and exam is not None:
                    exam.eyes = {k: v for k, v in exam.eyes.items() if v.n > 0}
                    if exam.eyes:
                        exams.append(exam)
                    exam = None
                    el.clear()
    except ET.ParseError as e:
        if not exams:
            raise EsxError(f"{os.path.basename(path)}: not a readable .esx file ({e})") from e
        # truncated file: keep the complete exams read so far
    if progress:
        progress(1.0)
    return exams



def parse_biometry_result(br) -> dict:
    out = {"quality": _txt(br, "QUALITY"), "used": _txt(br, "USED"), "scanlength": _txt(br, "SCANLENGTH"),
           "dimensions": [], "cursors": []}
    sd = br.find("SCANDATA")
    if sd is not None and sd.text:
        out["scan"] = decode_scandata(sd.text.strip(), int(out["scanlength"] or 0) or None)
    for d in br.findall("DIMENSION"):
        out["dimensions"].append({k: _txt(d, k) for k in ("ELEMENT", "DIMVALUE", "USED", "QUALITY", "WARNINGIDS")})
    for c in br.findall("CURSOR"):
        out["cursors"].append({k: _txt(c, k) for k in ("CURSORELEMENT", "SCANPOS", "VALUE", "QUALITY", "WARNINGIDS")})
    return out


# ---- SpikeFinder feature math (CurveEditorControl.cs) ---------------------------------------
def spike(avg: np.ndarray, a: int, b: int) -> dict:
    rise = float(avg[b] - avg[a]); run = float(b - a)
    return {"rise": rise, "run": run, "slope": rise / run if run else float("nan")}


def auc(avg: np.ndarray, a: int, b: int) -> float:
    return float(np.sum(avg[a:b]))


def phakic_features(avg: np.ndarray, m: list[int | None]) -> dict:
    """m = 13 marker sample indices (PHAKIC_MARKERS order; Retina may be None/-1)."""
    f = {}
    f["AqueousCapsule"] = spike(avg, m[1], m[2])
    f["CapsuleCortex_ant"] = spike(avg, m[1], m[3])
    f["CortexNucleus_ant"] = spike(avg, m[4], m[5])
    f["NucleusCortex_post"] = spike(avg, m[6], m[7])
    f["CortexCapsule_post"] = spike(avg, m[8], m[10])
    f["CapsuleVitreous_post"] = spike(avg, m[9], m[10])
    f["AnteriorCortexAUC"] = auc(avg, m[1], m[5])
    f["PosteriorCortexAUC"] = auc(avg, m[6], m[10])
    f["NucleusAUC"] = auc(avg, m[5], m[6])
    f["OPL"] = m[12] - OPL_REFERENCE_SAMPLE
    return f
