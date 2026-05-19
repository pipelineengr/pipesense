"""Test for multi-site functions

Covers:
  - _sites() helper (the resolve function in cli.py)
  - Config loading — all three sites parse correctly
  - DB isolation — site_id scoping in ArchiveReader/AlarmLog
  - ReportWriter — consolidated single-file output
  - _report() integration — the full CLI report path end-to-end

All fixtures write directly through ArchiveWriter/AlarmLog using site.id,
matching exactly how _run_single_site() writes in cli.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipesense.config.loader import load_config
from pipesense.detection.base import AlarmEvent, AlarmSeverity
from pipesense.reporting.builder import ReportBuilder
from pipesense.reporting.reader import ArchiveReader
from pipesense.reporting.writer import ReportWriter
from pipesense.sources.base import TagReading
from pipesense.storage.alarm_log import AlarmLog
from pipesense.storage.archive import ArchiveWriter

CONFIG_PATH = "config/site_default.yaml"
RUN_ID = "ms_test_run"
N_ROWS = 10  # readings per channel per site


@pytest.fixture
def three_site_config():
    """Load the real config — confirms all three sites parse without error.
    If this fixture fails, check site_default.yaml has all three site blocks.
    """
    cfg = load_config(CONFIG_PATH)

    # Print statement to confirm how many sites loaded and their IDs.
    # print(f"three_site_config  sites={[s.id for s in cfg.sites]}")

    return cfg


@pytest.fixture
def multi_site_db(tmp_path) -> Path:
    """Write N_ROWS good readings for every channel across all three sites,
    into a SINGLE shared DB file. This is the same pattern _run_single_site
    uses — one ArchiveWriter per site, same db_path, scoped by site_id.
    """
    cfg = load_config(CONFIG_PATH)
    db = tmp_path / "pipesense.db"
    now = datetime.now(timezone.utc)

    # Print statement to confirm the DB path and site list before writing.
    # print(f"multi_site_db  db={db}")
    # print(f"writing sites={[s.id for s in cfg.sites]}")

    for site in cfg.sites:
        with (
            ArchiveWriter(db, run_id=RUN_ID, site_id=site.id) as aw,
            AlarmLog(db, run_id=RUN_ID, site_id=site.id) as al,
        ):
            for ch in site.channels:
                for i in range(N_ROWS):
                    aw.write(
                        TagReading(
                            tag_id=ch.id,
                            value=float(50 + i),
                            timestamp=now,
                            quality="Good",
                            unit=ch.unit,
                        )
                    )
                al.append(
                    AlarmEvent(
                        tag_id=ch.id,
                        severity=AlarmSeverity.HIGH,
                        detector="spike",
                        value=float(50 + N_ROWS),
                        timestamp=now,
                        message=f"test alarm for {ch.id}",
                    )
                )

        # Print statement to see a per-site confirmation after each write batch.
        # print(f"wrote site={site.id!r}  channels={len(site.channels)}  rows_per_channel={N_ROWS}")

    return db


@pytest.fixture
def all_reports(multi_site_db) -> list:
    """Build a Report object for every site — used by ReportWriter tests."""
    cfg = load_config(CONFIG_PATH)
    reports = []
    for site in cfg.sites:
        reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id=site.id)
        alarms = AlarmLog(multi_site_db, run_id=RUN_ID, site_id=site.id).read_all()
        report = ReportBuilder(
            channel_dfs=reader.load_by_channel(),
            alarm_records=alarms,
            run_id=RUN_ID,
            site_id=site.id,
        ).build()
        reports.append(report)

        # Print statement to see each report's channel count and alarm count.
        # print(f"all_reports  site={site.id!r}  channels={len(report.channel_stats)}  alarms={report.total_alarms}")

    return reports


class TestSitesHelper:
    """Tests for the _sites() function in cli.py.
    _sites() is the central resolver — every CLI command calls it.
    We import it directly here to test it without running the full CLI.
    """

    def test_none_returns_all_sites(self, three_site_config):
        """Passing site_args=None must return all sites in config.
        This is the default behaviour when --site is not provided.
        """
        from pipesense.cli import _sites

        result = _sites(three_site_config, None)

        # Print statement to confirm all site IDs are returned.
        # print(f"[test] _sites(None) → {[s.id for s in result]}")

        assert len(result) == len(three_site_config.sites)

    def test_single_site_filter(self, three_site_config):
        """Passing one site ID must return only that one site."""
        from pipesense.cli import _sites

        sites = three_site_config.sites
        target = sites[0].id
        result = _sites(three_site_config, [target])

        # Print statement to confirm the single site returned.
        # print(f"[test] _sites([{target!r}]) → {[s.id for s in result]}")

        assert len(result) == 1
        assert result[0].id == target

    def test_multiple_site_filter(self, three_site_config):
        """Passing two site IDs must return exactly those two, in that order."""
        from pipesense.cli import _sites

        sites = three_site_config.sites
        ids = [sites[0].id, sites[2].id]
        result = _sites(three_site_config, ids)

        # Print statement to verify order is preserved.
        # print(f"[test] _sites({ids}) → {[s.id for s in result]}")

        assert [s.id for s in result] == ids

    def test_invalid_site_id_calls_sys_exit(self, three_site_config):
        """An unknown site ID must call sys.exit — not silently skip or return None."""
        from pipesense.cli import _sites

        with pytest.raises(SystemExit):
            _sites(three_site_config, ["LACT-999"])

    def test_all_sites_returned_in_config_order(self, three_site_config):
        """With no filter, sites come back in the same order as in the YAML."""
        from pipesense.cli import _sites

        result = _sites(three_site_config, None)
        expected_ids = [s.id for s in three_site_config.sites]

        # Print statement to compare expected vs actual order.
        # print(f"[test] expected={expected_ids}  got={[s.id for s in result]}")

        assert [s.id for s in result] == expected_ids


class TestMultiSiteConfig:
    """Validate that all three sites in site_default.yaml parse correctly
    and have the expected structure.
    """

    def test_correct_number_of_sites(self, three_site_config):
        """Config must have exactly three sites after Week 6 YAML additions."""

        # Print statement to see the actual count and site IDs.
        # print(f"[test] site count={len(three_site_config.sites)}  ids={[s.id for s in three_site_config.sites]}")

        assert len(three_site_config.sites) == 3

    def test_all_sites_have_channels(self, three_site_config):
        """Every site must have at least one channel defined."""
        for site in three_site_config.sites:
            # Print statement to see per-site channel counts.
            # print(f"[test] site={site.id!r}  channels={len(site.channels)}")

            assert len(site.channels) > 0, f"{site.id} has no channels"

    def test_all_sites_have_detection_config(self, three_site_config):
        """Every site must have a detection block — spike and drift are required."""
        for site in three_site_config.sites:
            assert site.detection is not None, f"{site.id} missing detection config"

    def test_unique_opc_endpoints(self, three_site_config):
        """Each site must declare a distinct OPC-UA endpoint to avoid port conflicts."""
        endpoints = [s.opc_ua_endpoint for s in three_site_config.sites]

        # Print statement to see the three endpoints.
        # print(f"[test] opc_ua_endpoints={endpoints}")

        assert len(set(endpoints)) == len(endpoints), (
            f"Duplicate OPC-UA endpoints found: {endpoints}"
        )

    def test_all_channel_types_known(self, three_site_config):
        """Every channel type across all sites must be in the registered set.
        This catches a new channel type added to YAML but not to simulate.py/loader.py.
        """
        from pipesense.sources.simulate import CHANNEL_SIMULATORS

        known_types = set(CHANNEL_SIMULATORS.keys())

        for site in three_site_config.sites:
            for ch in site.channels:
                # Print statement to trace each channel type check.
                # print(f"[test] site={site.id!r}  tag={ch.id!r}  type={ch.type!r}  known={ch.type in known_types}")

                assert ch.type in known_types, (
                    f"Site {site.id} channel {ch.id} has unregistered type {ch.type!r}"
                )


class TestSingleDbIsolation:
    """Verify that a single shared DB correctly isolates data by site_id.
    These tests prove the WHERE site_id = ? clause in ArchiveReader.load()
    is working — readings from one site must NEVER appear in another site's reader.
    """

    def test_each_site_has_rows(self, multi_site_db):
        """Every site must return a non-empty DataFrame from ArchiveReader."""
        cfg = load_config(CONFIG_PATH)
        for site in cfg.sites:
            reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id=site.id)
            df = reader.load()

            # Print statement to see row count per site.
            # print(f"[test] site={site.id!r}  rows={len(df)}")

            assert not df.empty, f"{site.id} returned no rows from shared DB"

    def test_each_site_correct_row_count(self, multi_site_db):
        """Row count per site must equal N_ROWS × number of channels for that site."""
        cfg = load_config(CONFIG_PATH)
        for site in cfg.sites:
            reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id=site.id)
            df = reader.load()
            expected = N_ROWS * len(site.channels)

            # Print statement to compare actual vs expected row counts.
            # print(f"[test] site={site.id!r}  rows={len(df)}  expected={expected}")

            assert len(df) == expected, (
                f"{site.id}: expected {expected} rows, got {len(df)}"
            )

    def test_reader_only_returns_own_site_rows(self, multi_site_db):
        """Every row in the DataFrame must have site_id matching the reader's site_id."""
        cfg = load_config(CONFIG_PATH)
        for site in cfg.sites:
            reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id=site.id)
            df = reader.load()

            # Print statement to see the unique site_ids in the returned DataFrame.
            # print(f"[test] site={site.id!r}  unique site_ids in df={df['site_id'].unique().tolist()}")

            assert (df["site_id"] == site.id).all(), (
                f"{site.id} reader returned rows belonging to another site"
            )

    def test_no_cross_site_row_contamination(self, multi_site_db):
        """Rows written for one site must not appear when reading another site.
        We check the site_id column on returned rows — not tag name uniqueness,
        since LACT-003 intentionally reuses some tag IDs from LACT-001.
        """
        cfg = load_config(CONFIG_PATH)
        for site in cfg.sites:
            reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id=site.id)
            df = reader.load()

            # [DEBUG] Uncomment to inspect the site_id values in each DataFrame.
            # print(f"[test] site={site.id!r}  unique site_ids in df={df['site_id'].unique().tolist()}")

            assert (df["site_id"] == site.id).all(), (
                f"Reader for {site.id} returned rows with a different site_id"
            )

    def test_run_id_visible_from_all_sites(self, multi_site_db):
        """list_runs() must return the shared run_id regardless of which site_id is used."""
        cfg = load_config(CONFIG_PATH)
        for site in cfg.sites:
            reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id=site.id)
            runs = reader.list_runs()

            # Print statement to see the run_ids visible per site.
            # print(f"[test] site={site.id!r}  list_runs={runs}")

            assert RUN_ID in runs, (
                f"{site.id} cannot see run_id {RUN_ID!r} in list_runs()"
            )

    def test_unknown_site_returns_empty_df(self, multi_site_db):
        """Querying a site_id that was never written must return an empty DataFrame."""
        reader = ArchiveReader(multi_site_db, run_id=RUN_ID, site_id="NONEXISTENT-SITE")
        df = reader.load()

        # Print statement to confirm the DataFrame is truly empty.
        # print(f"[test] nonexistent site  df.shape={df.shape}")

        assert df.empty


