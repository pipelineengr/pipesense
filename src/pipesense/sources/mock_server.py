"""OPC-UA virtual server — simulates a field instrument"""

import asyncio
import logging
from dataclasses import dataclass

from asyncua import Server, ua

from pipesense.config.schema import SiteConfig
from pipesense.sources.simulate import CHANNEL_SIMULATORS

logger = logging.getLogger(__name__)


@dataclass
class MockServerConfig:
    endpoint: str = (
        "opc.tcp://localhost:4840"  # Server is created in the local machine for testing
    )
    namespace: str = "urn:pipesense:mock"  # Identifier for the OPC-UA server
    update_interval_s: float = 1.0


class MockOpcUaServer:
    """Virtual OPC-UA server that publishes values for the five variables
    within the site channel.

    Equivalent to a Kepware server connected to the equipment — presents realistic tag values
    over OPC-UA based on the value functions in simulate.py without real field hardware.
    """

    def __init__(
        self,
        site: SiteConfig,
        config: MockServerConfig | None = None,
    ) -> None:
        self._site = site
        self._cfg = config or MockServerConfig()
        self._server = Server()
        self._nodes: dict[str, object] = {}
        self._running = False
        self._update_task: asyncio.Task | None = None

        # [INIT] Statement to confirm server object creation and config.
        # print(f"[INIT] MockOpcUaServer created for site={site.id!r} "
        #       f"endpoint={self._cfg.endpoint!r} "
        #       f"update_interval={self._cfg.update_interval_s}s")

    async def start(self) -> None:
        """Start the OPC-UA server and begin publishing values."""
        await self._server.init()
        self._server.set_endpoint(self._cfg.endpoint)
        self._server.set_server_name(f"pipesense mock — {self._site.name}")

        idx = await self._server.register_namespace(self._cfg.namespace)
        objects = self._server.get_objects_node()
        site_node = await objects.add_object(idx, self._site.id)

        for ch in self._site.channels:
            sim_fn = CHANNEL_SIMULATORS.get(ch.type)
            initial = sim_fn() if sim_fn else 0.0
            # var = await site_node.add_variable(idx, ch.opc_node, initial)
            node_id = ua.NodeId(
                ch.opc_node.split(";s=")[1], idx
            )  # e.g. "LACT001.FT101.PV" in ns=2
            var = await site_node.add_variable(node_id, ch.opc_node, initial)
            await var.set_writable()
            self._nodes[ch.opc_node] = var

            # [INIT] Statement to see each OPC-UA node as it is registered.
            # Shows the mapping: opc_node string → initial simulated value.
            # print(f"[INIT] Registered OPC node: {ch.opc_node!r} "
            #       f"type={ch.type!r} initial={initial:.4f}")

        await self._server.start()
        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())

        # [CONNECT] Print statement to confirm server started successfully.
        # print(f"[CONNECT] Mock server STARTED at {self._cfg.endpoint!r} "
        #       f"with {len(self._nodes)} nodes")

    async def stop(self) -> None:
        """Stop publishing and shut down the server."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        await self._server.stop()

        # [CONNECT] Print statement to confirm clean shutdown.
        # print(f"[CONNECT] Mock server STOPPED at {self._cfg.endpoint!r}")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def _update_loop(self) -> None:
        """Continuously update all node values at configured interval."""
        cycle = 0
        while self._running:
            cycle += 1
            for ch in self._site.channels:
                node = self._nodes.get(ch.opc_node)
                if node is None:
                    continue
                sim_fn = CHANNEL_SIMULATORS.get(ch.type)
                if sim_fn:
                    value = sim_fn()
                    await node.write_value(value)

                    # [POLL] Print statement to watch the server update loop
                    # writing new values to each OPC node every cycle.
                    # print(f"[POLL] cycle={cycle} node={ch.id!r} "
                    #       f"type={ch.type!r} new_value={value:.4f}")

            # [POLL] Print statement to see each full update cycle completing.
            # print(f"[POLL] Update cycle {cycle} complete — "
            #       f"sleeping {self._cfg.update_interval_s}s")

            await asyncio.sleep(self._cfg.update_interval_s)

    def inject_value(self, opc_node: str, value: float) -> None:
        """Queue a specific value for testing anomalies."""
        self._injected = getattr(self, "_injected", {})
        self._injected[opc_node] = value

        # [SIM] Print statement to confirm anomaly injection is registered.
        # print(f"[SIM] inject_value: node={opc_node!r} value={value:.4f}")
