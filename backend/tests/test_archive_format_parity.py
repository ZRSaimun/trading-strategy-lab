import zipfile
import pytest
from app.archive_format_parity import ParityInputError, compare_archives


def make_zip(tmp_path, name, rows, *, member='data.csv'):
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, rows)
    return path


def compare(tmp_path, ascii_rows, mt_rows, **kwargs):
    a = make_zip(tmp_path, 'ascii.zip', ascii_rows)
    b = make_zip(tmp_path, 'mt.zip', mt_rows)
    return compare_archives(a, b, instrument='XAUUSD-CFD', provider='HistData', **kwargs)


A = '20261022 100000;10;12;9;11;0\n20261022 100100;11;13;10;12;0\n'
M = '2026.10.22,10:00,10.000,12,9,11,0\n2026.10.22,10:01,11,13,10,12,0\n'


def test_exact_decimal_price_parity_and_no_certification(tmp_path):
    r = compare(tmp_path, A, M)
    assert r['status'] == 'EXACT_WALL_CLOCK_PRICE_PARITY'
    assert (r['aligned_minutes'], r['equal_ohlc_minutes']) == (2, 2)
    assert r['ascii_zero_volume_rows'] == r['mt_zero_volume_rows'] == 2
    assert not r['research_ready'] and not r['timebase_verified']


def test_price_conflict_never_silently_tolerated(tmp_path):
    r = compare(tmp_path, A, M.replace('10:01,11,13,10,12', '10:01,11,13,10,12.01'))
    assert r['status'] == 'PRICE_CONFLICT'
    assert r['conflicting_ohlc_minutes'] == 1
    assert r['samples'][-1]['kind'] == 'ohlc_conflict'


def test_partial_overlap_is_not_exact_parity(tmp_path):
    r = compare(tmp_path, A, '2026.10.22,10:01,11,13,10,12,0\n2026.10.22,10:02,11,13,10,12,0\n')
    assert (r['aligned_minutes'], r['ascii_only_minutes'], r['mt_only_minutes']) == (1, 1, 1)
    assert r['status'] == 'PARTIAL_WALL_CLOCK_PARITY'


@pytest.mark.parametrize('rows', [
    '20261022 100000;10;12;9;11;0\n20261022 100000;10;12;9;11;0\n',
    '20261022 100100;10;12;9;11;0\n20261022 100000;10;12;9;11;0\n',
    '20261022 100030;10;12;9;11;0\n',
    '20261022 100000;NaN;12;9;11;0\n',
    '20261022 100000;10;8;9;11;0\n',
    '20261022 100000;10;12;9;11;-1\n',
    '20261022 100000;10;12;9;11\n',
    '',
])
def test_bad_ascii_rejected_without_partial_success(tmp_path, rows):
    with pytest.raises(ParityInputError):
        compare(tmp_path, rows, M)


def test_bad_mt_order_rejected(tmp_path):
    with pytest.raises(ParityInputError, match='duplicate or backward'):
        compare(tmp_path, A, M + '2026.10.22,10:00,10,12,9,11,0\n')


def test_negative_oil_price_is_valid(tmp_path):
    r = compare(tmp_path, '20200420 142900;-35;-30;-41;-38;0\n',
                '2020.04.20,14:29,-35,-30,-41,-38,0\n')
    assert r['equal_ohlc_minutes'] == 1


def test_distinct_files_and_identity_required(tmp_path):
    a = make_zip(tmp_path, 'a.zip', A)
    with pytest.raises(ParityInputError, match='distinct'):
        compare_archives(a, a, instrument='XAUUSD', provider='HistData')
    b = make_zip(tmp_path, 'b.zip', M)
    with pytest.raises(ParityInputError, match='provider'):
        compare_archives(a, b, instrument='XAUUSD', provider='')


def test_row_and_byte_budgets_fail_closed(tmp_path):
    with pytest.raises(ParityInputError, match='row budget'):
        compare(tmp_path, A, M, max_rows=1)
    with pytest.raises(ParityInputError, match='byte budget'):
        compare(tmp_path, A, M, max_uncompressed_bytes=1)


def test_multi_member_and_unsupported_member_fail_closed(tmp_path):
    a = make_zip(tmp_path, 'a.zip', A)
    b = make_zip(tmp_path, 'b.zip', M)
    with zipfile.ZipFile(a, 'a') as z:
        z.writestr('second.csv', A)
    with pytest.raises(ParityInputError, match='exactly one'):
        compare_archives(a, b, instrument='XAUUSD', provider='HistData')
    c = make_zip(tmp_path, 'c.zip', M, member='not_csv.txt')
    with pytest.raises(ParityInputError, match='unsupported'):
        compare_archives(make_zip(tmp_path, 'ascii_only.zip', A), c, instrument='XAUUSD', provider='HistData')


def test_corrupt_zip_and_crc_failure_are_not_success(tmp_path):
    a = make_zip(tmp_path, 'a.zip', A)
    b = tmp_path / 'corrupt.zip'
    b.write_bytes(b'not a zip')
    with pytest.raises(zipfile.BadZipFile):
        compare_archives(a, b, instrument='XAUUSD', provider='HistData')


def test_sample_budget_zero_and_bounded(tmp_path):
    r = compare(tmp_path, A, M.replace('10:01,11,13,10,12', '10:01,11,13,10,12.01'), max_samples=0)
    assert r['samples'] == [] and r['conflicting_ohlc_minutes'] == 1
    with pytest.raises(ParityInputError):
        compare(tmp_path, A, M, max_samples=101)


def test_differing_volume_not_price_conflict(tmp_path):
    r = compare(tmp_path, A, M.replace(',0\n', ',8\n'))
    assert r['equal_ohlc_minutes'] == 2
    assert r['mt_zero_volume_rows'] == 0


def test_no_shared_wall_clock_minutes(tmp_path):
    r = compare(tmp_path, A, '2026.10.23,10:00,10,12,9,11,0\n')
    assert r['status'] == 'NO_SHARED_WALL_CLOCK_MINUTES'
    assert r['aligned_minutes'] == 0 and not r['research_ready']


def test_noncanonical_timestamp_rejected(tmp_path):
    with pytest.raises(ParityInputError, match='noncanonical ASCII'):
        compare(tmp_path, '20261022 1000;10;12;9;11;0\n', M)
    with pytest.raises(ParityInputError, match='noncanonical MT'):
        compare(tmp_path, A, '2026.10.22,1:00,10,12,9,11,0\n')


def test_crc_corruption_fails_closed(tmp_path):
    a = make_zip(tmp_path, 'ascii.zip', A)
    b = tmp_path / 'mt.zip'
    with zipfile.ZipFile(b, 'w', compression=zipfile.ZIP_STORED) as z:
        z.writestr('data.csv', M)
    raw = b.read_bytes()
    # Mutate one payload byte while leaving the ZIP central-directory CRC intact.
    pos = raw.index(M.encode())
    b.write_bytes(raw[:pos] + b'X' + raw[pos + 1:])
    with pytest.raises((zipfile.BadZipFile, ParityInputError)):
        compare_archives(a, b, instrument='XAUUSD', provider='HistData')