class TestConsolidatedReport:
    """Tests for ReportWriter.write(list[Report]) — the single-file, multi-site output.
    All sites must appear in one file. A single-site call must only contain that site.
    """

    def test_write_creates_file(self, all_reports, tmp_path):
        """write() must create the output file on disk."""
        out = tmp_path / "reports" / "run_report.md"
        ReportWriter(out).write(all_reports)

        # Print statement to confirm the file exists and its size.
        # print(f"[test] file exists={out.exists()}  size={out.stat().st_size} bytes")

        assert out.exists()

    def test_write_returns_string(self, all_reports, tmp_path):
        """write() must return the full rendered Markdown string."""
        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write(all_reports)

        # Print statement to see character count of returned string.
        # print(f"[test] returned md  len={len(md)}")

        assert isinstance(md, str) and len(md) > 0

    def test_all_site_headers_in_one_file(self, all_reports, tmp_path):
        """Every site must have its own '# Site Report: <id>' header in the file."""
        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write(all_reports)

        cfg = load_config(CONFIG_PATH)
        for site in cfg.sites:
            # Print statement to check each header is present.
            # print(f"[test] checking header for site={site.id!r}  present={'# Site Report: ' + site.id in md}")

            assert f"# Site Report: {site.id}" in md, (
                f"Missing site header for {site.id} in consolidated report"
            )

    def test_all_run_ids_in_file(self, all_reports, tmp_path):
        """The shared run_id must appear in the file."""
        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write(all_reports)
        assert RUN_ID in md

    def test_single_site_report_excludes_others(self, all_reports, tmp_path):
        """Writing only one Report must not include data from the other sites."""
        cfg = load_config(CONFIG_PATH)
        all_ids = [s.id for s in cfg.sites]
        target = all_reports[1]  # second site
        target_id = target.site_id
        other_ids = [sid for sid in all_ids if sid != target_id]

        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write([target])

        # Print statement to verify only the target site appears.
        # print(f"[test] target={target_id!r}  others={other_ids}")
        # print(f"[test] md preview:\n{md[:200]}")

        assert f"# Site Report: {target_id}" in md
        for other_id in other_ids:
            assert f"# Site Report: {other_id}" not in md, (
                f"Report for {target_id} unexpectedly contains header for {other_id}"
            )

    def test_no_alarms_message_appears_when_no_alarms(self, all_reports, tmp_path):
        """Each site section that had no alarms must contain the no-alarm message."""
        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write(all_reports)

        sites_with_no_alarms = [r for r in all_reports if r.total_alarms == 0]
        if sites_with_no_alarms:
            assert "No alarms recorded in this run." in md

    def test_channel_stats_table_present_for_each_site(self, all_reports, tmp_path):
        """Each site section must contain the Channel Statistics table header."""
        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write(all_reports)

        # Print statement to count how many times the table header appears.
        # print(f"[test] '## Channel Statistics' count={md.count('## Channel Statistics')}")

        assert md.count("## Channel Statistics") == len(all_reports)

    def test_sections_separated_in_output(self, all_reports, tmp_path):
        """The rendered file must contain at least one blank line between site sections."""
        out = tmp_path / "run_report.md"
        md = ReportWriter(out).write(all_reports)

        # The writer joins sections with \n\n\n\n — check at least two newlines between sections
        assert "\n\n" in md


