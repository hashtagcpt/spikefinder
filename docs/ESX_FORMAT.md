# The Lenstar / EyeSuite `.esx` export format

> **Unofficial.** This is reverse-engineered from `.esx` exports of Lenstar LS 900 biometer data (EyeSuite 2.x, exports dated
> 2016-2025, one instrument). It is not Haag-Streit documentation, may be incomplete, and other firmware or software versions may
> differ. *Lenstar* and *EyeSuite* are trademarks of their owners; this project is not affiliated with or endorsed by them.
> Verify against your own files (`spikefinder sample` writes a synthetic file with this structure).

## Overview

An `.esx` file is a single **XML** document (UTF-8). One file holds one patient/animal and one or more examinations. Files are
large (45-300 MB) because every raw A-scan and several camera images are embedded as base64 text, so **parse it as a stream**
(`xml.etree.ElementTree.iterparse`) and clear elements as you go; `spikefinder.esx.load_esx` does this.

```
EYESUITE
├── SOFTWARE        FAMILY, NAME, VERSION            (e.g. HSEyeSuite / HSEyeSuiteBasic / 2.1.0)
├── TIMESTAMP       DATE (yyyy.mm.dd), TIME (hh:mm:ss)    export time
├── USER
├── EXPORT
│   ├── PATIENT  [version]   UUID, NAME, FIRSTNAME, PATIENTID, BIRTHDAY (yyyy.mm.dd), DIAGNOSIS[eye], RISKFACTORS,
│   │                        GENDER, ETHNIE, COMMENT
│   └── EXAMINATION*  [category, method, timestamp="yyyy.mm.dd-hh:mm:ss-<ms>"]
│       ├── NOTES
│       └── BIOMETRY
│           ├── BIOMHARDWARE   SERIALNUMBER, board identifiers, FWVERSIONS
│           ├── VERSION, NUMBER
│           └── MEASUREMENT*  [eye="OD"|"OS"]
│               ├── START, STOP                      measurement time span
│               ├── NULLIFICATION                    TIMESTAMP, MEASURINGLEVEL, DETECTIONLEVEL
│               ├── ASCAN*          INDEX, USED, SATURATED, DISTANCE, SCANLENGTH, SCANDATA, CRC
│               ├── KERIMAGE*       INDEX, IMAGELENGTH, IMAGE                 (keratometry camera image)
│               ├── FULLIMAGE*      INDEX, IMAGELENGTH, IMAGE, GREENLIGHT, IRLIGHT, QUALITY, ERRORCODE, ...
│               ├── BIOMETRYSETTING WAVELENGTH, SETTINGEYE*  (ELEMENT, MEASMODE, MINIMAL, MAXIMAL, IDEAL, STDDEV, REFRINDEX, ...)
│               ├── BIOMETRYRESULT  SWVERSION, EVALID, MEASURINGMODE, QUALITY, USED, SCANLENGTH, SCANDATA, CRC,
│               │                   DIMENSION* (ELEMENT, DIMVALUE, USED, QUALITY, EVALUATIONMODE, WARNINGIDS),
│               │                   CURSOR*    (CURSORELEMENT, SCANPOS, VALUE, PROCESSMODE, QUALITY, WARNINGIDS)
│               ├── KERATOMETRYSETTING, KERATOMRESULT
└── CHECKSUM        e.g. 0xE30C9BA2
```
`*` = repeats. An exam can contain several `MEASUREMENT` elements for the same eye; the original SpikeFinder (and this tool)
pool all A-scans flagged `USED` for an eye in an exam.

## A-scans (`ASCAN/SCANDATA`)

* `SCANDATA` is **base64 -> zlib -> array of big-endian IEEE-754 float32** with `SCANLENGTH` values (59,375 in all files seen).
* `USED` is `true`/`false`: the instrument's own selection of good scans. Average only the `true` ones.
* Zero samples are valid zeros. Intensities are linear; the original software plots `max(0, log2(mean))^1.5`.
* The coordinate used everywhere in SpikeFinder is the **sample index** (0-based position in this array), not a physical unit.
  In chick data the first strong echo (probe/reference) sits at about sample 1000.

