"""Host metrics: one sample every 2 s, last hour kept in memory, pushed on the bus."""

import asyncio
import time
from collections import deque
from contextlib import suppress
from dataclasses import asdict, dataclass

import psutil

from hivora.core.events import EventBus

# Host counters via psutil are cheap (unlike per-container Docker stats, kept at
# 10 s by the budget): 2 s makes the live charts feel continuous.
INTERVAL_S = 2.0
HISTORY = 1800  # one hour


# Loopback counts every byte both ways; Docker's bridges and veth pairs count
# container traffic twice. Only the machine's own links say what enters/leaves it.
_VIRTUAL = ("lo", "veth", "docker", "br-")


def external_traffic() -> tuple[int, int]:
    counters = psutil.net_io_counters(pernic=True)
    real = [c for name, c in counters.items() if not name.startswith(_VIRTUAL)]
    return sum(c.bytes_recv for c in real), sum(c.bytes_sent for c in real)


@dataclass(frozen=True, slots=True)
class HostSample:
    ts: float
    cpu_percent: float
    mem_used: int
    mem_total: int
    net_rx_bps: float  # bytes per second, all interfaces
    net_tx_bps: float


class HostMetrics:
    # ponytail: in-memory only; persist 1 min / 5 min aggregates (metric_sample) for the 24 h view.
    # Inside the Hivora container, psutil sees the container's network namespace: host
    # network rates need /proc of the host mounted read-only (M6).
    def __init__(self, bus: EventBus, interval: float = INTERVAL_S) -> None:
        self.bus = bus
        self.interval = interval
        self.samples: deque[HostSample] = deque(maxlen=HISTORY)
        self._task: asyncio.Task[None] | None = None

    def sample(
        self, previous: tuple[float, int, int] | None
    ) -> tuple[HostSample, tuple[float, int, int]]:
        now = time.time()
        mem = psutil.virtual_memory()
        recv, sent = external_traffic()
        rx = tx = 0.0
        if previous:
            dt = max(now - previous[0], 1e-3)
            rx = max(recv - previous[1], 0) / dt
            tx = max(sent - previous[2], 0) / dt
        s = HostSample(
            now,
            psutil.cpu_percent(interval=None),
            mem.total - mem.available,
            mem.total,
            round(rx, 1),
            round(tx, 1),
        )
        return s, (now, recv, sent)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="host-metrics")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        psutil.cpu_percent(interval=None)  # first call only primes the counter
        _, previous = self.sample(None)
        while True:
            await asyncio.sleep(self.interval)
            s, previous = self.sample(previous)
            self.samples.append(s)
            self.bus.publish("metrics.host", **asdict(s))
