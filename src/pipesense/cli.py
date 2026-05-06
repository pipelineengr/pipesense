"""CLI (Command Line Interface) to be used to interact with pipesense"""

import argparse
import sys

from pipesense import __version__


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
    config_path = args.config

    if args.command == "validate":
        path = args.config_override or config_path
        config = _load(path)
        n_sites = len(config.sites)
        n_channels = sum(len(s.channels) for s in config.sites)
        print(f"Config valid: {path}")
        print(f"  {n_sites} site(s), {n_channels} channel(s) total")
        for site in config.sites:
            print(f"  [{site.id}] {site.name} — {len(site.channels)} channels")

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


if __name__ == "__main__":
    main()
