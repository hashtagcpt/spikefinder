"""Synthetic Lenstar-style .esx files, so you can try the tool (and run the tests) without any real exam.

The A-scans are made-up: Gaussian peaks at chick-like positions plus a little noise. They only exercise the file format, the
detector and the review window; they say nothing about real eyes.

    spikefinder sample my_sample.esx          # then:  spikefinder my_sample.esx
"""
from __future__ import annotations

import base64
import zlib

import numpy as np

N_SAMPLES = 59375

# (sample position, display-curve height) of each synthetic echo
PEAKS = {"reference": (1000, 39), "cornea": (1300, 20), "lens_front": (3600, 5), "lens_back": (7900, 6.5),
         "retina": (17100, 9), "rpe": (17500, 17), "choroid": (17800, 7), "sclera": (18000, 8)}


def make_avg(shift: int = 0, seed: int = 0) -> np.ndarray:
    """One synthetic A-scan (linear intensity). Inverts the display transform max(0, log2 I)**1.5."""
    rng = np.random.default_rng(seed)
    x = np.arange(N_SAMPLES)
    disp = np.zeros(N_SAMPLES)
    for pos, h in PEAKS.values():
        disp += h * np.exp(-0.5 * ((x - pos - shift) / 18.0) ** 2)
    disp += rng.normal(0, 0.03, N_SAMPLES).clip(0)
    return 2.0 ** (np.maximum(disp, 0) ** (1 / 1.5))


def _b64(arr: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(np.asarray(arr, dtype=">f4").tobytes())).decode()


def write_sample_esx(path: str, name: str = "S0001", first: str = "", birthday: str = "2025.04.09",
                     timestamp: str = "2025.04.17-19:18:35-0", n_scans: int = 6, eyes=("OD", "OS")) -> str:
    """Write a minimal synthetic .esx (same structure as an EyeSuite export, one exam, one measurement per eye)."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?><EYESUITE><EXPORT><PATIENT version="1.0.0">',
             f"<NAME>{name}</NAME><FIRSTNAME>{first}</FIRSTNAME><BIRTHDAY>{birthday}</BIRTHDAY></PATIENT>",
             f'<EXAMINATION category="1030" method="2" timestamp="{timestamp}"><BIOMETRY>']
    for k, eye in enumerate(eyes):
        parts.append(f'<MEASUREMENT eye="{eye}">')
        for i in range(n_scans):
            parts.append(f"<ASCAN><INDEX>{i}</INDEX><USED>true</USED><SCANLENGTH>{N_SAMPLES}</SCANLENGTH>"
                         f"<SCANDATA>{_b64(make_avg(seed=i + 10 * k))}</SCANDATA></ASCAN>")
        # one scan flagged unused: it must be ignored by the loader
        parts.append(f"<ASCAN><INDEX>99</INDEX><USED>false</USED><SCANLENGTH>{N_SAMPLES}</SCANLENGTH>"
                     f"<SCANDATA>{_b64(np.ones(N_SAMPLES) * 1000)}</SCANDATA></ASCAN>")
        parts.append("</MEASUREMENT>")
    parts.append("</BIOMETRY></EXAMINATION></EXPORT></EYESUITE>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return path
