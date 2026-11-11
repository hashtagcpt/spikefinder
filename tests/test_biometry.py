import csv
import json
import numpy as np
import pytest

from spikefinder import biometry, esx, session, export
from spikefinder.cli import main, collect_files


def test_known_geometry_and_missing_boundaries():
    x = np.full(13, np.nan)
    x[[0, 2, 9, 11, 12, 5, 6]] = [1300, 3600, 7900, 17100, 17500, 17800, 18000]
    m = biometry.measurements(x)
    assert m['axial_length_mm'] == pytest.approx(16500 / 1250 / 1.357442592)
    assert m['choroidal_thickness_mm'] == pytest.approx(300 / 1250 / 1.36)
    assert m['retinal_thickness_mm'] == pytest.approx(400 / 1250 / 1.36)
    assert m['scleral_thickness_mm'] == pytest.approx(200 / 1250 / 1.36)
    assert m['lens_thickness_mm'] == pytest.approx(4300 / 1250 / 1.419086426)
    x[5] = 17000
    assert biometry.measurements(x)['choroidal_thickness_mm'] is None
    x[12] = np.nan
    assert biometry.measurements(x)['axial_length_mm'] is None


def test_metadata_and_repeated_measurements(esx_file, tmp_path):
    text = open(esx_file).read()
    extra = ('<BIOMETRYRESULT><USED>false</USED><DIMENSION><ELEMENT>8</ELEMENT>'
             '<DIMVALUE>0.009</DIMVALUE><USED>false</USED></DIMENSION></BIOMETRYRESULT>')
    p = tmp_path / 'metadata.esx'
    p.write_text(text.replace('</MEASUREMENT>', extra + '</MEASUREMENT>'))
    recs = session.process_file(str(p))
    assert len(recs[0].device_results) == 1
    out = tmp_path / 'b.csv'
    export.write_biometry_csv(recs, str(out))
    row = next(csv.DictReader(out.open(encoding='utf-8-sig')))
    assert row['requires_review'] == '1' and row['treatment'] == ''
    recs[0].confirm()
    export.write_biometry_csv(recs, str(out))
    assert next(csv.DictReader(out.open(encoding='utf-8-sig')))['requires_review'] == '0'


def test_batch_reports_failures_and_deduplicates(esx_file, tmp_path):
    bad = tmp_path / 'bad.esx'; bad.write_text('not XML')
    out = tmp_path / 'out'
    assert len(collect_files([esx_file, esx_file])) == 1
    assert main(['run', esx_file, str(bad), '--out', str(out)]) == 1
    report = json.loads((out / 'batch_report.json').read_text())
    assert report['eyes'] == 2 and len(report['failures']) == 1
    assert (out / 'biometry.csv').exists()


def test_truncated_and_wrong_length_rejected(esx_file, tmp_path):
    text = open(esx_file).read()
    p = tmp_path / 'partial.esx'; p.write_text(text[:-8])
    with pytest.raises(esx.EsxError):
        esx.load_esx(str(p))
    p.write_text(text.replace('<SCANLENGTH>59375', '<SCANLENGTH>59374'))
    with pytest.raises(esx.EsxError, match='length mismatch'):
        esx.load_esx(str(p))


def test_same_filename_review_isolation_and_invalid_review(esx_file, tmp_path):
    a = session.process_file(esx_file)
    b = session.process_file(esx_file)
    b[0].source = str(tmp_path / 'elsewhere' / esx_file.split(chr(92))[-1].split('/')[-1])
    assert session.review_path(str(tmp_path), a[0].source) != session.review_path(str(tmp_path), b[0].source)
    a[0].confirm()
    p = session.save_review(a, str(tmp_path))[0]
    doc = json.loads(open(p).read()); doc['eyes'][0]['x'][0] = 9999999
    open(p, 'w').write(json.dumps(doc))
    assert session.apply_review(session.process_file(esx_file), str(tmp_path)) == 0