class TestReportCliIntegration:
    """End-to-end tests that call _report() directly (no subprocess).
    These tests verify the full chain: config → _sites() → ArchiveReader
    → ReportBuilder → ReportWriter → file on disk.
    """

    def _make_args(self, run_id=None, site=None):
        """Build a minimal args namespace that _report() expects."""
        import argparse

        args = argparse.Namespace()
        args.run_id = run_id
        args.site = site
        args.config_override = None
        return args

    def test_report_all_sites_creates_file(self, multi_site_db, tmp_path, monkeypatch):
        """_report() with no --site filter must write a file containing all sites."""
        from pipesense.cli import _report

        # Point config storage to our temp DB and output to tmp_path
        monkeypatch.setenv("PIPESENSE_TEST_DB", str(multi_site_db))

        # Use real config but patch storage.db_path and report_path
        cfg = load_config(CONFIG_PATH)
        cfg.storage.db_path = str(multi_site_db)
        cfg.reporting.report_path = str(tmp_path / "run_report.md")

        # Monkeypatch _load to return our patched config
        import pipesense.cli as cli_module

        monkeypatch.setattr(cli_module, "_load", lambda _: cfg)

        args = self._make_args(run_id=None, site=None)
        _report(args, CONFIG_PATH)

        out = tmp_path / "run_report.md"

        # Print statement to verify the file landed correctly.
        # print(f"[test] report file exists={out.exists()}  size={out.stat().st_size}")

        assert out.exists()
        md = out.read_text()
        for site in cfg.sites:
            assert f"# Site Report: {site.id}" in md

    def test_report_single_site_filter(self, multi_site_db, tmp_path, monkeypatch):
        """_report() with --site LACT-001 must only include LACT-001 in the output."""
        import pipesense.cli as cli_module
        from pipesense.cli import _report

        cfg = load_config(CONFIG_PATH)
        cfg.storage.db_path = str(multi_site_db)
        cfg.reporting.report_path = str(tmp_path / "run_report.md")

        monkeypatch.setattr(cli_module, "_load", lambda _: cfg)

        target_id = cfg.sites[0].id
        args = self._make_args(run_id=None, site=[target_id])
        _report(args, CONFIG_PATH)

        md = (tmp_path / "run_report.md").read_text()
        all_ids = [s.id for s in cfg.sites]
        other_ids = [sid for sid in all_ids if sid != target_id]

        # Print statement to confirm only the target site appears.
        # print(f"[test] target={target_id!r}  md preview:\n{md[:300]}")

        assert f"# Site Report: {target_id}" in md
        for other_id in other_ids:
            assert f"# Site Report: {other_id}" not in md

    def test_report_falls_back_to_latest_run(
        self, multi_site_db, tmp_path, monkeypatch
    ):
        """When no --run_id is given, _report() must use the most recent run_id."""
        import pipesense.cli as cli_module
        from pipesense.cli import _report

        cfg = load_config(CONFIG_PATH)
        cfg.storage.db_path = str(multi_site_db)
        cfg.reporting.report_path = str(tmp_path / "run_report.md")

        monkeypatch.setattr(cli_module, "_load", lambda _: cfg)

        args = self._make_args(run_id=None, site=None)
        _report(args, CONFIG_PATH)

        md = (tmp_path / "run_report.md").read_text()

        # Print statement to confirm the run_id used.
        # print(f"[test] RUN_ID={RUN_ID!r}  in md={RUN_ID in md}")

        assert RUN_ID in md

    def test_report_exits_when_no_runs_in_db(self, tmp_path, monkeypatch):
        """_report() must call sys.exit when the DB has no runs at all."""
        import pipesense.cli as cli_module
        from pipesense.cli import _report

        # Create a valid but empty DB — no readings written
        empty_db = tmp_path / "empty.db"
        from pipesense.storage.archive import ArchiveWriter

        cfg = load_config(CONFIG_PATH)
        # Touch the DB by opening a writer and immediately closing it
        with ArchiveWriter(empty_db, run_id="dummy", site_id="LACT-001"):
            pass
        import sqlite3

        sqlite3.connect(empty_db).execute("DELETE FROM readings").connection.commit()

        cfg.storage.db_path = str(empty_db)
        cfg.reporting.report_path = str(tmp_path / "run_report.md")
        monkeypatch.setattr(cli_module, "_load", lambda _: cfg)

        args = self._make_args(run_id=None, site=None)
        with pytest.raises(SystemExit):
            _report(args, CONFIG_PATH)
