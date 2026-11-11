"""Research biometry using the historical lab optical-path calibration.

These are protocol estimates, not a validation of chick refractive indices.
Reference sample 1000 is assumed to represent the anterior corneal surface.
"""
from __future__ import annotations

import math

SAMPLES_PER_OPL_MM = 1250.0
REFERENCE_SAMPLE = 1000.0
INDICES = dict(cornea=1.34507504, aqueous=1.344191678, lens=1.419086426,
               vitreous=1.342799941, retina=1.36, choroid=1.36, sclera=1.36,
               eye=1.357442592)


def measurements(x, samples_per_opl_mm=SAMPLES_PER_OPL_MM, reference_sample=REFERENCE_SAMPLE,
                 indices=None):
    """Return mm estimates; absent/reversed boundaries produce None, never negative thickness.

    Choroid = Choroid minus RPE; sclera = Sclera minus Choroid, following the
    historical protocol. Axial length uses RPE minus reference / whole-eye index.
    Vitreous-to-RPE is provided separately from vitreous-to-retina.
    """
    ri = dict(INDICES, **(indices or {}))
    if not math.isfinite(samples_per_opl_mm) or samples_per_opl_mm <= 0:
        raise ValueError("samples_per_opl_mm must be finite and positive")
    if not math.isfinite(reference_sample) or any(not math.isfinite(v) or v <= 0 for v in ri.values()):
        raise ValueError("reference and refractive indices must be finite; indices must be positive")

    def distance(a, b, tissue):
        if not all(math.isfinite(float(v)) for v in (a, b)) or b <= a:
            return None
        return float(b - a) / samples_per_opl_mm / ri[tissue]

    out = {
        "axial_length_mm": distance(reference_sample, x[12], "eye"),
        "corneal_thickness_mm": distance(reference_sample, x[0], "cornea"),
        "aqueous_depth_mm": distance(x[0], x[2], "aqueous"),
        "lens_thickness_mm": distance(x[2], x[9], "lens"),
        "vitreous_depth_to_retina_mm": distance(x[9], x[11], "vitreous"),
        "vitreous_depth_to_rpe_mm": distance(x[9], x[12], "vitreous"),
        "retinal_thickness_mm": distance(x[11], x[12], "retina"),
        "choroidal_thickness_mm": distance(x[12], x[5], "choroid"),
        "scleral_thickness_mm": distance(x[5], x[6], "sclera"),
    }
    c, aq = out["corneal_thickness_mm"], out["aqueous_depth_mm"]
    out["anterior_chamber_depth_mm"] = c + aq if c is not None and aq is not None else None
    parts = [out[k] for k in ("corneal_thickness_mm", "aqueous_depth_mm", "lens_thickness_mm",
                              "vitreous_depth_to_retina_mm", "retinal_thickness_mm")]
    out["axial_length_sum_segments_to_rpe_mm"] = sum(parts) if all(v is not None for v in parts) else None
    posterior = [out["axial_length_sum_segments_to_rpe_mm"], out["choroidal_thickness_mm"],
                 out["scleral_thickness_mm"]]
    out["eye_length_sum_segments_to_sclera_mm"] = sum(posterior) if all(v is not None for v in posterior) else None
    return out

