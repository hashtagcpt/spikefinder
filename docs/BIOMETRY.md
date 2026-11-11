# Batch biometry and validation

Run `spikefinder run PATH_TO_ESX_FOLDER --out results --exe-csv` to search recursively.
Open `results/biometry.csv` in Excel, LibreOffice, R or Python. There is one row per
source/subject/eye/examination. It includes blank experimental_group, treatment,
timepoint and experimental_notes columns for later annotation. Keep those annotations
in a separate keyed table: rerunning exports replaces the CSV. Duplicate examinations
across source files are retained and counted in duplicate_exam_count; resolve them
before statistical analysis. The subject/eye/timestamp key supports later joins.

The GUI File menu also exports biometry and device results after manual review.
Only confirmed eyes have requires_review=0, regardless of detector warning flags.
Missing or reversed boundaries give blank measurements, listed in unavailable_measurements.
Automatic positions remain visible for review, including low-confidence suggestions.

`device_results.csv` preserves every device biometry dimension
with its USED, QUALITY and WARNINGIDS metadata. Dimension element IDs are not assigned
anatomical names because their mapping is not established. A rejected device value
is not a substitute for a reviewed landmark measurement.

`batch_report.json` records input count, output eye count and failed files. Any failed
file makes the command exit nonzero even when other files succeeded. Truncated XML,
non-finite intensities and inconsistent scan lengths fail explicitly. Do not use old
CSV files remaining in an output folder after a completely unsuccessful run.

## Measurement definitions and assumptions

The historical research conversion uses 1250 samples per mm of optical path and an
anterior cornea reference of sample 1000. Neither is automatically established for
other instruments or scan formats. Refractive indices and reference are exported in
every analysis row. Values are **protocol estimates**, not calibrated absolute chick
dimensions. The Python API `biometry.measurements` accepts alternative calibration
and tissue indices; the CLI currently uses the documented defaults.

| Output | Formula (sample positions) |
|---|---|
| axial_length_mm | (RPE - 1000) / 1250 / 1.357442592 |
| corneal_thickness_mm | (Cornea/Aqueous - 1000) / 1250 / 1.34507504 |
| aqueous_depth_mm | (lens front - Cornea/Aqueous) / 1250 / 1.344191678 |
| anterior_chamber_depth_mm | corneal thickness + aqueous depth |
| lens_thickness_mm | (lens back - lens front) / 1250 / 1.419086426 |
| vitreous_depth_to_retina_mm | (Retina - lens back) / 1250 / 1.342799941 |
| vitreous_depth_to_rpe_mm | (RPE - lens back) / 1250 / 1.342799941 |
| retinal_thickness_mm | (RPE - Retina) / 1250 / 1.36 |
| choroidal_thickness_mm | (Choroid - RPE) / 1250 / 1.36 |
| scleral_thickness_mm | (Sclera - Choroid) / 1250 / 1.36 |

`axial_length_sum_segments_to_rpe_mm` sums cornea, aqueous, lens, vitreous-to-retina
and retina. `eye_length_sum_segments_to_sclera_mm` additionally includes choroid and
sclera. These differ in anatomical endpoint and conversion model from axial_length_mm.
The whole-eye-index estimate does not depend on the unreliable Retina marker. Do not
mix these definitions within an analysis. Landmark names alone do not establish
histological layer boundaries; posterior thicknesses follow the historical marking convention.

Keratometry is excluded from this workflow.

Human biometer conversion assumptions are not interchangeable with chicken anatomy.
See the primary study on [Lenstar refractive indices](https://pubmed.ncbi.nlm.nih.gov/25532546/).

## Remaining limitations

Review every eye, particularly choroid/sclera and Retina. Detector flags miss errors.
Anterior corneal position is a fixed reference assumption, not a detected landmark.
The parser expects the tested non-namespaced EyeSuite XML layout. Non-phakic modes
are not validated. Processing retains averaged scans for the whole batch in memory;
very large collections should be split into smaller batches. Exported treatment
annotations are not restored on rerun. Review filenames include a path hash to avoid
collisions; moving inputs changes that hash. Older review files are read as a fallback,
so avoid ambiguous legacy files with identical input basenames.

No independent physical reference or repeatability study was available in this audit. Hand-mark agreement cannot validate physical units.
