"""Unit tests for reader, builder and writer functions.
Each test here is done using a small SQLite DB created here
in the sample_db function"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipesense.reporting.reader import ArchiveReader
from pipesense.reporting.builder import Report, ReportBuilder
from pipesense.reporting.writer import ReportWriter
from pipesense.storage.archive import ArchiveWriter
from pipesense.storage.alarm_log import AlarmLog
from pipesense.sources.base import TagReading
from pipesense.detection.base import AlarmEvent, AlarmSeverity

RUN_ID  = "test_run_001"
SITE_ID = "LACT-001"
TAGS    = ["FT-101", "PT-201", "TT-301", "LT-401", "VT-501"]
N_ROWS  = 20   # readings per channel written by the fixture


@pytest.fixture
def sample_db(tmp_path) -> Path:
    """Write N_ROWS good readings per channel into a fresh SQLite DB,
    plus 3 alarms on FT-101 (2x HIGH, 1x CRITICAL).

    tmp_path is a pytest built-in that gives a unique temp directory per test.
    The DB only exists for the duration of the test that uses this fixture.
    """
    db  = tmp_path / "pipesense.db"
    now = datetime.now(timezone.utc)

    # Print Statement to see the exact path pytest assigned.
    # Open this file in a SQLite viewer when a test fails to inspect raw rows.
    # print(f"[fixture] sample_db path={db}")

    with ArchiveWriter(db, run_id=RUN_ID, site_id=SITE_ID) as aw:
        for i in range(N_ROWS):
            for tag in TAGS:
                aw.write(TagReading(
                    tag_id=tag,
                    value=float(100 + i),   # values 100.0 … 119.0
                    timestamp=now,
                    quality="Good",
                    unit="m3/h",
                ))

    # Print Statement to confirm alarm rows were written.
    # print(f"[fixture] writing 3 alarms on FT-101 (2x HIGH, 1x CRITICAL)")

    with AlarmLog(db, run_id=RUN_ID, site_id=SITE_ID) as log:
        for sev in [AlarmSeverity.HIGH, AlarmSeverity.HIGH, AlarmSeverity.CRITICAL]:
            log.append(AlarmEvent(
                tag_id="FT-101",
                severity=sev,
                detector="spike",
                value=200.0,
                timestamp=now,
                message="test alarm",
            ))

    return db


@pytest.fixture
def reader(sample_db) -> ArchiveReader:
    """ArchiveReader scoped to the sample_db fixture."""
    return ArchiveReader(sample_db, run_id=RUN_ID, site_id=SITE_ID)


@pytest.fixture
def report(sample_db) -> Report:
    """Fully built Report from the sample_db fixture — used by ReportBuilder and ReportWriter tests."""
    r      = ArchiveReader(sample_db, run_id=RUN_ID, site_id=SITE_ID)
    alarms = AlarmLog(sample_db, run_id=RUN_ID, site_id=SITE_ID).read_all()

    # Print Statement to see how many alarm records were loaded before the builder runs.
    # print(f"[fixture] report  alarm_records={len(alarms)}")

    return ReportBuilder(
        channel_dfs=r.load_by_channel(),
        alarm_records=alarms,
        run_id=RUN_ID,
        site_id=SITE_ID,
    ).build()


class TestArchiveReader:

    def test_list_runs_contains_run_id(self, reader):
        """list_runs() must return the run_id that was written by the fixture."""
        runs = reader.list_runs()

        # Print Statement to see all run_ids found in the DB.
        # print(f"[test] list_runs={runs}")

        assert RUN_ID in runs

    def test_load_returns_all_channels(self, reader):
        """load() should return rows for all five channels."""
        df = reader.load()

        # Print Statement to see which tag_ids came back.
        # print(f"[test] tag_ids in df={sorted(df['tag_id'].unique())}")

        assert set(df["tag_id"].unique()) == set(TAGS)

    def test_load_correct_total_row_count(self, reader):
        """Total rows = N_ROWS per channel × number of channels."""
        df = reader.load()

        # Print Statement to confirm total row count before asserting.
        # print(f"[test] total rows={len(df)}  expected={N_ROWS * len(TAGS)}")

        assert len(df) == N_ROWS * len(TAGS)

    def test_load_ts_is_datetime(self, reader):
        """ts column must be converted from Unix float to datetime by load()."""
        import pandas as pd
        df = reader.load()

        # Print Statement to see the dtype of the ts column.
        # print(f"[test] ts dtype={df['ts'].dtype}")

        assert pd.api.types.is_datetime64_any_dtype(df["ts"])

    def test_load_by_channel_keys(self, reader):
        """load_by_channel() must return one key per channel tag."""
        dfs = reader.load_by_channel()

        # Print Statement to see all keys returned by load_by_channel.
        # print(f"[test] load_by_channel keys={sorted(dfs.keys())}")

        assert set(dfs.keys()) == set(TAGS)

    def test_load_by_channel_row_count_per_tag(self, reader):
        """Each channel DataFrame must have exactly N_ROWS rows."""
        dfs = reader.load_by_channel()
        for tag, df in dfs.items():

            # Print Statement to see per-channel row counts.
            # print(f"[test] tag={tag!r}  rows={len(df)}")

            assert len(df) == N_ROWS, f"{tag}: expected {N_ROWS} rows, got {len(df)}"

    def test_missing_db_raises_file_not_found(self, tmp_path):
        """Constructing ArchiveReader with a non-existent path must raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ArchiveReader(tmp_path / "nonexistent.db", run_id=RUN_ID, site_id=SITE_ID)

    def test_unknown_run_id_returns_empty_df(self, sample_db):
        """Querying a run_id that doesn't exist must return an empty DataFrame, not raise."""
        r  = ArchiveReader(sample_db, run_id="no_such_run", site_id=SITE_ID)
        df = r.load()

        # Print Statement to confirm the DataFrame is truly empty.
        # print(f"[test] empty df shape={df.shape}")

        assert df.empty