```python
import base64, zlib, numpy as np
scan = np.frombuffer(zlib.decompress(base64.b64decode(ascan_scandata_text)), dtype=">f4")   # len == SCANLENGTH
mean = np.mean(np.vstack(used_scans), axis=0)
```

## Device results (`BIOMETRYRESULT`)

* `DIMENSION/DIMVALUE` values look like metres (e.g. `0.00534178`), `USED` says whether the instrument accepted it, and
  `WARNINGIDS` holds codes such as `IDM_OUT_OF_RANGE`. All dimensions are retained in `device_results.csv`; element numbers remain uninterpreted.
* `CURSOR/SCANPOS` are positions in the same index space as the A-scans. In chick eyes measured on an LS 900, comparison with
  human marks suggests (inferred, not documented): element 1 = cornea, 4 = lens front, 5 = lens back, 6 = retina, 7 = RPE,
  and 0 = the reference position (1000). They are sometimes far from where a person would mark, so treat them as a weak
  cross-check only.
* `BIOMETRYRESULT/SCANDATA` uses the same encoding but a different (shorter) length and is not used here.

## Identifying fields and privacy

`PATIENT/NAME`, `FIRSTNAME`, `BIRTHDAY`, `PATIENTID`, `UUID` and `COMMENT` can contain personal data, and so can file names
(the lab convention is `<animal id>_<yyyy>_<mm>_<dd>.esx`). In animal work `NAME` is an animal id and `BIRTHDAY` is the hatch
date. SpikeFinder reads only `NAME`, `FIRSTNAME` and `BIRTHDAY` to guess "animal vs human" and never writes them to its outputs
(see the README, *Privacy*). Do not publish raw `.esx` files from human subjects.

## What SpikeFinder reads

`PATIENT/{NAME,FIRSTNAME,BIRTHDAY}`, `EXAMINATION@timestamp`, `MEASUREMENT@eye`, `ASCAN/{USED,SCANLENGTH,SCANDATA}`, and
`BIOMETRYRESULT` dimensions/cursors. Keratometry results and settings are skipped.
Images and checksum validation are skipped. Truncated files are rejected rather than silently returning partial data.
Files that are not XML raise `spikefinder.esx.EsxError`. See [biometry](BIOMETRY.md) for units and interpretation.

## SpikeFinder landmark table (original "Dump" CSV)

The original Windows tool saved hand marks to a database and exported a 58-column CSV. `spikefinder run --exe-csv` writes the
same layout. Column groups, in order:

| Columns | Content |
|---|---|
| 1-7 | First Name, Last Name (animal id), DOB, Exam Date, Eye, Confidence (Low/Medium/High), Total Scans |
| 8-17 | Anterior Cortex AUC + rise/run/slope of three anterior spikes |
| 18-27 | Posterior Cortex AUC + rise/run/slope of three posterior spikes |
| 28-30 | Total Cortex AUC, Nucleus AUC, ratio |
| 31-52 | X (sample index) and Y (linear mean intensity at X) of markers 1-11 |
| 53-58 | Retina X, RPE X, RPE Y, "Total OPL in pixels (RPE X - 1000)", Notes, Measure Mode |

Marker slots (1-13): Cornea/Aqueous, Aqueous/Lens Baseline, Aqueous/Capsule, Capsule/Cortex, Cortex/Nucleus, *slot 6*,
*slot 7*, Nucleus/Cortex, Cortex/Capsule, Capsule/Vitreous, Lens/Vitreous Baseline, Retina, RPE. Slots 6 and 7 are named
"Anterior/Posterior Nucleus Nadir" in the original CSV header but were used for the **choroid** and **sclera** in chick work;
SpikeFinder calls them Choroid and Sclera everywhere except this legacy export. The lens-related derived columns (8-30) are
only meaningful when lens-interior markers were placed, so this tool leaves them blank otherwise.
