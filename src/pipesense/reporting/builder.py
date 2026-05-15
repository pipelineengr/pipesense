"""Builder to calculate the statistics for the report from alarms and readings"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class ChannelStats:
    """Computed statistics for a channel over the run."""
    
    #From readings
    tag_id:           str
    sample_count:     int
    good_count:       int
    bad_count:        int
    uncertain_count:  int
    mean:             Optional[float] = None   
    std:              Optional[float] = None
    min:              Optional[float] = None
    max:              Optional[float] = None
    
    #From Alarms
    alarm_count:      int = 0
    alarm_by_severity: dict[str, int] = field(default_factory=dict)


@dataclass
class Report:
    """Full report for the run for each site."""
    run_id:        str
    site_id:       str
    channel_stats: dict[str, ChannelStats]   # keyed by tag_id
    total_alarms:  int
    generated_at:  str                        # Timestamp as ISO-8601 UTC string


class ReportBuilder:
    """Builds a Report from ArchiveReader DataFrames and AlarmLog records.

    Usage:
        reader   = ArchiveReader(db_path, run_id=run_id, site_id=site_id)
        alarmlog = AlarmLog(db_path, run_id=run_id, site_id=site_id)
        builder  = ReportBuilder(
            channel_dfs=reader.load_by_channel(),
            alarm_records=alarmlog.read_all(),
            run_id=run_id,
            site_id=site_id,
        )
        report = builder.build()
    """

    def __init__(
        self,
        channel_dfs:   dict[str, pd.DataFrame],
        alarm_records: list[dict],
        run_id:        str,
        site_id:       str,
    ) -> None:
        self.channel_dfs   = channel_dfs
        self.alarm_records = alarm_records
        self.run_id        = run_id
        self.site_id       = site_id

        # [INIT] Confirm what the builder received before any computation starts
        # print(f"[ReportBuilder] init  run_id={run_id!r}  site_id={site_id!r}  "
        #       f"channels={len(channel_dfs)}  alarm_records={len(alarm_records)}")

    def build(self) -> Report:
        alarm_counts = self._group_alarm_counts()
        stats = {
            tag_id: self._compute_stats(tag_id, df, alarm_counts)
            for tag_id, df in self.channel_dfs.items()
        }
        total = sum(s.alarm_count for s in stats.values())

        # [BUILD] Summary line before handing off to the writer
        # print(f"[ReportBuilder] build complete  channels={len(stats)}  total_alarms={total}")

        return Report(
            run_id=self.run_id,
            site_id=self.site_id,
            channel_stats=stats,
            total_alarms=total,
            generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        )

    def _compute_stats(
        self,
        tag_id:       str,
        df:           pd.DataFrame,
        alarm_counts: dict[str, dict[str, int]],
    ) -> ChannelStats:
        # quality column: 0=Good 1=Bad 2=Uncertain — matches ArchiveWriter.QUALITY_MAP
        good = df[df["quality"] == 0]["value"]
        bad_count  = int((df["quality"] == 1).sum())
        unc_count  = int((df["quality"] == 2).sum())

        if good.empty:
            # [WARN] Flag a channel where every reading was bad/uncertain
            # print(f"[ReportBuilder] WARNING  tag={tag_id!r} has no good-quality readings — stats will be None")
            mean = std = mn = mx = None
        else:
            mean = float(good.mean())
            std  = float(good.std(ddof=0))   # population std — consistent with numpy
            mn   = float(good.min())
            mx   = float(good.max())

        counts = alarm_counts.get(tag_id, {})

        # [STATS] Show computed values per channel before they go into the dataclass
        # print(f"[ReportBuilder] stats  tag={tag_id!r}  samples={len(df)}  good={len(good)}  "
        #       f"mean={mean}  std={std}  alarms={sum(counts.values())}")

        return ChannelStats(
            tag_id=tag_id,
            sample_count=len(df),
            good_count=len(good),
            bad_count=bad_count,
            uncertain_count=unc_count,
            mean=round(mean, 4) if mean is not None else None,
            std=round(std,  4) if std  is not None else None,
            min=round(mn,   4) if mn   is not None else None,
            max=round(mx,   4) if mx   is not None else None,
            alarm_count=sum(counts.values()),
            alarm_by_severity=counts,
        )

    def _group_alarm_counts(self) -> dict[str, dict[str, int]]:
        """Group alarm records by tag_id -> severity -> count."""
        counts: dict[str, dict[str, int]] = {}
        for record in self.alarm_records:
            tag = record.get("tag_id", "unknown")
            sev = record.get("severity", "unknown")
            counts.setdefault(tag, {})
            counts[tag][sev] = counts[tag].get(sev, 0) + 1

        # [ALARMS] Show the alarm count dict after grouping
        # print(f"[ReportBuilder] alarm counts by tag  {counts}")

        return counts