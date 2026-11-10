"""Rule-based landmark detector for Lenstar chick-eye A-scans.

Works on the DISPLAY curve (max(0, log2(avg))**1.5), lightly smoothed. Anchor peaks (cornea, lens front, lens back, RPE
complex) are found with search windows; the four lens-interior markers are placed by fractions between the lens-front and
lens-back anchors, and the two foot/baseline markers by walking down the peak flanks. A *profile* (JSON, fitted on
hand-labelled data) supplies the fractions, per-marker bias corrections, per-marker
reliability (share of held-out labels within 25 samples) and plausible geometry ranges.

IMPORTANT scope: validated only on chick eyes (Lenstar LS900, 2015-2020 labels). Anything else (human-likely or unknown
subjects, geometry outside the chick ranges) is flagged NOT_VALIDATED / REVIEW and its confidences are capped, so a person
must check it.

Marker order (esx.PHAKIC_MARKERS):
 0 Cornea/Aqueous 1 Aqueous/Lens Baseline 2 Aqueous/Capsule 3 Capsule/Cortex 4 Cortex/Nucleus 5 CHOROID (legacy "Anterior
 Nucleus Nadir") 6 SCLERA (legacy "Posterior Nucleus Nadir") 7 Nucleus/Cortex 8 Cortex/Capsule 9 Capsule/Vitreous
 10 Lens/Vitreous Baseline 11 Retina 12 RPE.  Slots 3,4,7,8 (lens interior) are not auto-placed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from .esx import PHAKIC_MARKERS, display_curve

# Names used in this app. Slots 5 and 6 are called "Anterior/Posterior Nucleus Nadir" in the ORIGINAL SpikeFinder, but in the
# chick data they were used for the CHOROID and SCLERA (confirmed by the lab); the legacy names stay only in the
# original-format CSV export (export.write_exe_csv) so existing R scripts keep working.
LEGACY_NAMES = [n for n, _ in PHAKIC_MARKERS]
MARKER_NAMES = list(LEGACY_NAMES)
MARKER_NAMES[5], MARKER_NAMES[6] = "Choroid", "Sclera"
LENS_FRACTION_MARKERS = (3, 4, 7, 8)          # lens-interior markers (Capsule/Cortex, Cortex/Nucleus, Nucleus/Cortex, Cortex/Capsule)
# The chick lens is not a model for the human lens, and these markers are subjective shoulders, so they are NOT placed
# automatically (left empty for manual placement) unless a profile/caller asks for it. Listed as a limitation in the README.
ANCHOR_MARKERS = (0, 2, 9, 12)                # peak-like, detected directly
DEFAULT_PROFILE = "chick_2017_2020"
# marker -> device cursor element (chick, Lenstar LS900): used only as a cross-check
CURSOR_FOR_MARKER = {0: 1, 2: 4, 9: 5, 11: 6, 12: 7}
CURSOR_TOL = {0: 40, 2: 200, 9: 40, 11: 400, 12: 40}


# ------------------------------------------------------------------ profiles
@dataclass
class Profile:
    name: str = "uncalibrated"
    description: str = "no calibration: fractions 0.5, no bias, no reliability"
    fractions: dict[int, float] = field(default_factory=dict)
    bias: dict[int, float] = field(default_factory=dict)             # added to the raw position (samples)
    reliability: dict[int, float] = field(default_factory=dict)      # P(|err|<=25 samples), held out
    ranges: dict[str, list[float]] = field(default_factory=dict)     # geometry limits (samples), chick plausibility check
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "Profile":
        ik = lambda m: {int(k): float(v) for k, v in (m or {}).items()}
        return cls(d.get("name", "?"), d.get("description", ""), ik(d.get("fractions")), ik(d.get("bias")),
                   ik(d.get("reliability")), d.get("ranges", {}), d.get("meta", {}))

    def to_json(self) -> dict:
        return {"name": self.name, "description": self.description, "fractions": self.fractions, "bias": self.bias,
                "reliability": self.reliability, "ranges": self.ranges, "meta": self.meta}


def list_profiles() -> list[str]:
    try:
        return sorted(p.name[:-5] for p in resources.files("spikefinder.profiles").iterdir() if p.name.endswith(".json"))
    except Exception:
        return []


def load_profile(name: str | None = None) -> Profile:
    name = name or DEFAULT_PROFILE
    try:
        txt = resources.files("spikefinder.profiles").joinpath(f"{name}.json").read_text(encoding="utf-8")
        return Profile.from_json(json.loads(txt))
    except (FileNotFoundError, ModuleNotFoundError):
        return Profile()


# ------------------------------------------------------------------ anchor finding
def _foot_before(s: np.ndarray, peak: int, lo: int, frac: float = 0.15) -> int:
    """Walk left from a peak until the curve falls below baseline + frac*(peak-baseline)."""
    base = np.median(s[max(lo, peak - 600):peak]) if peak > lo else 0.0
    thr = base + frac * (s[peak] - base)
    i = peak
    while i > lo and s[i] > thr:
        i -= 1
    return i


def _foot_after(s: np.ndarray, peak: int, hi: int, frac: float = 0.15) -> int:
    base = np.median(s[peak:min(hi, peak + 600)])
    thr = base + frac * (s[peak] - base)
    i = peak
    while i < hi - 1 and s[i] > thr:
        i += 1
    return i


def find_anchors(avg: np.ndarray, smooth: int = 15) -> dict | None:
    d = display_curve(np.asarray(avg, float))
    s = uniform_filter1d(d, smooth)
    n = len(s)
    if n < 6000:
        return None
    ref = int(np.argmax(s[:2000]))                      # reference/probe peak ~ 1000
    w = slice(ref + 120, ref + 700)
    cornea = ref + 120 + int(np.argmax(s[w]))
    w0, w1 = cornea + 1200, cornea + 3200
    if w1 >= n:
        return None
    lens_front = w0 + int(np.argmax(s[w0:w1]))
    b0, b1 = lens_front + 2500, lens_front + 5500
    if b1 >= n:
        return None
    lens_back = b0 + int(np.argmax(s[b0:b1]))
    r0 = lens_back + 3000
    if r0 >= n - 500:
        return None
    rpe = r0 + int(np.argmax(s[r0:min(n, r0 + 12000)]))   # retina complex is at ~17-19k (lens back ~8k)
    pk, _ = find_peaks(s[r0:min(n, rpe + 2500)], prominence=0.08 * s[rpe])
    pk = pk + r0
    before = [p for p in pk if rpe - 1500 < p < rpe - 20]
    after = [p for p in pk if rpe + 20 < p < rpe + 2200]
    retina = before[0] if before else rpe - 400
    post = (after + [rpe + 350, rpe + 600])[:2]
    noise = float(np.median(s[rpe + 4000:min(n, rpe + 9000)])) if rpe + 4000 < n else 0.0
    return dict(s=s, ref=ref, cornea=cornea, lens_front=lens_front, lens_back=lens_back, rpe=rpe,
                retina=retina, post=post, n_post=len(after), noise=noise)


def raw_positions(avg: np.ndarray, fractions: dict[int, float] | None = None):
    """Uncorrected 13 positions + anchors dict (None, None if the anchor search fails)."""
    a = find_anchors(avg)
    if a is None:
        return None, None
    s = a["s"]
    p = np.full(13, np.nan)
    p[0] = a["cornea"]
    p[2] = a["lens_front"]
    p[1] = _foot_before(s, a["lens_front"], a["cornea"] + 300)
    p[9] = a["lens_back"]
    p[10] = _foot_after(s, a["lens_back"], a["rpe"] - 2000)
    span = p[9] - p[2]
    for m in LENS_FRACTION_MARKERS:
        p[m] = p[2] + (fractions or {}).get(m, 0.5) * span
    p[11] = a["retina"]
    p[12] = a["rpe"]
    p[5], p[6] = a["post"][0], a["post"][1]
    return p, a


# ------------------------------------------------------------------ full detection with confidence + QC flags
# DEVICE_DISAGREES is informational only: on the lab's labelled data the Lenstar device cursors were themselves off from the
# hand marks (by tens to thousands of samples) about as often as the detector was, so a disagreement is not evidence of error.
BLOCKING_FLAGS = {"ANCHOR_FAIL", "ORDER", "POSTERIOR_UNCERTAIN", "OUT_OF_RANGE_FOR_CHICK", "NOT_VALIDATED_SUBJECT", "SUBJECT_UNKNOWN", "FEW_SCANS"}


@dataclass
class Detection:
    x: np.ndarray                         # 13 sample positions (float, NaN = not found / removed)
    conf: np.ndarray                      # 13 confidences 0..1
    flags: list[str]
    profile: str
    subject_hint: str = "unknown"

    @property
    def needs_review(self) -> bool:
        weakest = float(np.min(self.conf[list(ANCHOR_MARKERS)]))
        return any(f in BLOCKING_FLAGS for f in self.flags) or weakest < 0.5


def _peak_quality(s: np.ndarray, p: int, noise: float, half: int = 400) -> float:
    """0..1: how far the peak rises above its local surroundings relative to the curve's noise floor."""
    lo, hi = max(0, p - half), min(len(s), p + half)
    local = float(np.percentile(s[lo:hi], 25))
    h = float(s[p]) - local
    return float(np.clip((h - 3 * noise) / 3.0, 0.0, 1.0))


