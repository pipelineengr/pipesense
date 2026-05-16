"""End-to-end tests for the full reporting workflow:
simulators → DetectionEngine → ArchiveWriter/AlarmLog → ArchiveReader → ReportBuilder → ReportWriter

No mocks — everything runs against a real SQLite DB written by the actual run pipeline.
All created here for the tests
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipesense.config.loader import load_config
from pipesense.detection.engine import DetectionEngine
from pipesense.reporting.builder import ReportBuilder
from pipesense.reporting.reader import ArchiveReader
from pipesense.reporting.writer import ReportWriter
from pipesense.sources.base import TagReading
from pipesense.sources.simulate import CHANNEL_SIMULATORS
from pipesense.storage.alarm_log import AlarmLog
from pipesense.storage.archive import ArchiveWriter

CONFIG_PATH = "config/site_default.yaml"
N_CYCLES    = 30     # poll cycles — enough for detectors to accumulate samples
RUN_ID      = "report_e2e"
SITE_ID     = "LACT-001"


@pytest.fixture
def e2e_db(tmp_path) -> Path:
    """Run the full acquisition pipeline synchronously and return the DB path.

    Mimics what _run_async does in cli.py but synchronously so no asyncio needed:
      1. Load config → get site + channels
      2. Call each channel's simulator function to get a reading
      3. Write reading to ArchiveWriter
      4. Pass reading through DetectionEngine → write any alarms to AlarmLog
    """
    cfg  = load_config(CONFIG_PATH)
    site = cfg.sites[0]
    db   = tmp_path / "pipesense.db"

    # Print statement to confirm which site and DB path the fixture is using.
    # print(f"e2e_db  site={site.id!r}  db={db}  cycles={N_CYCLES}")

    engine = DetectionEngine(site)

    with ArchiveWriter(db, run_id=RUN_ID, site_id=SITE_ID) as aw, \
         AlarmLog(db,     run_id=RUN_ID, site_id=SITE_ID) as log:

        for cycle in range(N_CYCLES):
            now = datetime.now(timezone.utc)
            for ch in site.channels:
                sim_fn = CHANNEL_SIMULATORS.get(ch.type)
                value  = sim_fn() if sim_fn else 0.0

                reading = TagReading(
                    tag_id=ch.id,
                    value=value,
                    timestamp=now,
                    quality="Good",
                    unit=ch.unit,
                )
                aw.write(reading)

                for event in engine.process(reading):
                    log.append(event)

                    # Print statement to see every alarm fired during the fixture run.
                    # print(f"alarm  cycle={cycle}  tag={ch.id!r}  "
                    #       f"severity={event.severity.value}  msg={event.message!r}")

    # Print statement to confirm the fixture finished writing before any test reads.
    # print(f"e2e_db complete  path={db}")

    return db


class TestArchiveReaderIntegration:

    def test_run_id_in_list_runs(self, e2e_db):
        """The run written by the fixture must appear in list_runs()."""
        r    = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID)
        runs = r.list_runs()

        # Print statement to see all run_ids found in the e2e DB.
        # print(f"list_runs={runs}")

        assert RUN_ID in runs

    def test_all_channels_loaded(self, e2e_db):
        """load_by_channel() must return one entry per channel defined in config."""
        cfg  = load_config(CONFIG_PATH)
        dfs  = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID).load_by_channel()
        expected = {ch.id for ch in cfg.sites[0].channels}

        # Print statement to compare loaded keys vs expected channel ids.
        # print(f"loaded keys={set(dfs.keys())}  expected={expected}")

        assert set(dfs.keys()) == expected

    def test_correct_row_count_per_channel(self, e2e_db):
        """Each channel must have exactly N_CYCLES rows — one per poll cycle."""
        dfs = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID).load_by_channel()
        for tag, df in dfs.items():

            # Print statement to check per-channel row counts against N_CYCLES.
            # print(f"tag={tag!r}  rows={len(df)}  expected={N_CYCLES}")

            assert len(df) == N_CYCLES, f"{tag}: expected {N_CYCLES} rows, got {len(df)}"


class TestReportBuilderIntegration:

    @pytest.fixture
    def report(self, e2e_db):
        """Build a Report from the full e2e DB — shared across builder integration tests."""
        r      = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID)
        alarms = AlarmLog(e2e_db, run_id=RUN_ID, site_id=SITE_ID).read_all()

        # Print statement to see total alarm count before the builder runs.
        # print(f"alarm_records from e2e_db={len(alarms)}")

        return ReportBuilder(
            channel_dfs=r.load_by_channel(),
            alarm_records=alarms,
            run_id=RUN_ID,
            site_id=SITE_ID,
        ).build()

    def test_stats_are_non_null(self, report):
        """All channels had Good readings so mean/std/min/max must not be None."""
        for tag, cs in report.channel_stats.items():

            # Print statement to inspect per-channel stats computed from real simulator values.
            # print(f"tag={tag!r}  mean={cs.mean}  std={cs.std}  "
            #       f"min={cs.min}  max={cs.max}  alarms={cs.alarm_count}")

            assert cs.mean is not None, f"{tag}: mean is None — all readings may be bad quality"
            assert cs.sample_count == N_CYCLES

    def test_total_alarm_count_matches_log(self, e2e_db, report):
        """report.total_alarms must equal the number of rows in the alarms table."""
        alarms = AlarmLog(e2e_db, run_id=RUN_ID, site_id=SITE_ID).read_all()

        # Print statement to compare builder total vs raw alarm log count.
        # print(f"report.total_alarms={report.total_alarms}  raw log count={len(alarms)}")

        assert report.total_alarms == len(alarms)

    def test_run_and_site_ids(self, report):
        assert report.run_id  == RUN_ID
        assert report.site_id == SITE_ID


class TestReportWriterIntegration:

    def test_report_file_written(self, e2e_db, tmp_path):
        """Full chain — DB → reader → builder → writer — must produce a file."""
        r      = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID)
        alarms = AlarmLog(e2e_db, run_id=RUN_ID, site_id=SITE_ID).read_all()
        report = ReportBuilder(
            channel_dfs=r.load_by_channel(),
            alarm_records=alarms,
            run_id=RUN_ID,
            site_id=SITE_ID,
        ).build()

        out = tmp_path / "reports" / "summary.md"
        md  = ReportWriter(out).write(report)

        # Print statement to eyeball the first 300 chars of the final Markdown output.
        # print(f"md preview:\n{md[:300]}")

        assert out.exists()
        assert SITE_ID in md
        assert RUN_ID  in md

    def test_all_channel_tags_in_output(self, e2e_db, tmp_path):
        """Every channel id from config must appear in the rendered Markdown."""
        cfg    = load_config(CONFIG_PATH)
        r      = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID)
        alarms = AlarmLog(e2e_db, run_id=RUN_ID, site_id=SITE_ID).read_all()
        report = ReportBuilder(
            channel_dfs=r.load_by_channel(),
            alarm_records=alarms,
            run_id=RUN_ID,
            site_id=SITE_ID,
        ).build()

        md = ReportWriter(tmp_path / "out.md").write(report)

        for ch in cfg.sites[0].channels:

            # Print statement to check each channel id as it's searched in the output.
            # print(f"checking channel {ch.id!r} in md")

            assert ch.id in md, f"Channel {ch.id!r} missing from report"

    def test_markdown_structure(self, e2e_db, tmp_path):
        """The rendered Markdown must contain the three expected section headers."""
        r      = ArchiveReader(e2e_db, run_id=RUN_ID, site_id=SITE_ID)
        alarms = AlarmLog(e2e_db, run_id=RUN_ID, site_id=SITE_ID).read_all()
        report = ReportBuilder(
            channel_dfs=r.load_by_channel(),
            alarm_records=alarms,
            run_id=RUN_ID,
            site_id=SITE_ID,
        ).build()
        md = ReportWriter(tmp_path / "out.md").write(report)

        assert "# Pipesense Site Report" in md
        assert "## Channel Statistics"   in md
        assert "## Alarm Summary"        in md