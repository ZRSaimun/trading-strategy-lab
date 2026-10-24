"""Deterministic synthetic data-quality checks, never real vendor data."""
import sqlite3
from pathlib import Path
import pytest
from app.data_quality_research import scan_database


def fixture(tmp_path: Path) -> Path:
    p=tmp_path/'test.sqlite'
    db=sqlite3.connect(str(p))
    db.executescript('''CREATE TABLE historical_datasets (
       id TEXT PRIMARY KEY, provider TEXT, instrument TEXT, format TEXT, state TEXT,
       archive_sha256 TEXT, accepted INTEGER, rejected INTEGER, zero_volume INTEGER,
       archive_filename TEXT, utc_offset_minutes INTEGER);
       CREATE TABLE historical_candles (
       dataset_id TEXT, time INTEGER, open FLOAT, high FLOAT, low FLOAT, close FLOAT, volume FLOAT);
       INSERT INTO historical_datasets VALUES
         ('d1','HistData','NSXUSD-CFD','ascii','READY','hash1',2,1,2,'a.zip',-300),
         ('d2','HistData','NSXUSD-CFD','ascii','READY','hash2',2,0,2,'b.zip',-300),
         ('d3','Other','NSXUSD-CFD','ascii','READY','hash3',1,0,1,'c.zip',0),
         ('d4','HistData','NSXUSD-CFD','mt','IMPORTING','hash4',1,0,1,'d.zip',-300);
       INSERT INTO historical_candles VALUES
         ('d1',0,100,105,99,103,0),('d1',60,103,110,101,104,0),
         ('d2',60,103,110,101,104,0),('d2',240,105,112,104,110,0),
         ('d3',60,999,1000,998,999,0),('d4',0,5,6,4,5,0);
    ''')
    db.commit();db.close()
    return p


def test_detects_exact_overlap_gap_and_preserves_provider(tmp_path):
    r=scan_database(str(fixture(tmp_path)))
    assert r['input']['nonready_dataset_count']==1
    assert r['summary']['source_rows']==5
    assert r['summary']['distinct_within_source_group_minutes']==4
    assert r['summary']['source_overlap_extra_rows']==1
    assert r['summary']['overlap_conflicts']==0
    h=next(x for x in r['groups'] if x['provider']=='HistData')
    assert h['unique_minutes']==3 and h['exact_overlap_rows']==1
    assert h['time_gaps_gt_1m']==1 and h['max_observed_gap_minutes']==2
    assert h['zero_volume_rows']==4


def test_fails_cleanly_on_nonsqlite(tmp_path):
    p=tmp_path/'bad.sqlite';p.write_text('invalid')
    with pytest.raises(ValueError, match='SQLite'):
        scan_database(str(p))


def test_only_reads_does_not_write(tmp_path):
    p=fixture(tmp_path)
    before=p.read_bytes()
    scan_database(str(p))
    assert p.read_bytes() == before


def test_conflicting_same_source_overlaps_are_separately_counted(tmp_path):
    p=fixture(tmp_path)
    with sqlite3.connect(str(p)) as db:
        db.execute("UPDATE historical_candles SET close=106 WHERE dataset_id='d2' AND time=60")
    r=scan_database(str(p))
    assert r['summary']['overlap_conflicts']==1
    assert r['summary']['source_overlap_extra_rows']==1

def test_different_declared_offsets_are_isolated(tmp_path):
    """A fixed-clock convention is part of source identity, not a display option."""
    p = fixture(tmp_path)
    with sqlite3.connect(str(p)) as db:
        db.execute(
            "INSERT INTO historical_datasets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ('d5', 'HistData', 'NSXUSD-CFD', 'ascii', 'READY',
             'hash5', 1, 0, 1, 'offset-zero.zip', 0),
        )
        # Same timestamp as d1/d2 but different declared clock convention:
        # it must not be counted as a conflicting same-source overlap.
        db.execute(
            "INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?)",
            ('d5', 60, 888, 889, 887, 888.5, 0),
        )
    r = scan_database(str(p))
    assert r['schema_version'] == 2
    groups = [g for g in r['groups']
              if g['provider'] == 'HistData' and g['format'] == 'ascii']
    assert len(groups) == 2
    assert {g['utc_offset_minutes'] for g in groups} == {-300, 0}
    assert r['summary']['source_overlap_extra_rows'] == 1  # d1/d2 only
    assert r['summary']['overlap_conflicts'] == 0
    assert r['summary']['distinct_within_source_group_minutes'] == 5
    assert r['summary']['accepted_count_mismatch'] == 0


def test_nonready_checkpoint_rows_are_not_misreported_as_ready_mismatches(tmp_path):
    p = fixture(tmp_path)
    r = scan_database(str(p))
    assert r['summary']['accepted_count_mismatch'] == 0
    group = next(g for g in r['groups']
                 if g['provider'] == 'HistData' and g['format'] == 'mt')
    assert group['ready_datasets'] == 0
    assert group['nonready_datasets'] == 1
    assert group['raw_rows'] == 0
    assert group['accepted_imported'] == 0
    assert group['nonready_accepted_imported'] == 1
    assert r['input']['nonready_dataset_count'] == 1


def test_offset_isolation_does_not_change_read_only_source(tmp_path):
    p = fixture(tmp_path)
    with sqlite3.connect(str(p)) as db:
        db.execute(
            "INSERT INTO historical_datasets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ('d5', 'HistData', 'NSXUSD-CFD', 'ascii', 'READY',
             'hash5', 0, 0, 0, 'offset-zero.zip', 0),
        )
    before = p.read_bytes()
    r = scan_database(str(p))
    assert p.read_bytes() == before
    assert len([g for g in r['groups'] if g['provider'] == 'HistData'
                and g['format'] == 'ascii']) == 2



def test_ready_dataset_reconciliation_catches_offsetting_count_errors(tmp_path):
    """Two broken archives must not appear valid because their group sum matches."""
    p = fixture(tmp_path)
    with sqlite3.connect(str(p)) as db:
        db.execute("DELETE FROM historical_candles WHERE dataset_id='d1' AND time=0")
        db.execute(
            "INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?)",
            ('d2', 300, 110, 112, 109, 111, 0),
        )
    before = p.read_bytes()
    r = scan_database(str(p))
    assert p.read_bytes() == before
    # The previous group-only comparison cannot detect these opposing errors.
    assert r['summary']['accepted_count_mismatch'] == 0
    assert r['summary']['ready_dataset_count_mismatch'] == 2
    manifest = {d['id']: d for d in r['dataset_manifest']}
    assert manifest['d1']['observed_ready_rows'] == 1
    assert manifest['d2']['observed_ready_rows'] == 3
    assert manifest['d1']['accepted_count_matches'] is False
    assert manifest['d2']['accepted_count_matches'] is False
    assert manifest['d3']['accepted_count_matches'] is True
    # An IMPORTING dataset is intentionally excluded from READY reconciliation.
    assert manifest['d4']['observed_ready_rows'] is None
    assert manifest['d4']['accepted_count_matches'] is None


def test_ready_dataset_reconciliation_detects_zero_observed_rows(tmp_path):
    p = fixture(tmp_path)
    with sqlite3.connect(str(p)) as db:
        db.execute("DELETE FROM historical_candles WHERE dataset_id='d1'")
    r = scan_database(str(p))
    assert r['summary']['ready_dataset_count_mismatch'] == 1
    manifest = {d['id']: d for d in r['dataset_manifest']}
    assert manifest['d1']['observed_ready_rows'] == 0
    assert manifest['d1']['accepted_count_matches'] is False
    assert manifest['d2']['accepted_count_matches'] is True
