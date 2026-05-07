"""Abstract base class for all pipesense data sources so each can be configured independently and more can be added in the future"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TagReading:
    """A single timestamped reading from one channel/tag.

    Mirrors what PI typically stores for each tag: value, timestamp, quality.
    Quality follows OPC-UA/PI convention: 'Good', 'Bad', 'Uncertain'.
    """
    tag_id: str
    value: float
    timestamp: datetime
    quality: str = "Good"
    unit: str = ""

    @property
    def is_good(self) -> bool:
        return self.quality == "Good"

    @classmethod
    def bad(cls, tag_id: str, reason: str = "Bad") -> "TagReading":
        """Create a bad-quality reading placeholder."""
        return cls(
            tag_id=tag_id,
            value=float("nan"),
            timestamp=datetime.now(timezone.utc),
            quality=reason,
        )


@dataclass
class SourceStatus:
    """Connection status details for a data source."""
    connected: bool
    source_type: str
    endpoint: str
    n_tags: int
    last_error: str | None = None


class DataSource(ABC):
    """Abstract base for OPC-UA, PI historian, and mock sources.

    All pipesense consumers (poller, detector, storage) depend
    on this interface — the concrete source is injected at runtime.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Open connection to the data source."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection cleanly."""

    @abstractmethod
    async def read_tag(self, tag_id: str) -> TagReading:
        """Read the current value of a single tag.

        Args:
            tag_id: OPC node string or PI tag name.

        Returns:
            TagReading with value, timestamp, and quality.
        """

    @abstractmethod
    async def read_tags(self, tag_ids: list[str]) -> list[TagReading]:
        """Read multiple tags in a single round trip where possible."""

    @abstractmethod
    def status(self) -> SourceStatus:
        """Return current connection status."""

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()