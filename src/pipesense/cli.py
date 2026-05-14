"""CLI (Command Line Interface) to be used to interact with pipesense"""

import argparse
import sys
import asyncio
import signal
import time as _time

from datetime import datetime, timezone

from pipesense import __version__
from pipesense.sources.base import TagReading
from pipesense.sources.simulate import CHANNEL_SIMULATORS
from pipesense.detection.engine import DetectionEngine
from pipesense.storage.archive import ArchiveWriter
from pipesense.storage.alarm_log import AlarmLog

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
    p_info.add_argument("--site", default=None, help="Site ID (default: all)")
    p_info.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
    )

    p_status = sub.add_parser("status", help="Show data source configuration for a site")
    p_status.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
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
    await asyncio.sleep(2)
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

async def _run_async(args, config_path: str) -> None:
    config  = _load(config_path)
    site    = config.sites[0]
    storage = config.storage
    run_id  = f"run_{int(_time.time())}"

    print(f"Source     : {args.source}")
    print(f"DB         : {storage.db_path}")
    print(f"Run ID     : {run_id}")

    source, server = await _SOURCE[args.source](site, args)

    engine  = DetectionEngine(site)
    running = True
    start   = _time.monotonic()

    def _stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    print("Starting run — press Ctrl+C to stop\n")

    try:
        with ArchiveWriter(storage.db_path, run_id=run_id, site_id=storage.site_id) as archive, \
             AlarmLog(storage.db_path,      run_id=run_id, site_id=storage.site_id) as alarm_log:

            while running:
                if args.duration is not None and (_time.monotonic() - start) >= args.duration:
                    break

                tag_ids  = [ch.opc_node for ch in site.channels]
                readings = await source.read_tags(tag_ids)

                #for r in readings:
                #    print(f"  tag={r.tag_id!r} value={r.value} quality={r.quality!r}")

                for reading in readings:
                    if not reading.is_good or reading.value != reading.value:  # Got a NaN check, added Nan != Nan which is always true
                        # print(f"  SKIPPED: {reading.tag_id!r} value={reading.value} quality={reading.quality!r}")
                        continue
                    archive.write(reading)
                    for event in engine.process(reading):
                        alarm_log.append(event)
                        print(f"  [{event.severity.value}] {event.tag_id}: {event.message}")

                archive.flush()
                await asyncio.sleep(1.0)

    finally:
        await source.disconnect()
        if server is not None:
            await server.stop()

    print("Run complete.")

def main():
    args = parse_args()
    config_override = getattr(args, "config_override", None)  
    config_path = config_override or args.config

    if args.command == "validate":
        path = args.config_override or config_path
        config = _load(path)
        n_sites = len(config.sites)
        n_channels = sum(len(s.channels) for s in config.sites)
        print(f"Config valid: {path}")
        print(f"  {n_sites} site(s), {n_channels} channel(s) total")
        for site in config.sites:
            print(f"  [{site.id}] {site.name} — {len(site.channels)} channels")

    elif args.command == "status":
        config = _load(config_path)
        for site in config.sites:
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

    elif args.command == "info":
        config = _load(config_path)
        sites = config.sites
        if args.site:
            site = config.get_site(args.site)
            if not site:
                print(f"Site {args.site!r} not found.", file=sys.stderr)
                sys.exit(1)
            sites = [site]
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

    elif args.command == "run":
        asyncio.run(_run_async(args, config_path))


if __name__ == "__main__":
    main()
