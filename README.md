# SpikeFinder (Python)

Automatic landmark ("spike") marking for **Lenstar LS 900 A-scans** exported from EyeSuite as `.esx` files, with a small
cross-platform window (Windows, macOS, Linux) so a person can **check and correct every mark**.

This is an open, MIT-licensed, independent reimplementation of the idea behind the lab's old Windows-only
`LenstarSpikeFinder.exe` (hand-marking of A-scan peaks). It reads the `.esx` files directly: no MySQL server, no EyeSuite
database and no Windows needed. It was built and validated on **chick eyes** (the lab's model animal); see
[Limitations](#limitations) before using it on anything else.

> **Automatic marks are suggestions, not measurements.** Nothing is final until a person confirms it. This software is
> research code, not a medical device, and must not be used for clinical decisions.

## What you get

* `spikefinder run FILES --out DIR` - marks every eye in every `.esx`, writes tables, review files and optional PNGs.
* `spikefinder` (or `spikefinder gui FILES`) - a review window: the averaged A-scan with the marks on it; drag marks, nudge
  them with the keyboard, place missing ones, delete wrong ones, confirm an eye. Edits are saved automatically.
* Per-mark confidence and QC flags, so you can jump straight to the eyes that need a look (`f` key).
* Export as a tidy CSV, or in the original SpikeFinder 58-column "Dump" format so existing R/MATLAB scripts keep working.

## Install

You need **Python 3.9 or newer** with Tk (the window toolkit). Dependencies (numpy, scipy, matplotlib) install automatically.

### Windows
1. Install Python from <https://www.python.org/downloads/> (the installer includes Tk; tick *Add python.exe to PATH*).
2. In a terminal (PowerShell):
   ```powershell
   git clone https://github.com/hashtagcpt/spikefinder.git
   cd spikefinder
   python -m venv .venv
   .venv\Scripts\activate
   pip install .
   spikefinder
   ```

### macOS
1. Install Python from <https://www.python.org/downloads/> (includes Tk) **or** `brew install python python-tk`.
2. In Terminal:
   ```bash
   git clone https://github.com/hashtagcpt/spikefinder.git && cd spikefinder
   python3 -m venv .venv && source .venv/bin/activate
   pip install .
   spikefinder
   ```

### Linux (Debian/Ubuntu shown)
```bash
sudo apt install python3 python3-venv python3-tk     # Fedora: sudo dnf install python3-tkinter
git clone https://github.com/hashtagcpt/spikefinder.git && cd spikefinder
python3 -m venv .venv && source .venv/bin/activate
pip install .
spikefinder
```
Needs a desktop session for the window. On a server or over SSH without a display, use the headless `spikefinder run ... --png`.

### Developers / researchers
```bash
pip install -e ".[dev]"      # editable install + pytest + pyinstaller
python -m pytest -q tests
```

### Standalone app (no Python for end users)
`packaging/launch_gui.py` is the entry point for PyInstaller; `.github/workflows/build-app.yml` builds one app per OS from
GitHub (Actions tab -> *build-app* -> *Run workflow*). Locally:
```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name SpikeFinder --collect-data spikefinder packaging/launch_gui.py
```
The workflow builds on Linux, macOS and Windows in CI, but nobody has launched the macOS/Linux apps yet; test them before handing them out. macOS may
require right-click -> Open the first time (unsigned app).

## Quick start

No data handy? `spikefinder sample sample.esx` writes a **synthetic** `.esx` (made-up A-scans) so you can try everything below.
The file layout is documented in [docs/ESX_FORMAT.md](docs/ESX_FORMAT.md).

```bash
# review window; open files/folders from the File menu or pass them here
spikefinder  path/to/exam.esx  path/to/folder_of_esx_files

# headless: mark everything, write results, make a picture of every eye
spikefinder run path/to/folder --out results --png --exe-csv
```

`run` writes into `--out` (default `~/SpikeFinder/review`):

| File | Contents |
|---|---|
| `markers.csv` | one row per eye: id, eye, timestamp, scans, status, flags, then `<marker>_x`, `_y`, `_conf` for each marker |
| `biometry.csv` | axial length and tissue thickness estimates in mm, review state, and blank experimental-condition fields |
| `device_results.csv` | individual device biometry dimensions, including acceptance and warning metadata |
| `batch_report.json` | input/eye counts and failed files; any failure gives a nonzero exit code |
| `<esx name>.spikefinder.json` | the review file (automatic positions, current positions, status, notes, reviewer) - the GUI reads and updates it |
| `spike_finder_export.csv` | (with `--exe-csv`) original SpikeFinder "Dump" layout |
| `png/` | (with `--png`) one picture per eye |

Positions in `markers.csv` are **sample indices** of the Lenstar A-scan (the same coordinates the original tool used).
`_y` is the mean linear intensity at that sample, as in the original export.

`biometry.csv` uses the historical optical-path calibration and tissue refractive indices.
These are research estimates requiring confirmation, with absolute chicken accuracy still unvalidated.
See [biometry definitions and batch workflow](docs/BIOMETRY.md) and the [audit results](docs/AUDIT_2026-11-11.md).
Review the landmarks in the GUI, then use File > Export biometry for updated measurements.
Keep experimental annotations separately: rerunning exports replaces their blank columns.

### Review window keys

| Key | Action | Key | Action |
|---|---|---|---|
| `n` / `p` | next / previous eye | `c` | confirm eye (records reviewer + time) |
| `f` | next eye that needs review | `r` | reset to the automatic result |
| `[` / `]` | select previous / next marker | `Left` / `Right` | nudge selected marker 1 sample (Shift: 10) |
| `Delete` | remove selected marker | `i`, then click | place the selected (missing) marker |
| `s` / `Ctrl+S` | save | drag a line | move it (snaps to the local peak; toggle in *View*) |

Eye status: **auto** (untouched), **edited** (a person changed something), **confirmed** (a person signed it off).
Rows marked `*` need review. A dashed line is a low-confidence automatic mark. Use the matplotlib toolbar to zoom/pan
(dragging marks is disabled while zoom/pan is active). *View* switches between full / anterior / lens / posterior ranges, display
vs linear intensity, and shows the Lenstar device's own cursors.

## Markers

13 slots, numbered as in the original tool. **Slots 6 and 7 were called "Anterior/Posterior Nucleus Nadir" in the original
software but were used for the chick *choroid* and *sclera*; this program calls them Choroid and Sclera.** The legacy
names are kept only in the original-format export so old scripts still line up.

| # | This program | Original name | Placed automatically? |
|---|---|---|---|
| 1 | Cornea/Aqueous | same | yes |
| 2 | Aqueous/Lens Baseline | same | yes (estimate) |
| 3 | Aqueous/Capsule (lens front) | same | yes |
| 4 | Capsule/Cortex | same | **no** (lens interior) |
| 5 | Cortex/Nucleus | same | **no** (lens interior) |
| 6 | **Choroid** | Anterior Nucleus Nadir | yes |
| 7 | **Sclera** | Posterior Nucleus Nadir | yes |
| 8 | Nucleus/Cortex | same | **no** (lens interior) |
| 9 | Cortex/Capsule | same | **no** (lens interior) |
| 10 | Capsule/Vitreous (lens back) | same | yes |
| 11 | Lens/Vitreous Baseline | same | yes (estimate) |
| 12 | Retina | same | yes (optional; convention varies) |
| 13 | RPE | same | yes |

## How it works (short)

1. `.esx` is XML; each A-scan is base64 -> zlib -> big-endian float32 (59,375 samples). All A-scans flagged *used* are averaged
   per eye. This reproduces the original program exactly (checked against its saved marks to three decimals).
2. The display curve is `max(0, log2(mean))^1.5`, as in the original window.
3. Rules find the anchor peaks inside search windows (cornea, lens front, lens back, the retina/RPE complex and the two
   posterior-wall peaks), walk down the flanks for the two lens baselines, and then apply a small per-profile bias correction.
4. Confidence comes from how clearly each peak stands out of the noise, a small boost when the Lenstar device cursors in the
   file agree, and the held-out accuracy of that marker. QC flags that ask for review: `ANCHOR_FAIL`, `ORDER`,
   `POSTERIOR_UNCERTAIN` (fewer than two peaks behind the RPE, so choroid/sclera are guesses), `OUT_OF_RANGE_FOR_CHICK`,
   `FEW_SCANS`, `NOT_VALIDATED_SUBJECT`, `SUBJECT_UNKNOWN`. `DEVICE_DISAGREES` is informational only: the device cursors were
   themselves often far from the hand marks, so a disagreement is not evidence that the detector is wrong.

Detector *profiles* (`src/spikefinder/profiles/*.json`, listed by `spikefinder profiles`) hold fitted corrections:
`chick_2017_2020` (default) and `chick_2015_2016` (older labelling conventions).

## How accurate is it?

Leave-one-animal-out, against the lab's hand marks (profile `chick_2017_2020`: 118 eye-exams from 28 chicks; 2015-2016 profile:
156 eye-exams from 41 chicks; the hand-marked data are not included in this repository). "Within 5" = automatic mark within 5 samples of the human mark.

| Marker | Within 5 samples (2017-2020) | Within 5 samples (2015-2016) |
|---|---|---|
| Cornea/Aqueous | 97% | 99% |
| Aqueous/Capsule (lens front) | 93% | 65% |
| Capsule/Vitreous (lens back) | 97% | 98% |
| RPE | 96% | 98% |
| Choroid / Sclera | 79% / 77% | 82% / 84% |
| Retina | 70% | 2% (different convention) |
| Aqueous/Lens Baseline, Lens/Vitreous Baseline | 17% / 14% (67% / 81% within 25) | 24% / 12% |

**Review flags are a priority hint, not a guarantee.** On the 118 labelled 2017-2020 eye-exams, 28 (24%) had at least one of the
six peak markers more than 25 samples from the human mark. The flags (`needs review`) marked 8 eyes (7%); all 8 really had an
error, but they catch only 8 of the 28. **An unflagged eye is not a checked eye** - look at every eye, or at least a random
sample of each batch, before using the numbers.

These are a few dozen animals from one lab and one instrument, and the "truth" is itself human judgement. Treat the numbers as
indicative, not as a guarantee for your data.

## Limitations

Please read these before relying on the output.

1. **Chick eyes only.** Everything (search windows, geometry limits, profiles, accuracy numbers) comes from chick eyes
   measured on a Lenstar LS 900. The chick eye is used as a *model*; its optics are not human optics. **Human eyes are
   not validated at all.** Subjects that look human or cannot be identified as animals are flagged
   (`NOT_VALIDATED_SUBJECT` / `SUBJECT_UNKNOWN`), get capped confidences, and must be checked by a person.
2. **The lens interior is not handled.** Capsule/Cortex, Cortex/Nucleus, Nucleus/Cortex and Cortex/Capsule are subjective
   shoulders in the chick lens, are not meaningful as a model for the human lens, and the automatic estimates were poor
   (median errors of ~40-350 samples). They are **not placed automatically**; you can place them by hand. The two lens
   *baseline* markers are rough estimates (a few tens of samples off).
3. **Legacy names are misleading.** In data labelled with the original tool, slots 6/7 ("Nucleus Nadir") hold choroid and
   sclera. Any old analysis that treated them as lens nucleus landmarks, or computed the original cortex/nucleus areas
   (AUCs) and spike slopes from them, is not meaningful for chick data. The original-format export therefore leaves those
   derived columns blank unless all lens-interior markers were placed.
4. **Labelling conventions drifted between years and people.** The Retina marker and (in 2015) the lens-front marker were
   placed differently in the older data. Use the profile that matches your convention, or re-fit one (below).
5. **Only peak-type markers are reasonably reliable**: cornea, lens front, lens back, RPE, choroid, sclera (and even those
   are off by more than 25 samples in roughly 1 eye in 4, mostly the choroid/sclera when the posterior wall has fewer than two
   clear peaks). Retina is convention-dependent. The review flags miss most of these errors (see *How accurate is it?*).
6. **Units.** Marker positions are sample indices. Biometry exports add mm estimates under explicit historical calibration
   and index assumptions; independent physical validation in chickens remains necessary.
7. **Only the phakic 13-marker layout.** The original tool's pseudophakic layout and image-based keratometry fitting are not
   implemented. Keratometry is outside the current scope.
8. **File compatibility.** Tested on EyeSuite `.esx` exports from 2016-2025 (A-scans of 59,375 samples, one instrument). Other firmware, other scan lengths or other instruments may fail to parse or fall outside the search windows
   (then you get `ANCHOR_FAIL`/`OUT_OF_RANGE_FOR_CHICK`). Truncated files are read as far as they are complete.
9. **Averaging only.** Only A-scans flagged *used* are averaged (as the original did); no outlier rejection or re-alignment.
10. **Platform testing.** The automated tests pass in CI on Linux, macOS and Windows with Python 3.9 and 3.12
    (`.github/workflows/tests.yml`). The review window itself has only been hand-tested on Windows; on macOS and Linux it is
    untested by a human, and Tk looks different on each system.
11. **Speed/memory.** Files up to ~300 MB parse in seconds to a minute with a few hundred MB of RAM; there is no GPU or
    multiprocessing.
12. **No ground truth is bundled.** The `.esx` data and hand-marked tables are not part of this repository.

## Privacy

`.esx` files can contain names and birth dates (e.g. if human exams are mixed in). This program tries to keep them out of
everything it writes: the window, CSVs, review JSON and PNG titles show the animal id, or a short hash (`H-xxxxxxxx`) for
anything that does not look like an animal id; first names and dates of birth are never written (the original-format
export leaves them blank). The animal/human guess is a heuristic (first name present, adult age, non-id name) and can be
wrong - check your data before sharing outputs, and never commit raw `.esx` files (the `.gitignore` excludes them).

## Extending it

* **Input format:** [docs/ESX_FORMAT.md](docs/ESX_FORMAT.md) describes the `.esx` structure (reverse-engineered, unofficial).
  `spikefinder.esx.load_esx` is a streaming reader you can reuse on its own.
* **Better detector:** `detect.detect(avg, n_scans, subject_hint, profile, device_cursors)` returns a `Detection` (positions,
  confidences, flags). Replace or extend it; the window, exports and review files only depend on that object.
* **Profiles:** a profile is a small JSON file (`src/spikefinder/profiles/*.json`, see `detect.Profile`) with per-marker bias
  corrections, reliabilities and geometry limits fitted on hand-marked data. The fitting scripts depend on lab data and are not
  part of this repository; you can write profiles for your own labelling convention by hand or with your own script.
* **Library use:**
  ```python
  from spikefinder.esx import load_esx
  from spikefinder.detect import detect
  exam = load_esx("exam.esx")[0]
  es = exam.eyes["OD"]
  det = detect(es.average, es.n, exam.subject_hint)
  print(det.x, det.flags)
  ```
* Contributions are welcome: please add a test (`tests/`) for new behaviour and keep real patient/animal data out of the repo.

## Relationship to the original SpikeFinder

This package is an independent reimplementation based on the *behaviour and file formats* of the original program
(`.esx` structure, A-scan encoding, display transform, marker semantics, 58-column export layout). It contains no code from
the original executable. If you are redistributing this in an institution, confirm that the lab/owner of the original
software is comfortable with the reimplementation and the MIT licence.

## Licence

MIT - see [LICENSE](LICENSE). *Lenstar* and *EyeSuite* are trademarks of their respective owners; this project is independent of and
not endorsed by them.
