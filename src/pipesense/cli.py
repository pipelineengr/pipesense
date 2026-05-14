"""CLI (Command Line Interface) to be used to interact with pipesense"""

import argparse
import sys
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

    p_run = sub.add_parser("run", help="Start a run (not yet implemented)")
    p_run.add_argument(
        "--config", dest="config_override", default=None,
        help="Path to site config YAML (overrides root --config)"
    )
    p_run.add_argument(
        "--duration", type=int, default=None, metavar="SECONDS",
        help="Stop after this many seconds (default: run until stopped manually)"
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
        config  = _load(config_path)
        site    = config.sites[0]        # DetectionEngine takes SiteConfig
        storage = config.storage
        run_id  = f"run_{int(_time.time())}"

        # Print statement to confirm db path, run_id, and site_id before any files are created — a wrong path here is far easier to spot than a downstream error
        # print(f"[run] db={storage.db_path!r}  run_id={run_id!r}  site_id={storage.site_id!r}")

        engine   = DetectionEngine(site)
        duration = getattr(args, "duration", None)
        running  = True
        start    = _time.monotonic()

        def _stop(sig, frame):
            nonlocal running
            running = False
            # Print statement to confirm which OS signal triggered the shutdown — useful when debugging unexpected exits under Docker or systemd
            # print(f"[run] shutdown signal received  sig={sig}")

        signal.signal(signal.SIGINT,  _stop)
        signal.signal(signal.SIGTERM, _stop)

        print(f"Starting run — db: {storage.db_path}  run_id: {run_id}")

        with ArchiveWriter(storage.db_path, run_id=run_id, site_id=storage.site_id) as archive, \
            AlarmLog(storage.db_path,      run_id=run_id, site_id=storage.site_id) as alarm_log:

            while running:
                if duration is not None and (_time.monotonic() - start) >= duration:
                    break

                now = datetime.now(timezone.utc)

                for ch in site.channels:
                    sim_fn = CHANNEL_SIMULATORS.get(ch.type)
                    if sim_fn is None:
                        continue

                    reading = TagReading(
                        tag_id=ch.id,
                        value=sim_fn(),
                        timestamp=now,
                        quality="Good",
                        unit=ch.unit,
                    )

                    # Print statement to show every raw reading entering the pipeline — enable briefly to verify all 5 channels are polling, disable during normal runs
                    # print(f"[run] polled  tag={reading.tag_id!r}  value={reading.value:.4f}")

                    archive.write(reading)

                    for event in engine.process(reading):
                        alarm_log.append(event)
                        # Print statement to show each alarm event emitted by the detection engine — severity, tag, and message in one line for quick triage
                        # print(f"[run] alarm  [{event.severity.value}] {event.tag_id}: {event.message}")
                        print(f"  [{event.severity.value}] {event.tag_id}: {event.message}")

                archive.flush()
                _time.sleep(1.0)

        print("Run complete.")


if __name__ == "__main__":
    main()
