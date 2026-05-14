"""Tests for end to end integration: simulators -> DetectionEngine -> ArchiveWriter + AlarmLog (SQLite)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from pipesense.config.loader import load_config
from pipesense.detection.base import AlarmEvent, AlarmSeverity
from pipesense.detection.engine import DetectionEngine
from pipesense.sources.base import TagReading
from pipesense.sources.simulate import CHANNEL_SIMULATORS
from pipesense.storage.alarm_log import AlarmLog
from pipesense.storage.archive import ArchiveWriter

CONFIG_PATH = "config/site_default.yaml"
N_CYCLES    = 30
RUN_ID      = "e2e_test"
SITE_ID     = "LACT-001"


def _rows(db, sql, params=()):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture
def pipeline(tmp_path):
    cfg  = load_config(CONFIG_PATH)
    site = cfg.sites[0]
    db   = tmp_path / "PipesenseStorage.db"

    # Print statement to show the tmp_path pytest assigned — open PipesenseStorage.db 
    # here with 'sqlite3' or DB Browser for SQLite when an assertion fails
    # print(f"[fixture] db={db}")

    return site, db


def _run_cycles(site, db, n=N_CYCLES) -> list[AlarmEvent]:
    engine = DetectionEngine(site)
    events: list[AlarmEvent] = []
    now = datetime.now(timezone.utc)
    with ArchiveWriter(db, run_id=RUN_ID, site_id=SITE_ID) as archive, \
         AlarmLog(db,      run_id=RUN_ID, site_id=SITE_ID) as alarm_log:
        for _ in range(n):
            for ch in site.channels:
                sim_fn = CHANNEL_SIMULATORS.get(ch.type)
                if sim_fn is None:
                    continue
                reading = TagReading(
                    tag_id=ch.id, value=sim_fn(),
                    timestamp=now, quality="Good", unit=ch.unit,
                )
                archive.write(reading)
                for event in engine.process(reading):
                    alarm_log.append(event)
                    events.append(event)

    # Print statement to report how many alarm events fired and total readings written
    # zero alarms is valid during warm-up but worth confirming before asserting on the alarms table
    # r_count = _rows(db, "SELECT COUNT(*) FROM readings")[0][0]
    # print(f"[run_cycles] {n} cycles — readings={r_count}  alarms={len(events)}")
    return events


# ── readings table ────────────────────────────────────────────────────────────

def test_all_channels_have_rows(pipeline):
    site, db = pipeline
    _run_cycles(site, db)
    for ch in site.channels:
        count = _rows(db,
            "SELECT COUNT(*) FROM readings WHERE tag_id=? AND run_id=? AND site_id=?",
            (ch.id, RUN_ID, SITE_ID))[0][0]
        assert count == N_CYCLES, f"{ch.id}: expected {N_CYCLES} rows, got {count}"


def test_total_reading_row_count(pipeline):
    site, db = pipeline
    _run_cycles(site, db)
    total = _rows(db,
        "SELECT COUNT(*) FROM readings WHERE run_id=? AND site_id=?",
        (RUN_ID, SITE_ID))[0][0]
    assert total == N_CYCLES * len(site.channels)


def test_timestamps_are_unix_floats(pipeline):
    site, db = pipeline
    _run_cycles(site, db)
    rows = _rows(db, "SELECT ts FROM readings WHERE run_id=? LIMIT 5", (RUN_ID,))
    for (ts,) in rows:
        assert isinstance(ts, float) and ts > 0


def test_quality_codes_are_valid(pipeline):
    site, db = pipeline
    _run_cycles(site, db)
    rows = _rows(db, "SELECT DISTINCT quality FROM readings WHERE run_id=?", (RUN_ID,))
    for (q,) in rows:
        assert q in (0, 1, 2)


def test_site_id_on_every_reading(pipeline):
    site, db = pipeline
    _run_cycles(site, db)
    bad = _rows(db,
        "SELECT COUNT(*) FROM readings WHERE run_id=? AND site_id != ?",
        (RUN_ID, SITE_ID))[0][0]
    assert bad == 0


def test_alarm_rows_have_correct_columns(pipeline):
    site, db = pipeline
    events = _run_cycles(site, db, n=60)
    if not events:
        pytest.skip("No alarms fired — increase N_CYCLES or lower thresholds")
    rows = _rows(db,
        "SELECT severity, detector, value FROM alarms WHERE run_id=?", (RUN_ID,))
    for severity, detector, value in rows:
        assert severity in ("LOW", "HIGH", "CRITICAL")
        assert detector in ("spike", "drift")
        assert isinstance(value, float)


def test_detector_column_not_detector_type(pipeline):
    """Regression: column must be 'detector', never 'detector_type'."""
    site, db = pipeline
    _run_cycles(site, db)
    with sqlite3.connect(db) as conn:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(alarms)").fetchall()]
    assert "detector"      in cols
    assert "detector_type" not in cols


def test_alarm_count_matches_log(pipeline):
    site, db = pipeline
    events = _run_cycles(site, db, n=60)
    log_records = AlarmLog(db, run_id=RUN_ID, site_id=SITE_ID).read_all()
    assert len(events) == len(log_records)


def test_both_tables_in_same_db(pipeline):
    site, db = pipeline
    _run_cycles(site, db)
    
    # Print statement to show row counts in both tables after the run
    # confirms readings and alarms are in the same file and both tables received data
    # r = _rows(db, "SELECT COUNT(*) FROM readings")[0][0]
    # a = _rows(db, "SELECT COUNT(*) FROM alarms")[0][0]
    # print(f"[test] readings={r}  alarms={a}  db={db}")
    
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "readings" in tables
    assert "alarms"   in tables


def test_engine_reset_does_not_raise(pipeline):
    site, db = pipeline
    engine = DetectionEngine(site)
    _run_cycles(site, db)
    engine.reset()