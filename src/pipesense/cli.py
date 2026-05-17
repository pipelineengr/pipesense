"""CLI (Command Line Interface) to be used to interact with pipesense"""

import argparse
import sys
import asyncio
import signal
import logging
import time as _time

from pipesense import __version__
from pipesense.sources.base import TagReading
from pipesense.detection.engine import DetectionEngine
from pipesense.storage.archive import ArchiveWriter
from pipesense.storage.alarm_log import AlarmLog
from pipesense.reporting.reader import ArchiveReader
from pipesense.reporting.builder import ReportBuilder
from pipesense.reporting.writer import ReportWriter
from pipesense.storage.alarm_log import AlarmLog
from pathlib import Path

logging.getLogger("asyncua").setLevel(logging.ERROR)

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="pipesense",
        description=(
            "Tool for pipeline production real-time data acquisition, analysis, historical simulation and leak detection."
        ),
        formatter_class=_Formatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--config",
        default="config/site_default.yaml",
        metavar="FILE",
        help="Path to site configuration",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="")

    p_val = sub.add_parser(
        "validate",
        help="Validate a site configuration file (valid sample located at config/site_default.yaml, invalid at config/site_default_fail.yaml)",
    )
    p_val.add_argument("--config", dest="config_override", default=None)

    p_info = sub.add_parser("info", help="Show site and channel summary")
    p_info.add_argument(
        "--site",
        nargs="+",           
        default=None,
        metavar="SITE_ID",
        help="Site ID(s) to target. Accepts one, multiple, or omit for all sites.",
    )
    p_info.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
    )

    p_status = sub.add_parser("status", help="Show data source configuration for a site")
    p_status.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
    )
    p_status.add_argument(
        "--site",
        nargs="+",           
        default=None,
        metavar="SITE_ID",
        help="Site ID(s) to target. Accepts one, multiple, or omit for all sites.",
    )

    p_run = sub.add_parser("run", help="Start a run")
    p_run.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
    )
    p_run.add_argument(
        "--duration", type=int, default=None, metavar="SECONDS",
        help="Stop after this many seconds (default: run until stopped manually)"
    )
    p_run.add_argument(
            "--source",
            choices=["sim", "opcua", "pi"],
            default="sim",
            help=(
                "Data source: "
                "sim = built-in simulator (default), "
                "opcua = virtual OPC-UA server on with the endpoint listed in config, "
                "pi = generated PI historian CSV exports"
            ),
        )
    p_run.add_argument(
        "--pi-dir",
        default=None,
        metavar="DIR",
        help="Directory for PI CSV exports (--source pi only). "
            "Defaults to the export_path in site config.",
    )
    p_run.add_argument(
        "--site",
        nargs="+",           
        default=None,
        metavar="SITE_ID",
        help="Site ID(s) to target. Accepts one, multiple, or omit for all sites.",
    )

    p_report = sub.add_parser("report", help="Generate a report")
    p_report.add_argument(
        "--run_id", dest="run_id", default=None,
        help="Run ID to run the report for (default is generate for the most recent run)"
    )
    p_report.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
    )
    p_report.add_argument(
        "--site",
        nargs="+",           
        default=None,
        metavar="SITE_ID",
        help="Site ID(s) to target. Accepts one, multiple, or omit for all sites.",
    )
    return parser.parse_args(argv)


# This formatter class is to replace the typical {} below the positional arguments
class _Formatter(argparse.HelpFormatter):
    def _format_action(self, action):
        if action.nargs == argparse.PARSER:
            return "".join(
                self._format_action(subaction)
                for subaction in self._iter_indented_subactions(action)
            )
        return super()._format_action(action)


def _load(config_path: str):
    from pipesense.config.loader import ConfigError, load_config

    try:
        return load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

async def _make_sim_source(site, _args):
    """Wrap CHANNEL_SIMULATORS in a thin async-compatible DataSource."""
    from pipesense.sources.simulator_source import SimulatorSource
    source = SimulatorSource(site)
    await source.connect()
    return source, None          


async def _make_opcua_source(site, _args):
    """Start MockOpcUaServer then connect OpcUaSource to it."""
    from pipesense.sources.mock_server import MockOpcUaServer, MockServerConfig
    from pipesense.sources.opcua_source import OpcUaSource

    cfg    = MockServerConfig(endpoint=site.opc_ua_endpoint)
    server = MockOpcUaServer(site, cfg)
    await server.start()
    await asyncio.sleep(2)                  # 2 second wait
    print(f"OPC-UA server started at {site.opc_ua_endpoint}")

    source = OpcUaSource(endpoint=site.opc_ua_endpoint)
    await source.connect()

    #for ch in site.channels:
    #    test = await source.read_tag(ch.opc_node)
    #    print(f"  CONNECT TEST: {ch.opc_node!r} → value={test.value} quality={test.quality!r}")

    print("OPC-UA client connected")
    return source, server       


