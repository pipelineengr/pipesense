"""Source function to allow the internal simulator identical to the OPC-UA and PI data sources
all three work the same way - connect / disconnect / read_tag / read_tags / status
"""
from datetime import datetime, timezone

from pipesense.config.schema import SiteConfig
from pipesense.sources.base import DataSource, SourceStatus, TagReading
from pipesense.sources.simulate import CHANNEL_SIMULATORS


class SimulatorSource(DataSource):
    """Wraps CHANNEL_SIMULATORS as a DataSource.

    Accepts opc_node strings as tag_ids (same as OpcUaSource) and
    resolves them to channel types internally.
    """

    def __init__(self, site: SiteConfig) -> None:
        self._site               = site
        self._connected          = False
        self._last_error: str | None = None
        self._opc_to_channel: dict[str, str] = {
            ch.opc_node: ch.id for ch in site.channels
        }
        self._channel_to_type: dict[str, str] = {
            ch.id: ch.type for ch in site.channels
        }

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_tag(self, tag_id: str) -> TagReading:
        """tag_id is an opc_node string — resolve to channel then simulate."""
        channel_id   = self._opc_to_channel.get(tag_id, tag_id)
        channel_type = self._channel_to_type.get(channel_id)
        sim_fn       = CHANNEL_SIMULATORS.get(channel_type) if channel_type else None

        if sim_fn is None:
            return TagReading.bad(tag_id, reason=f"No simulator for type={channel_type!r}")

        return TagReading(
            tag_id=channel_id,
            value=sim_fn(),
            timestamp=datetime.now(timezone.utc),
            quality="Good",
        )

    async def read_tags(self, tag_ids: list[str]) -> list[TagReading]:
        return [await self.read_tag(t) for t in tag_ids]

    def status(self) -> SourceStatus:
        return SourceStatus(
            connected=self._connected,
            source_type="Simulator",
            endpoint="built-in",
            n_tags=len(self._site.channels),
            last_error=self._last_error,
        )