import zipfile
import pytest
from app.archive_validation import inspect_archive


def archive(tmp_path, text):
    path = tmp_path / 'sample.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('sample.csv', text)
    return path


def inspect(path, **kw):
    return inspect_archive(path, instrument='NSXUSD-CFD', provider='HistData', utc_offset_minutes=-300, **kw)


def test_quality_and_provenance(tmp_path):
    p = archive(tmp_path, '20160104 100000;10;12;9;11;0\n20160104 100000;10;12;9;11;0\n20160104 095900;10;12;9;11;0\n20160104 100200;10;12;9;11;1\n20160104 100300;10;8;9;11;1\n')
    r = inspect(p)
    assert (r['rows'], r['valid_rows'], r['quarantined_rows']) == (5, 2, 3)
    assert r['issues'] == {'duplicate_timestamp': 1, 'backward_timestamp': 1, 'invalid_ohlcv': 1}
    assert r['gap_events'] == 1
    assert len(r['sha256']) == 64
    assert r['start'] == 1451919600  # 10:00 fixed UTC-5 -> 15:00 UTC
    assert inspect(p) == r


def test_resource_limits(tmp_path):
    p = archive(tmp_path, '20160104 100000;10;12;9;11;0\n')
    with pytest.raises(ValueError, match='resource'):
        inspect(p, max_uncompressed_bytes=1)
    with pytest.raises(ValueError, match='row budget'):
        inspect(p, max_rows=0)


def test_bad_values(tmp_path):
    p = archive(tmp_path, 'bad\n20160104 100000;nan;12;9;11;0\n')
    r = inspect(p)
    assert r['valid_rows'] == 0
    assert r['quarantined_rows'] == 2


def test_mt_fixed_est_in_summer(tmp_path):
    p = archive(tmp_path, '2016.07.04,10:00,10,12,9,11,0\n')
    r = inspect(p, data_format='mt')
    from datetime import datetime, timezone
    assert r['start'] == int(datetime(2016, 7, 4, 15, tzinfo=timezone.utc).timestamp())
    assert r['valid_rows'] == 1
    assert r['price_side'] == 'bid'


def test_negative_oil_prices_are_not_discarded(tmp_path):
    p = archive(tmp_path, '20200420 142900;-35;-30;-41;-38;0\n')
    r = inspect_archive(p, instrument='CL-202005-NYMEX', provider='synthetic-fixture', utc_offset_minutes=-300)
    assert r['valid_rows'] == 1 and r['quarantined_rows'] == 0


def test_corrupt_zip_fails_instead_of_reporting_success(tmp_path):
    p = tmp_path / 'corrupt.zip'
    p.write_bytes(b'not a zip archive')
    with pytest.raises(zipfile.BadZipFile):
        inspect(p)


def test_issue_samples_remain_bounded(tmp_path):
    p = archive(tmp_path, 'bad\n' * 1001)
    r = inspect(p)
    assert r['quarantined_rows'] == 1001
    assert len(r['samples']) == 100