async def _make_pi_source(site, args):
    """Generate PI CSVs if missing, then load PIHistorianSource."""
    from pathlib import Path
    from pipesense.sources.pi_generator import generate_pi_export
    from pipesense.sources.pi_source import PIHistorianSource

    export_dir = Path(args.pi_dir or site.pi_historian.export_path)
    if not any(export_dir.glob("*.csv")):
        print(f"Generating PI exports → {export_dir}")
        generate_pi_export(site, export_dir, duration_hours=24.0, interval_s=5)

    source = PIHistorianSource(site, export_dir)
    await source.connect()
    print(f"PI historian loaded {source.status().n_tags} tag(s) from {export_dir}")
    return source, None


_SOURCE = {
    "sim":   _make_sim_source,
    "opcua": _make_opcua_source,
    "pi":    _make_pi_source,
}

async def _run_single_site(
    site,
    args,
    db_path: str,
    run_id: str,
    engine: "DetectionEngine",
    stop_event: asyncio.Event,
) -> None:
    """Poll one site until stop_event is set or duration expires.
    One instance of this coroutine runs per site in _run_async.
    """
    source, server = await _SOURCE[args.source](site, args)

    # [RUN_SITE] Confirm source and server are ready for this site
    # print(f"[_run_site] site={site.id!r}  source={args.source!r}  server={server is not None}")

    _opc_to_id = {ch.opc_node: ch.id for ch in site.channels}
    start      = _time.monotonic()

    try:
        with ArchiveWriter(db_path, run_id=run_id, site_id=site.id) as archive, \
             AlarmLog(db_path,      run_id=run_id, site_id=site.id) as alarm_log:

            while not stop_event.is_set():
                if args.duration is not None and (_time.monotonic() - start) >= args.duration:
                    break

                tag_ids  = [ch.opc_node for ch in site.channels]
                readings = await source.read_tags(tag_ids)

                for reading in readings:
                    if not reading.is_good or reading.value != reading.value:
                        # [RUN_SITE] Uncomment to see skipped bad/NaN readings per site
                        # print(f"[_run_site] SKIPPED site={site.id!r} tag={reading.tag_id!r}")
                        continue

                    reading = TagReading(
                        tag_id=_opc_to_id.get(reading.tag_id, reading.tag_id),
                        value=reading.value,
                        timestamp=reading.timestamp,
                        quality=reading.quality,
                        unit=reading.unit,
                    )
                    archive.write(reading)

                    for event in engine.process(reading):
                        alarm_log.append(event)
                        print(f"  [{site.id}] [{event.severity.value}] "
                              f"{event.tag_id}: {event.message}")

                archive.flush()

                # [RUN_SITE] Uncomment to watch the poll cycle complete per site
                # print(f"[_run_site] site={site.id!r}  cycle complete — sleeping 1s")

                await asyncio.sleep(1.0)

    finally:
        await source.disconnect()
        if server is not None:
            await server.stop()

        # [RUN_SITE] Confirm clean shutdown per site
        # print(f"[_run_site] site={site.id!r}  shutdown complete")


