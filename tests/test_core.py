import json
import numpy as np
from conftest import make_avg, write_esx, N
from spikefinder import esx, detect, labels, privacy, session, export


def test_esx_loads_and_averages(esx_file):
    exams = esx.load_esx(esx_file)
    assert len(exams) == 1 and set(exams[0].eyes) == {"OD", "OS"}
    es = exams[0].eyes["OD"]
    assert es.n == 6                                   # the unused A-scan is ignored
    expected = np.mean([make_avg(seed=i) for i in range(6)], axis=0)
    assert np.allclose(es.average, expected, rtol=1e-5)        # big-endian float32 round trip
    assert exams[0].name == "13151"


def test_bad_file_raises(tmp_path):
    p = tmp_path / "x.esx"; p.write_text("not xml")
    try:
        esx.load_esx(str(p)); assert False
    except esx.EsxError:
        pass


def test_display_curve():
    assert esx.display_curve(np.array([0.0, 1.0, 4.0]))[2] == 2 ** 1.5      # log2(4)=2 -> 2^1.5
    assert esx.display_curve(np.array([0.5]))[0] == 0.0                       # negative log clipped


def test_detector_finds_peaks_within_tolerance():
    prof = detect.load_profile()
    d = detect.detect(make_avg(), 80, "animal_likely", prof)
    pos = {"Cornea/Aqueous": 1300, "Aqueous/Capsule": 3600, "Capsule/Vitreous": 7900, "RPE": 17500}
    for name, p in pos.items():
        i = detect.MARKER_NAMES.index(name)
        assert abs(d.x[i] - p) <= 12, (name, d.x[i])
    assert detect.MARKER_NAMES[5] == "Choroid" and detect.MARKER_NAMES[6] == "Sclera"
    assert abs(d.x[5] - 17800) <= 15 and abs(d.x[6] - 18000) <= 15
    assert np.isnan(d.x[list(detect.LENS_FRACTION_MARKERS)]).all()        # lens interior is not auto-placed
    assert not d.needs_review


def test_human_and_unknown_are_flagged_and_capped():
    for hint, flag in (("human_likely", "NOT_VALIDATED_SUBJECT"), ("unknown", "SUBJECT_UNKNOWN")):
        d = detect.detect(make_avg(), 80, hint)
        assert flag in d.flags and d.needs_review and d.conf.max() <= 0.4


def test_garbage_curve_fails_safely():
    d = detect.detect(np.ones(100), 50, "animal_likely")
    assert "ANCHOR_FAIL" in d.flags and np.isnan(d.x).all()
    flat = detect.detect(np.ones(N), 50, "animal_likely")           # no peaks at all: must not crash
    assert flat.needs_review


def test_privacy_hints():
    h = privacy.subject_hint
    assert h("13151", "", "2025.04.09", "2025.04.17-19:18:35-0") == "animal_likely"
    assert h("a14402", "", "2020.02.01", "2020.02.21-10:00:00-0") == "animal_likely"
    assert h("Smith", "John", "1970.01.01", "2025.04.17-19:18:35-0") == "human_likely"
    assert h("12345", "", "1980.05.05", "2025.04.17-19:18:35-0") == "human_likely"      # numeric id but adult age
    assert privacy.display_id("Smith", "John", "1970.01.01", "human_likely").startswith("H-")
    assert "Smith" not in privacy.display_id("Smith", "John", "1970.01.01", "human_likely")


def test_session_and_review_roundtrip(tmp_path):
    f = write_esx(str(tmp_path / "h.esx"), name="Smith", first="John", birthday="1970.01.01")
    recs = session.process_file(f)
    assert recs[0].hint == "human_likely" and "Smith" not in recs[0].subject_key and recs[0].needs_review
    recs[0].set_marker(12, 17600); recs[0].confirm("tester")
    out = str(tmp_path / "out")
    p = session.save_review(recs, out)[0]
    txt = open(p).read()
    assert "Smith" not in txt and "John" not in txt and "1970" not in txt         # no identifiers on disk
    fresh = session.process_file(f)
    assert session.apply_review(fresh, out) == 1
    assert fresh[0].x[12] == 17600 and fresh[0].status == "confirmed" and fresh[0].reviewer == "tester"
    assert json.loads(txt)["eyes"][0]["auto_x"][12] != 17600


def test_exports_roundtrip_through_original_parser(esx_file, tmp_path):
    recs = session.process_file(esx_file)
    r = recs[0]
    for i, v in zip((3, 4, 7, 8), (4000, 4500, 6500, 7400)):          # place lens-interior markers manually
        r.set_marker(i, v)
    tidy, exe = str(tmp_path / "t.csv"), str(tmp_path / "e.csv")
    export.write_tidy_csv(recs, tidy)
    assert "Smith" not in open(tidy).read()
    assert export.write_exe_csv(recs, exe) == 2
    rows = labels.load_label_csv(exe)                                  # parse with the legacy 58-col parser
    assert len(rows) == 2
    got = rows[0]
    assert got.x["Cornea/Aqueous"] == r.x[0] and got.x["RPE"] == r.x[12]
    assert got.x["Anterior Nucleus Nadir"] == r.x[5]                    # legacy slot holds the choroid
    assert abs(got.y["RPE"] - float(r.avg[int(r.x[12])])) < 1e-6 and got.opl == r.x[12] - 1000
