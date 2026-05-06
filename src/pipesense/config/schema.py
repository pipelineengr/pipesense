"""Schema for pipesense site configuration."""

from dataclasses import dataclass, field
from typing import Literal

ChannelType = Literal[
    "flow", "pressure", "temperature", "level", "vibration"
]  # Five parameters to monitor and control


@dataclass
class Thresholds:
    """Alarm thresholds(Configured similar to the industry conventions for SCADA)."""

    high_high: float
    high: float
    low: float
    low_low: float

    def check(self, value: float) -> str | None:
        """Return alarm level if value breaches a threshold, else None."""
        if value >= self.high_high:
            return "HIGH_HIGH"
        if value <= self.low_low:
            return "LOW_LOW"
        if value >= self.high:
            return "HIGH"
        if value <= self.low:
            return "LOW"
        return None


@dataclass
class ChannelConfig:  # Config for individual signals incl. an unique id, name and pi tag address etc.
    id: str
    name: str
    description: str
    opc_node: str
    pi_tag: str
    unit: str
    type: ChannelType
    poll_interval_s: int
    thresholds: Thresholds


@dataclass
class SpikeDetectionConfig:
    enabled: bool = True
    z_threshold: float = 3.5
    min_samples: int = 10


@dataclass
class DriftDetectionConfig:
    enabled: bool = True
    cusum_threshold: float = 5.0
    cusum_slack: float = 0.5
    window_s: int = 300


@dataclass
class DetectionConfig:
    spike: SpikeDetectionConfig = field(default_factory=SpikeDetectionConfig)
    drift: DriftDetectionConfig = field(default_factory=DriftDetectionConfig)


@dataclass
class PIHistorianConfig:
    enabled: bool = False
    export_path: str = "./data/pi_exports"
    tag_prefix: str = ""


@dataclass
class SiteConfig:
    """Complete configuration for a single monitored site."""

    id: str
    name: str
    description: str
    location: str
    opc_ua_endpoint: str
    channels: list[ChannelConfig]
    detection: DetectionConfig
    pi_historian: PIHistorianConfig = field(default_factory=PIHistorianConfig)

    @property
    def channel_ids(self) -> list[str]:
        return [ch.id for ch in self.channels]

    def get_channel(self, channel_id: str) -> ChannelConfig | None:
        return next((ch for ch in self.channels if ch.id == channel_id), None)

    def channels_by_type(self, channel_type: ChannelType) -> list[ChannelConfig]:
        return [ch for ch in self.channels if ch.type == channel_type]


@dataclass
class PipesenseConfig:
    version: str
    sites: list[SiteConfig]

    def get_site(self, site_id: str) -> SiteConfig | None:
        return next((s for s in self.sites if s.id == site_id), None)
