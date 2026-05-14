"""Tests for archive writer."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from pipesense.sources.base import TagReading
from pipesense.storage.archive import ArchiveWriter, QUALITY_MAP


def _reading(
    tag: str = "FT-101",
    value: float = 100.0,
    quality: str = "Good",
) -> TagReading:
    """Real datetime timestamp — matches how the poll loop constructs readings."""
    return TagReading(
        tag_id=tag,
        value=value,
        timestamp=datetime.now(timezone.utc),
        quality=quality,
    )


def _rows(db_path, sql, params=()):
    """Open a fresh read-only connection and return all matching rows."""
    connection = sqlite3.connect(db_path)
    try:    
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()
    

@pytest.fixture
def tmp_db(tmp_path):
    aw = ArchiveWriter(tmp_path / "test.db", run_id="test_run", site_id="LACT-001")
    # Print statement to show the tmp_path pytest chose — open test.db here with 'sqlite3 ' or DB Browser for SQLite when an assertion fails
    # print(f"[fixture] tmp_db path: {aw.path}")
    return aw


def test_open_creates_readings_table(tmp_db):
    with tmp_db:
        pass
    conn = sqlite3.connect(tmp_db.path)
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    assert ("readings",) in tables


def test_write_inserts_one_row(tmp_db):
    with tmp_db as aw:
        aw.write(_reading(value=42.0))
    rows = _rows(tmp_db.path, "SELECT tag_id, value FROM readings")
    # Print statement to dump the raw row returned by SELECT — shows every column value before individual field assertions run
    # print(f"[test] raw row: {rows}")
    assert len(rows) == 1
    assert rows[0][0] == "FT-101"
    assert abs(rows[0][1] - 42.0) < 1e-9


def test_write_appends_multiple_rows(tmp_db):
    with tmp_db as aw:
        aw.write(_reading(value=1.0))
        aw.write(_reading(value=2.0))
    rows = _rows(tmp_db.path, "SELECT value FROM readings ORDER BY id")
    assert len(rows) == 2
    assert abs(rows[0][0] - 1.0) < 1e-9
    assert abs(rows[1][0] - 2.0) < 1e-9


def test_datetime_stored_as_unix_float(tmp_db):
    dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    r = TagReading(tag_id="FT-101", value=1.0, timestamp=dt, quality="Good")
    with tmp_db as aw:
        aw.write(r)
    rows = _rows(tmp_db.path, "SELECT ts FROM readings")
    assert abs(rows[0][0] - dt.timestamp()) < 0.001


def test_quality_encoding_capitalised(tmp_db):
    """Good/Bad/Uncertain — OPC-UA capitalised, not lowercase."""
    with tmp_db as aw:
        aw.write(_reading(quality="Good"))
        aw.write(_reading(quality="Bad"))
        aw.write(_reading(quality="Uncertain"))
    rows = _rows(tmp_db.path, "SELECT quality FROM readings ORDER BY id")
    assert [r[0] for r in rows] == [0, 1, 2]


def test_unknown_quality_maps_to_uncertain(tmp_db):
    with tmp_db as aw:
        aw.write(_reading(quality="Timeout"))
    rows = _rows(tmp_db.path, "SELECT quality FROM readings")
    assert rows[0][0] == 2


def test_site_id_stored_on_every_row(tmp_db):
    with tmp_db as aw:
        aw.write(_reading())
    rows = _rows(tmp_db.path, "SELECT site_id FROM readings")
    assert rows[0][0] == "LACT-001"


def test_run_id_stored_on_every_row(tmp_db):
    with tmp_db as aw:
        aw.write(_reading())
    rows = _rows(tmp_db.path, "SELECT run_id FROM readings")
    assert rows[0][0] == "test_run"


def test_multi_tag_rows_isolated(tmp_db):
    with tmp_db as aw:
        aw.write(_reading(tag="FT-101", value=10.0))
        aw.write(_reading(tag="PT-201", value=50.0))
    rows = _rows(tmp_db.path, "SELECT tag_id, value FROM readings ORDER BY id")
    assert rows[0] == ("FT-101", 10.0)
    assert rows[1] == ("PT-201", 50.0)


def test_write_batch_inserts_all(tmp_db):
    readings = [_reading(value=float(i)) for i in range(5)]
    with tmp_db as aw:
        aw.write_batch(readings)
    count = _rows(tmp_db.path, "SELECT COUNT(*) FROM readings")[0][0]
    assert count == 5


def test_context_manager_closes_connection(tmp_db):
    with tmp_db:
        pass
    assert tmp_db._conn is None


def test_write_without_open_raises(tmp_db):
    with pytest.raises(RuntimeError, match="not open"):
        tmp_db.write(_reading())


def test_default_run_id_prefixed(tmp_path):
    aw = ArchiveWriter(tmp_path / "x.db")
    assert aw.run_id.startswith("run_")