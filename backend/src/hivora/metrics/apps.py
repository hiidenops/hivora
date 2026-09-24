"""Live resource usage of the apps being looked at.

Docker `stats` is sampled one-shot (never a permanent stream), every 5 s,
and only for apps that someone currently watches on the WebSocket.
"""

import asyncio
import logging
import time
from collections import Counter, deque
from contextlib import suppress
from typing import Any

from hivora.core.events import EventBus
from hivora.docker_gateway import ContainerState, DockerGateway, StatsSample
from hivora.state import StateStore

logger = logging.getLogger(__name__)

INTERVAL_S = 5.0
HISTORY = 60  # five minutes


class AppMetrics:
    def __init__(self, gateway: DockerGateway, store: StateStore, bus: EventBus,
                 interval: float = INTERVAL_S) -> None:  # fmt: skip
        self.gateway = gateway
        self.store = store
        self.bus = bus
        self.interval = interval
        self.watchers: Counter[str] = Counter()
        self.history: dict[str, deque[dict[str, Any]]] = {}
        self._previous: dict[str, tuple[float, int, int]] = {}
        self._task: asyncio.Task[None] | None = None

    def watch(self, slug: str) -> list[dict[str, Any]]:
        self.watchers[slug] += 1
        return list(self.history.get(slug, ()))

    def unwatch(self, slug: str) -> None:
        self.watchers[slug] -= 1
        if self.watchers[slug] <= 0:
            del self.watchers[slug]
            self.history.pop(slug, None)
            self._previous.pop(slug, None)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="app-metrics")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            if self.watchers:
                await asyncio.gather(*(self._sample(slug) for slug in list(self.watchers)))

    async def _sample(self, slug: str) -> None:
        running = [c for c in self.store.app(slug).containers if c.state is ContainerState.RUNNING]
        if not running:
            self._previous.pop(slug, None)
            return
        results = await asyncio.gather(
            *(self.gateway.stats_once(c.id) for c in running), return_exceptions=True
        )
        stats = [r for r in results if isinstance(r, StatsSample)]
        if not stats:
            return
        now = time.time()
        rx, tx = sum(s.net_rx for s in stats), sum(s.net_tx for s in stats)
        rx_bps = tx_bps = 0.0
        if prev := self._previous.get(slug):
            dt = max(now - prev[0], 1e-3)
            rx_bps, tx_bps = max(rx - prev[1], 0) / dt, max(tx - prev[2], 0) / dt
        self._previous[slug] = (now, rx, tx)
        sample = {
            "ts": now,
            # % of the whole machine (docker stats counts 100 % per core)
            "cpu_percent": round(sum(s.cpu_percent / max(s.online_cpus, 1) for s in stats), 2),
            "mem_bytes": sum(s.mem_bytes for s in stats),
            "mem_limit": max(s.mem_limit for s in stats),
            "net_rx_bps": round(rx_bps, 1),
            "net_tx_bps": round(tx_bps, 1),
        }
        self.history.setdefault(slug, deque(maxlen=HISTORY)).append(sample)
        self.bus.publish("metrics.app", app=slug, **sample)
