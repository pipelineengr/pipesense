import pytest
import sqlite3

from contextlib import closing
from datetime import datetime, timezone
from pipesense.config.loader import load_config
from pipesense.detection.base import AlarmEvent, AlarmSeverity
from pipesense.storage.alarm_log import AlarmLog


@pytest.fixture
def site():
    config = load_config("config/site_default.yaml")
    site = config.sites[0]

    # print(f"\n[FIXTURE] site loaded: id={site.id!r} name={site.name!r}")
    # print(f"[FIXTURE] channels: {[ch.id for ch in site.channels]}")
    # print(f"[FIXTURE] channel types: "
    #       f"{[(ch.id, ch.type) for ch in site.channels]}")

    return site


def _event(
    tag: str = "FT-101",
    sev: AlarmSeverity = AlarmSeverity.HIGH,
    detector: str = "spike",
    value: float = 300.0,
) -> AlarmEvent:
    """Correct AlarmEvent field names — 'detector' not 'detector_type'."""
    return AlarmEvent(
        tag_id=tag,
        severity=sev,
        detector=detector,
        value=value,
        timestamp=datetime.now(timezone.utc),
        message="test alarm",
    )


@pytest.fixture
def tmp_log(tmp_path):
    return AlarmLog(tmp_path / "test.db", run_id="test_run", site_id="LACT-001")


def test_open_creates_alarms_table(tmp_log):
    with tmp_log:
        pass
    connection = sqlite3.connect(tmp_log.path)
    try:
        tables = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        connection.close()
    assert "alarms" in tables


def test_append_inserts_correct_fields(tmp_log):
    with tmp_log as log:
        log.append(_event())
    records = tmp_log.read_all()
    assert len(records) == 1
    r = records[0]
    assert r["tag_id"]   == "FT-101"
    assert r["severity"] == "HIGH"
    assert r["detector"] == "spike"
    assert r["site_id"]  == "LACT-001"
    assert r["run_id"]   == "test_run"


def test_detector_field_not_detector_type(tmp_log):
    """Regression guard — column must be 'detector', never 'detector_type'."""
    with tmp_log as log:
        log.append(_event(detector="drift"))
    connection = sqlite3.connect(tmp_log.path)    
    try:
        cols = [c[1] for c in connection.execute("PRAGMA table_info(alarms)").fetchall()]
    finally:
        connection.close()
    assert "detector"      in cols
    assert "detector_type" not in cols


def test_severity_stored_as_uppercase_string(tmp_log):
    with tmp_log as log:
        log.append(_event(sev=AlarmSeverity.CRITICAL))
    assert tmp_log.read_all()[0]["severity"] == "CRITICAL"


def test_multiple_events_inserted(tmp_log):
    with tmp_log as log:
        log.append(_event(sev=AlarmSeverity.HIGH))
        log.append(_event(tag="PT-201", sev=AlarmSeverity.CRITICAL))
    assert len(tmp_log.read_all()) == 2


def test_read_by_severity(tmp_log):
    with tmp_log as log:
        log.append(_event(sev=AlarmSeverity.HIGH))
        log.append(_event(sev=AlarmSeverity.CRITICAL))
    highs = tmp_log.read_by_severity(AlarmSeverity.HIGH)
    assert len(highs) == 1 and highs[0]["severity"] == "HIGH"


def test_read_by_tag(tmp_log):
    with tmp_log as log:
        log.append(_event(tag="FT-101"))
        log.append(_event(tag="PT-201"))
    assert len(tmp_log.read_by_tag("FT-101")) == 1


def test_read_all_scoped_to_run_and_site(tmp_path):
    """Two AlarmLog instances with different run_ids must not see each other's rows."""
    db = tmp_path / "shared.db"
    with AlarmLog(db, run_id="run_A", site_id="LACT-001") as log:
        log.append(_event())
    with AlarmLog(db, run_id="run_B", site_id="LACT-001") as log:
        log.append(_event())
    assert len(AlarmLog(db, run_id="run_A", site_id="LACT-001").read_all()) == 1
    assert len(AlarmLog(db, run_id="run_B", site_id="LACT-001").read_all()) == 1


def test_write_without_open_raises(tmp_log):
    with pytest.raises(RuntimeError, match="not open"):
        tmp_log.append(_event())


def test_context_manager_closes_connection(tmp_log):
    with tmp_log as log:
        log.append(_event())
    assert tmp_log._connection is None


def test_read_all_missing_db_returns_empty(tmp_path):
    log = AlarmLog(tmp_path / "nonexistent.db", run_id="x", site_id="y")
    assert log.read_all() == []