"""OPC-UA virtual source — simulates a field instrument"""

import logging
from datetime import datetime, timezone

from asyncua import Client

from pipesense.sources.base import DataSource, SourceStatus, TagReading

logger = logging.getLogger(__name__)


class OpcUaSource(DataSource):
    """OPC-UA client implementing the Data source.

    Connects to any OPC-UA server — real hardware gateway or virtual server created here.
    All that is needed is the server address.
    """

    def __init__(self, endpoint: str, timeout_s: float = 10.0) -> None:
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._client: Client | None = None
        self._last_error: str | None = None
        self._tag_count = 0

        # [INIT] Print statement to confirm that the source is initialized.
        # print(f"[INIT] OpcUaSource created: endpoint={endpoint!r} "
        #       f"timeout={timeout_s}s")

    async def connect(self) -> None:
        self._client = Client(url=self._endpoint, timeout=self._timeout_s)
        await self._client.connect()

        # [CONNECT] Print statement to confirm a successful connection.
        # print(f"[CONNECT] OpcUaSource CONNECTED to {self._endpoint!r}")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

            # [CONNECT] Print statement to confirm a successful disconnect.
            # print(f"[CONNECT] OpcUaSource DISCONNECTED from {self._endpoint!r}")

    async def read_tag(self, tag_id: str) -> TagReading:
        """Read a single OPC-UA node by its node string."""
        if self._client is None:
            return TagReading.bad(tag_id, reason="Not connected")

        # [READ] Print statement to trace every individual tag read call.
        # Useful for seeing how many reads fire per poll cycle.
        # print(f"[READ] reading tag: {tag_id!r}")

        try:
            node = self._client.get_node(tag_id)
            dv = await node.read_data_value()

            quality = _parse_quality(dv.StatusCode)
            value = (
                float(dv.Value.Value) if dv.Value.Value is not None else float("nan")
            )
            ts = dv.SourceTimestamp or datetime.now(timezone.utc)

            # [READ] Print statement to see the full result of every tag read.
            # Shows value, quality, and source timestamp from the server.
            # print(f"[READ] tag={tag_id!r} value={value:.4f} "
            #       f"quality={quality!r} ts={ts.isoformat()}")

            return TagReading(
                tag_id=tag_id,
                value=value,
                timestamp=ts,
                quality=quality,
            )
        except Exception as exc:
            self._last_error = str(exc)

            # [READ] Print statement to see every read exception with full detail.
            # Essential for debugging connection or node-address problems.
            # print(f"[READ] ERROR reading {tag_id!r}: {type(exc).__name__}: {exc}")

            return TagReading.bad(tag_id, reason=f"ReadError: {exc}")

    async def read_tags(self, tag_ids: list[str]) -> list[TagReading]:
        results = []
        for tag_id in tag_ids:
            results.append(await self.read_tag(tag_id))

        # [READ] Print statement to see batch summary: good vs bad readings.
        # good = sum(1 for r in results if r.is_good)
        # print(f"[READ] read_tags complete: {good}/{len(results)} good")

        return results

    def status(self) -> SourceStatus:
        return SourceStatus(
            connected=self._client is not None,
            source_type="OPC-UA",  # Source name for the virtual OPC-UA Server
            endpoint=self._endpoint,
            n_tags=self._tag_count,
            last_error=self._last_error,
        )


def _parse_quality(status_code) -> str:
    """Map OPC-UA StatusCode to PI-style quality string."""
    try:
        if status_code.is_good():
            # print(f"[QUALITY] StatusCode resolved → 'Good'")
            return "Good"
        if status_code.is_uncertain():
            # print(f"[QUALITY] StatusCode resolved → 'Uncertain'")
            return "Uncertain"

        # print(f"[QUALITY] StatusCode resolved → 'Bad' (code={status_code})")
        return "Bad"
    except Exception:
        # print(f"[QUALITY] _parse_quality exception: {exc}")
        return "Unknown"
