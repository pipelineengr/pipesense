"""PI historian DataSource — loads archived tag data from CSV exports."""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipesense.config.schema import SiteConfig
from pipesense.sources.base import DataSource, SourceStatus, TagReading

logger = logging.getLogger(__name__)


class PIHistorianSource(DataSource):
    """Load all CSVs created by pi_source.py and serves them as a DataSource for analysis.

    This is the baseline reference source — it can be used to compare live OPC-UA
    readings against historical PI data to detect any anomalies.
    """

    def __init__(self, site: SiteConfig, export_dir: str | Path) -> None:
        self._site = site
        self._export_dir = Path(export_dir)
        self._data: dict[str, pd.DataFrame] = {}
        self._connected = False
        self._last_error: str | None = None
        self._tag_to_channel: dict[str, str] = {
            ch.pi_tag: ch.id for ch in site.channels
        }
        self._channel_to_tag: dict[str, str] = {
            ch.id: ch.pi_tag for ch in site.channels
        }

        # [INIT] Print statement to see the tag resolution maps at creation.
        # These maps are how PI tag names resolve to channel IDs.
        # print(f"[INIT] PIHistorianSource created: site={site.id!r} "
        #       f"export_dir={self._export_dir}")
        # print(f"[INIT] tag→channel map: {self._tag_to_channel}")
        # print(f"[INIT] channel→tag map: {self._channel_to_tag}")

    async def connect(self) -> None:
        """Load all CSVs created by pi_source.py into memory."""
        # [PI] Print statement to see the connect/load process start.
        # print(f"[PI] PIHistorianSource connecting — loading CSVs from "
        #       f"{self._export_dir}")

        loaded = 0
        for ch in self._site.channels:
            fname = f"{ch.pi_tag.replace('.', '_')}.csv"
            path = self._export_dir / fname

            if not path.exists():
                # [PI] Print statement to catch missing PI export files.
                # print(f"[PI] WARNING: export file not found: {path}")
                continue

            try:
                df = pd.read_csv(path, parse_dates=["Timestamp"])
                df = df.sort_values("Timestamp").reset_index(drop=True)
                df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
                self._data[ch.id] = df
                loaded += 1

            except Exception as exc:
                self._last_error = str(exc)
                # [PI] Print statement to see CSV load failures in detail, if there are any.
                # print(f"[PI] ERROR loading {path}: {type(exc).__name__}: {exc}")

        self._connected = loaded > 0

        # [PI] Print statement to see the final connect summary.
        # print(f"[PI] connect complete: {loaded}/{len(self._site.channels)} "
        #       f"tags loaded connected={self._connected}")

    async def disconnect(self) -> None:
        # [PI] Print statement to confirm data is cleared on disconnect.
        # print(f"[PI] PIHistorianSource disconnecting — "
        #       f"clearing {len(self._data)} DataFrames")
        self._data.clear()
        self._connected = False

    async def read_tag(self, tag_id: str) -> TagReading:
        """Return the most recent archived value for this channel."""
        channel_id = self._resolve(tag_id)

        df = self._data.get(channel_id)
        if df is None or df.empty:
            # [READ] Print statement to catch missing channel lookups.
            # print(f"[READ] pi read_tag: no data for channel={channel_id!r}")
            return TagReading.bad(tag_id, reason="No PI data")

        last_row = df.iloc[-1]
        quality = str(last_row.get("Quality", "Good"))
        reading = TagReading(
            tag_id=channel_id,
            value=float(last_row["Value"]),
            timestamp=last_row["Timestamp"].to_pydatetime(),
            quality=quality,
        )

        # [READ] Print statement to see the last archived value being returned.
        # print(f"[READ] pi latest: channel={channel_id!r} "
        #       f"value={reading.value:.4f} ts={reading.timestamp.isoformat()}")

        return reading

    async def read_at(
        self, channel_id: str, timestamp: datetime
    ) -> TagReading:
        """Return the archived value closest to the given timestamp."""
        df = self._data.get(channel_id)
        if df is None or df.empty:
            return TagReading.bad(channel_id, reason="No PI data")

        ts = pd.Timestamp(timestamp)
        idx = (df["Timestamp"] - ts).abs().idxmin()
        row = df.iloc[idx]
        delta = abs((df["Timestamp"].iloc[idx] - ts).total_seconds())

        # [PI] Print statement to see point-in-time lookups with how close
        # the nearest archived value is to the requested timestamp.
        # print(f"[PI] read_at: channel={channel_id!r} "
        #       f"requested={timestamp.isoformat()} "
        #       f"nearest_delta={delta:.1f}s "
        #       f"value={float(row['Value']):.4f}")

        return TagReading(
            tag_id=channel_id,
            value=float(row["Value"]),
            timestamp=row["Timestamp"].to_pydatetime(),
            quality=str(row.get("Quality", "Good")),
        )

    async def read_range(
        self,
        channel_id: str,
        start: datetime,
        end: datetime,
    ) -> list[TagReading]:
        """Return all archived values between start and end timestamps."""
        df = self._data.get(channel_id)
        if df is None or df.empty:
            return []

        mask = (
            (df["Timestamp"] >= pd.Timestamp(start)) &
            (df["Timestamp"] <= pd.Timestamp(end))
        )
        subset = df[mask]

        # [PI] Print statement to see range queries and how many rows they return.
        # similar to querying a PI DA for data.
        # print(f"[PI] read_range: channel={channel_id!r} "
        #       f"start={start.isoformat()} end={end.isoformat()} "
        #       f"→ {len(subset)} rows returned")

        return [
            TagReading(
                tag_id=channel_id,
                value=float(row["Value"]),
                timestamp=row["Timestamp"].to_pydatetime(),
                quality=str(row.get("Quality", "Good")),
            )
            for _, row in subset.iterrows()
        ]

    async def read_tags(self, tag_ids: list[str]) -> list[TagReading]:
        # [READ] Print statement to see batch reads on the PI source.
        # print(f"[READ] pi read_tags: {len(tag_ids)} tags requested")
        results = []
        for tag_id in tag_ids:
            results.append(await self.read_tag(tag_id))
        return results

    def status(self) -> SourceStatus:
        return SourceStatus(
            connected=self._connected,
            source_type="PI Historian",         #Source name for the generated PI data
            endpoint=str(self._export_dir),
            n_tags=len(self._data),
            last_error=self._last_error,
        )

    def _resolve(self, tag_id: str) -> str:
        """Resolve OPC node or PI tag name to channel_id."""
        if tag_id in self._data:
            return tag_id
        if tag_id in self._tag_to_channel:
            resolved = self._tag_to_channel[tag_id]
            # [PI] Print statement to see PI tag name → channel_id resolution.
            # print(f"[PI] _resolve: pi_tag={tag_id!r} → channel={resolved!r}")
            return resolved
        for ch in self._site.channels:
            if ch.opc_node == tag_id:
                # [PI] Print statement to see OPC node → channel_id resolution.
                # print(f"[PI] _resolve: opc_node={tag_id!r} → channel={ch.id!r}")
                return ch.id
        # [PI] Print statement to catch unresolvable tag IDs.
        # print(f"[PI] _resolve: could not resolve {tag_id!r} — returning as-is")
        return tag_id