def detect(avg: np.ndarray, n_scans: int | None = None, subject_hint: str = "unknown", profile: Profile | None = None,
           device_cursors: dict[int, float] | None = None, place_lens_interior: bool = False) -> Detection:
    profile = profile or load_profile()
    flags: list[str] = []
    if subject_hint == "human_likely":
        flags.append("NOT_VALIDATED_SUBJECT")       # chick-tuned windows/profile: a person must check every marker
    elif subject_hint == "unknown":
        flags.append("SUBJECT_UNKNOWN")
    if n_scans is not None and n_scans < 5:
        flags.append("FEW_SCANS")
    p, a = raw_positions(avg, profile.fractions)
    if p is None:
        return Detection(np.full(13, np.nan), np.zeros(13), flags + ["ANCHOR_FAIL"], profile.name, subject_hint)
    n = len(avg)
    x = p.copy()
    for m, b in profile.bias.items():
        if m < 13 and not np.isnan(x[m]):
            x[m] += b
    x = np.clip(np.round(x), 0, n - 1)

    # --- confidence per marker
    s, noise = a["s"], a["noise"]
    conf = np.zeros(13)
    for m, key in ((0, "cornea"), (2, "lens_front"), (9, "lens_back"), (12, "rpe")):
        conf[m] = 0.55 + 0.45 * _peak_quality(s, int(a[key]), noise)
    cur = device_cursors or {}
    for m, c in CURSOR_FOR_MARKER.items():
        if c in cur and m in ANCHOR_MARKERS:
            if abs(cur[c] - x[m]) <= CURSOR_TOL[m]:
                conf[m] = min(1.0, conf[m] + 0.1)            # agreement nudges confidence up
            elif "DEVICE_DISAGREES" not in flags:
                flags.append("DEVICE_DISAGREES")             # informational, no penalty (see BLOCKING_FLAGS note)
    anchor_q = float(np.mean(conf[[0, 2, 9, 12]]))
    for m in range(13):
        if m not in ANCHOR_MARKERS:
            conf[m] = float(np.clip(profile.reliability.get(m, 0.3) * (0.6 + 0.4 * anchor_q), 0.0, 1.0))
    if a["n_post"] < 2:                              # fewer than two peaks behind the RPE: choroid/sclera are guesses
        flags.append("POSTERIOR_UNCERTAIN")
        conf[[5, 6]] *= 0.5
    if not place_lens_interior:
        x[list(LENS_FRACTION_MARKERS)] = np.nan      # left for manual placement; see module docstring
        conf[list(LENS_FRACTION_MARKERS)] = 0.0

    # --- plausibility of geometry vs the chick calibration set
    geom = {"cornea_pos": x[0], "cornea_to_lens_front": x[2] - x[0], "lens_thickness": x[9] - x[2],
            "lens_back_to_rpe": x[12] - x[9]}
    for k, v in geom.items():
        r = profile.ranges.get(k)
        if r and not (r[0] <= v <= r[1]):
            if "OUT_OF_RANGE_FOR_CHICK" not in flags:
                flags.append("OUT_OF_RANGE_FOR_CHICK")
            conf = conf * 0.7
    chain = [i for i in (0, 1, 2, 3, 4, 7, 8, 9, 10, 12, 5, 6) if not np.isnan(x[i])]
    if len(chain) < 4 or not np.all(np.diff(x[chain]) > 0):      # cornea < ... < lens back < RPE < choroid < sclera
        flags.append("ORDER")
    if subject_hint != "animal_likely":
        conf = np.minimum(conf, 0.4)                # never look confident on data the method was not validated on
    return Detection(x, conf, flags, profile.name, subject_hint)


# ------------------------------------------------------------------ helpers used by the research scripts
def predict(avg: np.ndarray, fractions: dict[int, float]):
    """Research API (evaluate.py): raw positions with given fractions, no bias correction."""
    p, _ = raw_positions(avg, fractions)
    return p


def lens_fractions(train: list[dict]) -> dict[int, float]:
    out = {}
    for m in LENS_FRACTION_MARKERS:
        v = []
        for d in train:
            x = d["label_x"]
            if np.isnan(x[[2, 9, m]]).any() or x[9] <= x[2]:
                continue
            v.append((x[m] - x[2]) / (x[9] - x[2]))
        out[m] = float(np.median(v)) if v else 0.5
    return out
