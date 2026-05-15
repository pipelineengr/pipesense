"""YAML configuration loader and validator for pipesense."""

from pathlib import Path

import yaml

from pipesense.config.schema import (
    ChannelConfig,
    DetectionConfig,
    DriftDetectionConfig,
    ReportConfig,
    StorageConfig,
    PIHistorianConfig,
    PipesenseConfig,
    SiteConfig,
    SpikeDetectionConfig,
    Thresholds,  # Trailing comma :)
)


class ConfigError(Exception):
    """Raises Exception when config is missing, abnormal, or invalid."""


def _parse_thresholds(data: dict, channel_id: str) -> Thresholds:
    required = {"low_low", "low", "high", "high_high"}
    missing = required - set(data.keys())
    if missing:
        raise ConfigError(
            f"Channel {channel_id!r} missing threshold keys: {missing}"
        )  # Do we need all four? Let's keep them for now, can make low_low, high_high optional if needed
    t = Thresholds(
        low_low=float(data["low_low"]),
        low=float(data["low"]),
        high=float(data["high"]),
        high_high=float(data["high_high"]),
    )
    if not (t.low_low <= t.low <= t.high <= t.high_high):
        raise ConfigError(
            f"Channel {channel_id!r} thresholds must satisfy "
            f"low_low <= low <= high <= high_high. Got: {t}"
        )
    return t


def _parse_channel(data: dict) -> ChannelConfig:
    required = {
        "id",
        "name",
        "opc_node",
        "pi_tag",
        "unit",
        "type",
        "poll_interval_s",
        "thresholds",
    }
    missing = required - set(data.keys())
    if missing:
        raise ConfigError(f"Channel {data.get('id', '?')!r} missing keys: {missing}")
    valid_types = {"flow", "pressure", "temperature", "level", "vibration"}
    if data["type"] not in valid_types:
        raise ConfigError(
            f"Channel {data['id']!r} has invalid type {data['type']!r}. "  # Support for other units like Imperial/Metric or alternates?
            f"Must be one of: {valid_types}"
        )
    if int(data["poll_interval_s"]) <= 0:
        raise ConfigError(f"Channel {data['id']!r} poll_interval_s must be > 0")
    return ChannelConfig(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        opc_node=data["opc_node"],
        pi_tag=data["pi_tag"],
        unit=data["unit"],
        type=data["type"],
        poll_interval_s=int(data["poll_interval_s"]),
        thresholds=_parse_thresholds(data["thresholds"], data["id"]),
    )


def _parse_detection(data: dict) -> DetectionConfig:
    s = data.get("spike", {})
    d = data.get("drift", {})
    return DetectionConfig(
        spike=SpikeDetectionConfig(
            enabled=s.get("enabled", True),
            z_threshold=float(s.get("z_threshold", 3.5)),
            crit_sigma=float(s.get("crit_sigma", 5.0)),
            min_samples=int(s.get("min_samples", 10)),
        ),
        drift=DriftDetectionConfig(
            enabled=d.get("enabled", True),
            cusum_threshold=float(d.get("cusum_threshold", 5.0)),
            cusum_slack=float(d.get("cusum_slack", 0.5)),
            window_s=int(d.get("window_s", 300)),
        ),
    )


def _parse_site(data: dict) -> SiteConfig:
    required = {"id", "name", "opc_ua_endpoint", "channels"}
    missing = required - set(data.keys())
    if missing:
        raise ConfigError(f"Site {data.get('id', '?')!r} missing keys: {missing}")
    if not data["channels"]:
        raise ConfigError(f"Site {data['id']!r} must have at least one channel")
    pi = data.get("pi_historian", {})
    return SiteConfig(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        location=data.get("location", ""),
        opc_ua_endpoint=data["opc_ua_endpoint"],
        channels=[_parse_channel(ch) for ch in data["channels"]],
        detection=_parse_detection(data.get("detection", {})),
        pi_historian=PIHistorianConfig(
            enabled=pi.get("enabled", False),
            export_path=pi.get("export_path", "./data/pi_exports"),
            tag_prefix=pi.get("tag_prefix", ""),
        ),
    )

def _parse_storage(data: dict) -> StorageConfig:
    return StorageConfig(
        db_path=data.get("db_path", "data/PipesenseStorage.db"),
        site_id=data.get("site_id", "unknown"),
    )

def _parse_report(data: dict) -> ReportConfig:
    return ReportConfig(
        report_path=data.get("report_path", "reports/run_report.md")
    )

def load_config(path: str | Path) -> PipesenseConfig:
    """Load and validate a pipesense YAML config file.

    Raises:
        ConfigError: If file is missing, invalid, or fails validation.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a YAML mapping, got: {type(raw)}")
    if "sites" not in raw or not raw["sites"]:
        raise ConfigError("Config must contain at least one site under 'sites'")
    storage = _parse_storage(raw.get("storage", {}))
    return PipesenseConfig(
        version=str(raw.get("version", "1.0")),
        sites=[_parse_site(s) for s in raw["sites"]],
        storage=storage,
        reporting=_parse_report(raw.get("reporting", {}))
    )