class TestReportBuilder:

    def test_run_id_on_report(self, report):
        assert report.run_id == RUN_ID

    def test_site_id_on_report(self, report):
        assert report.site_id == SITE_ID

    def test_all_channels_present(self, report):
        """Every channel written by the fixture must appear in channel_stats."""

        # Print Statement to see which channels the builder produced.
        # print(f"[test] channel_stats keys={sorted(report.channel_stats.keys())}")

        assert set(report.channel_stats.keys()) == set(TAGS)

    def test_sample_count(self, report):
        """sample_count must equal the N_ROWS written by the fixture."""
        assert report.channel_stats["FT-101"].sample_count == N_ROWS

    def test_good_count(self, report):
        """All rows were written as Good quality so good_count must equal N_ROWS."""
        assert report.channel_stats["FT-101"].good_count == N_ROWS

    def test_bad_and_uncertain_counts_are_zero(self, report):
        assert report.channel_stats["FT-101"].bad_count       == 0
        assert report.channel_stats["FT-101"].uncertain_count == 0

    def test_mean_correct(self, report):
        """Mean of values 100.0…119.0 = 109.5."""
        import statistics
        expected = statistics.mean(float(100 + i) for i in range(N_ROWS))

        # Print Statement to compare computed vs expected mean.
        # print(f"[test] mean computed={report.channel_stats['FT-101'].mean}  expected={expected}")

        assert abs(report.channel_stats["FT-101"].mean - expected) < 1e-4

    def test_min_and_max(self, report):
        cs = report.channel_stats["FT-101"]
        assert cs.min == 100.0
        assert cs.max == 119.0

    def test_alarm_count_on_ft101(self, report):
        """FT-101 had 3 alarms written by the fixture."""

        # Print Statement to see the full alarm_by_severity breakdown.
        # print(f"[test] alarm_by_severity={report.channel_stats['FT-101'].alarm_by_severity}")

        assert report.channel_stats["FT-101"].alarm_count == 3

    def test_alarm_by_severity_breakdown(self, report):
        sev = report.channel_stats["FT-101"].alarm_by_severity
        assert sev.get("HIGH")     == 2
        assert sev.get("CRITICAL") == 1

    def test_total_alarms(self, report):
        assert report.total_alarms == 3

    def test_no_alarms_on_other_channels(self, report):
        """Only FT-101 had alarms — all other channels should have alarm_count=0."""
        for tag in ["PT-201", "TT-301", "LT-401", "VT-501"]:
            assert report.channel_stats[tag].alarm_count == 0, \
                f"{tag} unexpectedly has alarms"

    def test_bad_quality_produces_none_stats(self, sample_db):
        """A channel where every reading has Bad quality must produce None stats, not crash.
        This guards against a division-by-zero or empty-series error in _compute_stats.
        """
        now = datetime.now(timezone.utc)
        with ArchiveWriter(sample_db, run_id="bad_run", site_id=SITE_ID) as aw:
            aw.write(TagReading(
                tag_id="VT-501", value=0.0, timestamp=now, quality="Bad", unit="mm/s"
            ))

        r      = ArchiveReader(sample_db, run_id="bad_run", site_id=SITE_ID)
        alarms = AlarmLog(sample_db, run_id="bad_run", site_id=SITE_ID).read_all()
        bad_report = ReportBuilder(
            channel_dfs=r.load_by_channel(),
            alarm_records=alarms,
            run_id="bad_run",
            site_id=SITE_ID,
        ).build()

        cs = bad_report.channel_stats["VT-501"]

        # Print Statement to confirm the stats are None as expected.
        # print(f"[test] bad quality stats: mean={cs.mean}  std={cs.std}")

        assert cs.mean is None
        assert cs.std  is None


