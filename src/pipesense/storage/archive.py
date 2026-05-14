"""SQLite archive writer — one row per TagReading in the readings table.
Developed to handle multiple sites simultaneously (sites are marked by site_id)"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pipesense.sources.base import TagReading


# DDL run once at connection time, the pattern low is how the data will be stored in the DB
_CREATE_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT    NOT NULL,
    site_id  TEXT    NOT NULL,
    tag_id   TEXT    NOT NULL,
    ts       REAL    NOT NULL,
    value    REAL    NOT NULL,
    quality  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_tag_run
    ON readings (tag_id, run_id);
"""

# TagReading.quality uses OPC-UA capitalised convention
QUALITY_MAP: dict[str, int] = {"Good": 0, "Bad": 1, "Uncertain": 2}


class ArchiveWriter:
    """Inserts TagReadings into the SQLite readings table.

    Usage:
        with ArchiveWriter("data/pipesense.db", run_id="run_001") as aw:
            aw.write(reading)
    """

    def __init__(self, path: Path, site_id: str = "unknown", run_id: Optional[str] = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or f"run_{int(time.time())}"
        self.site_id = site_id
        self._conn: Optional[sqlite3.Connection] = None

    def open(self) -> "ArchiveWriter":
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_CREATE_READINGS)
        self._conn.commit()
        
        # Print statement to confirm the database opened and the readings table was initialised
        # shows path and run_id that will tag every row this session
        # print(f"[ArchiveWriter] opened  db={self.path}  run_id={self.run_id!r}")
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None
            
            # Print statement to confirm the final DB write and connection close
            # verifies no rows are lost before the process exits
            # print(f"[ArchiveWriter] committed and closed  db={self.path}")

    def __enter__(self) -> "ArchiveWriter":
        return self.open()

    def __exit__(self, *_) -> None:
        self.close()

    def write(self, reading: TagReading) -> None:
        if self._conn is None:
            raise RuntimeError(
                "ArchiveWriter is not open — use as a context manager"
            )

        # TagReading.timestamp is a datetime — convert to Unix epoch (float)
        if isinstance(reading.timestamp, datetime):
            ts = reading.timestamp.timestamp()
        else:
            ts = float(reading.timestamp)

        quality_code = QUALITY_MAP.get(reading.quality, 2)

        # Print statement to show each row before it is inserted — tag, value, Unix epoch timestamp (float), and encoded quality code
        # enable to confirm all channels are writing
        # print(
        #     f"[ArchiveWriter] insert  tag={reading.tag_id!r}"
        #     f"  value={reading.value:.4f}  ts={ts:.3f}"
        #     f"  quality={reading.quality!r} -> {quality_code}"
        # )

        self._conn.execute(
            "INSERT INTO readings (run_id, site_id, tag_id, ts, value, quality) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self.run_id, self.site_id, reading.tag_id, ts, float(reading.value), quality_code),
        )
        self._conn.commit()

    def write_batch(self, readings: List[TagReading]) -> None:
        for r in readings:
            self.write(r)
        self._conn.commit()

    def flush(self) -> None:
        """Commit pending rows without closing."""
        if self._conn is not None:
            self._conn.commit()
            # Print statement to confirm a mid-session commit — useful when you want to query the DB 
            # from a second connection while the writer is still running
            # print(f"[ArchiveWriter] flushed (mid-session commit)  db={self.path}")