async def _run_async(args, config_path: str) -> None:
    config  = _load(config_path)
    sites   = _sites(config, getattr(args, "site", None))
    storage = config.storage
    run_id  = f"run_{int(_time.time())}"

    print(f"Source     : {args.source}")
    print(f"DB         : {storage.db_path}")
    print(f"Run ID     : {run_id}")
    print(f"Sites      : {[s.id for s in sites]}")

    # [RUN] Confirm the full site list and run_id before any tasks are launched
    # print(f"[_run_async] launching {len(sites)} site task(s)")

    stop_event = asyncio.Event()

    def _stop(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    print("Starting run — press Ctrl+C to stop\n")

    tasks = [
        asyncio.create_task(
            _run_single_site(
                site=site,
                args=args,
                db_path=storage.db_path,
                run_id=run_id,
                engine=DetectionEngine(site),   # one engine per site — state is independent
                stop_event=stop_event,
            ),
            name=f"run_site_{site.id}",
        )
        for site in sites
    ]

    # [RUN] Uncomment to see the task names as they're created
    # print(f"[_run_async] tasks={[t.get_name() for t in tasks]}")

    await asyncio.gather(*tasks, return_exceptions=True)
    print("Run complete.")

def _validate(args, config_path: str) -> None:
    path   = args.config_override or config_path
    config = _load(path)
    sites = _sites(config, getattr(args, "site", None))
    
    n_sites    = len(config.sites)
    
    n_channels = sum(len(s.channels) for s in sites)
    
    print(f"Config valid: {path}")
    print(f"  {len(sites)} site(s), {n_channels} channel(s) total")
    for site in sites:
        print(f"  [{site.id}] {site.name} — {len(site.channels)} channels")

def _status(args, config_path: str) -> None:
    config = _load(config_path)
    sites  = _sites(config, getattr(args, "site", None))

    for site in sites:
        print(f"\n[{site.id}] {site.name}")
        print(f"  OPC-UA endpoint : {site.opc_ua_endpoint}")
        pi = site.pi_historian
        print(f"  PI historian    : {'enabled' if pi.enabled else 'disabled'}")
        if pi.enabled:
            print(f"  PI export path  : {pi.export_path}")
            print(f"  PI tag prefix   : {pi.tag_prefix}")
        print(f"  Channels ({len(site.channels)}):")
        for ch in site.channels:
            print(f"    {ch.id:10s} {ch.type:12s} "
                  f"[{ch.unit}] poll={ch.poll_interval_s}s")


def _info(args, config_path: str) -> None:
    config = _load(config_path)
    sites  = _sites(config, getattr(args, "site", None))

    for site in sites:
        print(f"\n{'=' * 52}")
        print(f"Site:       {site.id} — {site.name}")
        print(f"Location:   {site.location}")
        print(f"Endpoint:   {site.opc_ua_endpoint}")
        print(f"PI enabled: {site.pi_historian.enabled}")
        print(f"\nChannels ({len(site.channels)}):")
        for ch in site.channels:
            print(
                f"  {ch.id:10s} {ch.type:12s} "
                f"{ch.name:30s} [{ch.unit}] "
                f"poll={ch.poll_interval_s}s"
            )

def _sites(config, site_args: list[str] | None) -> list:
    """Return the list of SiteConfig objects to process.

    - site_args=None  → all sites in config
    - site_args=[...] → only the requested site IDs, validated against config

    Exits with an error if any requested site ID is not found.
    """
    if site_args is None:
        # No --site flag — running against all sites in config
        # print(f"[_sites] no filter — returning all {len(config.sites)} site(s)")
        return config.sites

    site_list = []
    for sid in site_args:
        site = config.get_site(sid)
        if site is None:
            print(f"Site {sid!r} not found in config. "
                  f"Available: {[s.id for s in config.sites]}", file=sys.stderr)
            sys.exit(1)
        site_list.append(site)

    # Show which site IDs were resolved after validation
    # print(f"[_sites] resolved={[s.id for s in resolved]}")

    return site_list

def _report(args, config_path: str) -> None:
    config     = _load(config_path)
    storage    = config.storage
    report_cfg = config.reporting
    sites      = _sites(config, getattr(args, "site", None))

    # Confirm db path and output path before any file IO
    # print(f"db={storage.db_path!r}  output={report_cfg.report_path!r}")

    reader         = ArchiveReader(storage.db_path, run_id="", site_id=sites[0].id)
    available_runs = reader.list_runs()

    if not available_runs:
        print(f"No runs found in database {storage.db_path}", file=sys.stderr)
        sys.exit(1)

    arg_run_id = getattr(args, "run_id", None)
    if arg_run_id and arg_run_id in available_runs:
        run_id = arg_run_id
    else:
        run_id = available_runs[-1]

    # Show all available run_ids and which one was selected
    # print(f"available_runs={available_runs}  selected={run_id!r}")

    full_report = []

    for site in sites:
        reader      = ArchiveReader(storage.db_path, run_id=run_id, site_id=site.id)
        channel_dfs = reader.load_by_channel()
        alarms      = AlarmLog(storage.db_path, run_id=run_id, site_id=site.id).read_all()
        
        # Confirm how many channels and alarms came back per site
        # print(f"site={site.id!r}  channels={len(channel_dfs)}  alarms={len(alarms)}")

        report = ReportBuilder(
            channel_dfs=channel_dfs,
            alarm_records=alarms,
            run_id=run_id,
            site_id=site.id,
        ).build()

        full_report.append(report)

    # Confirm the output path just before writing
    # print(f"writing to {report_cfg.report_path!r}")

    report_path = getattr(report_cfg, "report_path", "reports/run_report.md")
    out = Path(report_path)
    
    ReportWriter(out).write(full_report)
    
    print(f"Report containing {len(full_report)} site(s) written → {out}")

def main():
    args = parse_args()
    config_override = getattr(args, "config_override", None)  
    config_path = config_override or args.config

    if args.command == "validate": 
        _validate(args, config_path)
    elif args.command == "status":   
        _status(args, config_path)
    elif args.command == "info":     
        _info(args, config_path)
    elif args.command == "report":   
        _report(args, config_path)
    elif args.command == "run":      
        asyncio.run(_run_async(args, config_path))


if __name__ == "__main__":
    main()