class TestReportWriter:

    def test_creates_file(self, report, tmp_path):
        """write() must create the output file on disk."""
        out = tmp_path / "reports" / "summary.md"
        ReportWriter(out).write(report)
        assert out.exists()

    def test_returns_string(self, report, tmp_path):
        """write() must return the rendered Markdown string."""
        md = ReportWriter(tmp_path / "out.md").write(report)
        assert isinstance(md, str) and len(md) > 0

    def test_contains_site_and_run(self, report, tmp_path):
        md = ReportWriter(tmp_path / "out.md").write(report)

        # Print Statement to eyeball the first 200 chars of the rendered output.
        # print(f"[test] md preview:\n{md[:200]}")

        assert SITE_ID in md
        assert RUN_ID  in md

    def test_contains_all_channel_tags(self, report, tmp_path):
        """Every channel tag_id must appear somewhere in the rendered Markdown."""
        md = ReportWriter(tmp_path / "out.md").write(report)
        for tag in TAGS:
            assert tag in md, f"Tag {tag!r} missing from rendered report"

    def test_alarm_severities_in_output(self, report, tmp_path):
        """HIGH and CRITICAL must appear in the Alarm Summary section."""
        md = ReportWriter(tmp_path / "out.md").write(report)
        assert "HIGH"     in md
        assert "CRITICAL" in md

    def test_no_alarms_message(self, sample_db, tmp_path):
        """When alarm_records=[] the writer must print the no-alarms message.
        This tests the else branch in render() that handles zero alarms.
        """
        r = ArchiveReader(sample_db, run_id=RUN_ID, site_id=SITE_ID)
        no_alarm_report = ReportBuilder(
            channel_dfs=r.load_by_channel(),
            alarm_records=[],    # ← explicitly empty
            run_id=RUN_ID,
            site_id=SITE_ID,
        ).build()
        md = ReportWriter(tmp_path / "out.md").write(no_alarm_report)

        # Print Statement to confirm the no-alarms message appears.
        # print(f"[test] no-alarm md snippet:\n{md[-200:]}")

        assert "No alarms recorded" in md

    def test_creates_parent_directories(self, report, tmp_path):
        """ReportWriter must create any missing parent directories automatically."""
        deep = tmp_path / "a" / "b" / "c" / "report.md"
        ReportWriter(deep).write(report)
        assert deep.exists()

    def test_markdown_headers_present(self, report, tmp_path):
        """The rendered output must contain the expected section headers."""
        md = ReportWriter(tmp_path / "out.md").write(report)
        assert "# Pipesense Site Report" in md
        assert "## Channel Statistics"   in md
        assert "## Alarm Summary"        in md