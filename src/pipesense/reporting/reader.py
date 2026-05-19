"""Reads the SQLite DB created and write them as DataFrames,
the DF is then used to create a summary report for a run
(can be either for a single site or multiple sites)"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

# Inverse of ArchiveWriter.QUALITY_MAP — used for display only
QUALITY_DECODE: dict[int, str] = {0: "Good", 1: "Bad", 2: "Uncertain"}


class ArchiveReader:
    """Queries the DB archive table and returns a DataFrame per channel.
    Alarms has its own reader in alarm_log.py

    Usage:
        reader = ArchiveReader("data/PipesenseStorage.db", run_id="run_001", site_id="LACT-001")
        df  = reader.load()               # all channels in one DataFrame
        dfs = reader.load_by_channel()    # dict of tag_id -> DataFrame
    """

    def __init__(self, path: Path, run_id: str, site_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.site_id = site_id

        # [INIT] Confirm the three values that scope every SELECT in this reader
        # print(f"[ArchiveReader] init  db={self.path}  run_id={self.run_id!r}  site_id={self.site_id!r}")

        if not self.path.exists():
            raise FileNotFoundError(f"Archive database not found: {self.path}")

    def list_runs(self) -> list[str]:
        """Return all distinct run_ids stored in the readings table."""
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM readings ORDER BY run_id"
            ).fetchall()
        runs = [r[0] for r in rows]

        # [QUERY] Show every run_id found — useful when multiple runs exist and you need to pick one
        # print(f"[ArchiveReader] list_runs  found={runs}")

        return runs

    def load(self) -> pd.DataFrame:
        """Load all readings for this run_id and site_id into one DataFrame.

        Columns: id, run_id, site_id, tag_id, ts (datetime UTC), value, quality (int)
        """
        sql = (
            "SELECT id, run_id, site_id, tag_id, ts, value, quality "
            "FROM readings "
            "WHERE run_id = ? AND site_id = ? "
            "ORDER BY tag_id, ts"
        )

        # [QUERY] Show the SQL and bind params before execution
        # print(f"[ArchiveReader] load  sql={sql!r}  params=({self.run_id!r}, {self.site_id!r})")

        with closing(sqlite3.connect(self.path)) as conn:
            df = pd.read_sql(sql, conn, params=(self.run_id, self.site_id))

        # ts column is a Unix float — convert to timezone-aware datetime
        df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)

        # [QUERY] Show shape and dtypes — confirms ts converted and all channels have rows
        # print(f"[ArchiveReader] load  shape={df.shape}  dtypes=\n{df.dtypes}")

        return df

    def load_by_channel(self) -> dict[str, pd.DataFrame]:
        """Return a dict mapping tag_id -> DataFrame for that channel only."""
        df = self.load()
        result = {
            tag: group.reset_index(drop=True) for tag, group in df.groupby("tag_id")
        }

        # [QUERY] Show each channel's tag_id and row count after splitting
        # for tag, cdf in result.items():
        #     print(f"[ArchiveReader] load_by_channel  tag={tag!r}  rows={len(cdf)}")

        return result
