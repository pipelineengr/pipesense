"""Generate sample PI historian export CSVs for testing."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipesense.config.schema import SiteConfig
from pipesense.sources.simulate import CHANNEL_SIMULATORS


def generate_pi_export(
    site: SiteConfig,
    output_dir: Path,
    duration_hours: float = 24.0,
    interval_s: int = 5,
) -> dict[str, Path]:
    """Generate PI historian CSV export for a single site, has data for all five
    signals in the channel.

    Creates one CSV per channel in PI export format:
    Timestamp, TagName, Value, Quality
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    start = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    n_points = int(duration_hours * 3600 / interval_s)

    # [PI] Print statement to see generation parameters before writing.
    # print(f"[PI] generate_pi_export: site={site.id!r} "
    #       f"duration={duration_hours}h interval={interval_s}s "
    #       f"n_points={n_points} output={output_dir}")

    paths = {}

    for ch in site.channels:
        fname = f"{ch.pi_tag.replace('.', '_')}.csv"
        path = output_dir / fname
        sim_fn = CHANNEL_SIMULATORS.get(ch.type)
        rows = []

        for i in range(n_points):
            ts = start + timedelta(seconds=i * interval_s)
            value = sim_fn() if sim_fn else 0.0
            rows.append(
                {
                    "Timestamp": ts.isoformat(),
                    "TagName": ch.pi_tag,
                    "Value": round(value, 4),
                    "Quality": "Good",
                }
            )

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["Timestamp", "TagName", "Value", "Quality"]
            )
            writer.writeheader()
            writer.writerows(rows)
        paths[ch.id] = path

        # [PI] Print statement to confirm each CSV file as it is written.
        # Shows channel, PI tag name, file path, and row count.
        # print(f"[PI] wrote {len(rows)} rows → {path} "
        #       f"(channel={ch.id!r} pi_tag={ch.pi_tag!r})")

    # [PI] Print statement to see the full generation summary.
    # print(f"[PI] generate_pi_export complete: {len(paths)} files written")
    # for ch_id, p in paths.items():
    #     print(f"[PI]   {ch_id!r} → {p.name}")

    return paths
