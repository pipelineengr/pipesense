"""SQLite alarm log — one row per AlarmEvent in the alarms table, writes to the same database as archive"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional
from contextlib import closing

from pipesense.detection.base import AlarmEvent, AlarmSeverity


_DDL = """
CREATE TABLE IF NOT EXISTS alarms (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT    NOT NULL,
    site_id   TEXT    NOT NULL,
    tag_id    TEXT    NOT NULL,
    ts        TEXT    NOT NULL,
    severity  TEXT    NOT NULL,
    detector  TEXT    NOT NULL,
    value     REAL    NOT NULL,
    message   TEXT    NOT NULL
);
"""


class AlarmLog:
    """Inserts AlarmEvents into the SQLite table.

    Shares the same database file as ArchiveWriter. Both classes must
    receive the same run_id so readings and alarms can be joined:

        SELECT r.value, a.severity
        FROM readings r JOIN alarms a
        ON r.run_id = a.run_id AND r.site_id = a.site_id AND r.tag_id = a.tag_id

    Usage:
        with AlarmLog("data/pipesense.db", run_id="r1", site_id="LACT-001") as log:
            log.append(event)
    """

    def __init__(
        self,
        path: Path,
        run_id: Optional[str] = None,
        site_id: str = "unknown",
    ) -> None:
        self.path    = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id  = run_id or f"run_{int(time.time())}"
        self.site_id = site_id
        self._connection: Optional[sqlite3.Connection] = None

    
    def open(self) -> "AlarmLog":
        self._connection = sqlite3.connect(self.path)
        
        # Print statement to confirm the database opened and show path, run_id, and site_id
        # pair with ArchiveWriter's open print to see both tables initialise together
        # print(f"[AlarmLog] opened  db={self.path}  run_id={self.run_id!r}  site_id={self.site_id!r}")
        
        self._connection.execute(_DDL)
        
        # Print statement to confirm the alarms DDL executed — only meaningful on the first open of a fresh database
        # print(f"[AlarmLog] DDL applied  tables: {[r[0] for r in self._conn.execute('SELECT name FROM sqlite_master WHERE type=?', ('table',)).fetchall()]}")
        
        self._connection.commit()
        return self

    def close(self) -> None:
        if self._connection is not None:
            self._connection.commit()
            self._connection.close()
            self._connection = None
            
            # Print statement to confirm the final commit and close — verifies no alarm rows are lost on shutdown
            # print(f"[AlarmLog] committed and closed  db={self.path}")

    def __enter__(self) -> "AlarmLog":
        return self.open()

    def __exit__(self, *_) -> None:
        self.close()

    
    def append(self, event: AlarmEvent) -> None:
        if self._connection is None:
            raise RuntimeError(
                "AlarmLog is not open — use as a context manager"
            )
        row = {
            "run_id":   self.run_id,
            "site_id":  self.site_id,
            "tag_id":   event.tag_id,
            "ts":       event.timestamp.isoformat(),
            "severity": event.severity.value,   # "LOW" / "HIGH" / "CRITICAL"
            "detector": event.detector,          # "spike" or "drift"
            "value":    round(event.value, 6),
            "message":  event.message,
        }
        
        # Print statement to show the exact dict being inserted, all fields visible 
        # before sqlite3 serialises them, including severity.value and event.detector
        # print(f"[AlarmLog] insert  {row}")
        
        self._connection.execute(
            "INSERT INTO alarms"
            " (run_id, site_id, tag_id, ts, severity, detector, value, message)"
            " VALUES (:run_id, :site_id, :tag_id, :ts, :severity, :detector, :value, :message)",
            row,
        )
        self._connection.commit()

    
    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        
        def _query(connection):
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM alarms WHERE run_id = ? AND site_id = ? ORDER BY id",
                (self.run_id, self.site_id),
            ).fetchall()
            return [dict(r) for r in rows]
        
        if self._connection is not None:
            return _query(self._connection)
        
        with closing(sqlite3.connect(self.path)) as connection:
            return _query(connection)
        
        # Print statement to show how many alarm rows were returned for this run_id and site_id
        # confirms the query is scoped correctly and catches missing entries
        # print(f"[AlarmLog] read_all  run_id={self.run_id!r}  site_id={self.site_id!r}  rows={len(result)}")

    def read_by_severity(self, severity: AlarmSeverity) -> list[dict]:
        return [r for r in self.read_all() if r.get("severity") == severity.value]

    def read_by_tag(self, tag_id: str) -> list[dict]:
        return [r for r in self.read_all() if r.get("tag_id") == tag_id]