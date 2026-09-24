import asyncio

import psutil

from hivora.core.events import EventBus
from hivora.metrics.host import HostMetrics, external_traffic


def test_sample_computes_rates_from_counter_deltas() -> None:
    m = HostMetrics(EventBus())
    first, prev = m.sample(None)
    assert first.net_rx_bps == 0 and 0 < first.mem_used <= first.mem_total
    ts, rx, tx = prev
    second, _ = m.sample((ts - 10, rx - 1000, tx - 500))  # 10 s ago, 1000/500 bytes fewer
    assert 90 < second.net_rx_bps < 1_000_000 and 40 < second.net_tx_bps < 1_000_000


async def test_samples_are_kept_and_published() -> None:
    bus = EventBus()
    m = HostMetrics(bus, interval=0.02)
    async with bus.subscribe("metrics.host") as sub:
        await m.start()
        event = await asyncio.wait_for(sub.queue.get(), 1)
        await m.stop()
    assert set(event.payload) >= {"cpu_percent", "mem_used", "mem_total", "net_rx_bps"}
    assert len(m.samples) >= 1


def test_external_traffic_ignores_loopback_and_docker_links() -> None:
    recv, _ = external_traffic()
    counters = psutil.net_io_counters(pernic=True)
    lo = counters.get("lo")
    assert recv <= sum(c.bytes_recv for c in counters.values()) - (lo.bytes_recv if lo else 0)


async def test_app_metrics_sample_only_watched_apps() -> None:
    from hivora.docker_gateway import ContainerInfo, ContainerState, StatsSample
    from hivora.docker_gateway.fake import FakeDockerGateway
    from hivora.metrics.apps import AppMetrics
    from hivora.state import StateStore

    gateway, store, bus = FakeDockerGateway(), StateStore(), EventBus()
    mc = ContainerInfo(
        id="c1", name="mc-1", image="x", state=ContainerState.RUNNING,
        labels={"io.hivora.app": "mc"},
    )  # fmt: skip
    store.upsert(mc)
    gateway.put(mc)
    gateway.stats["c1"] = StatsSample(200.0, 1000, 4000, 5000, 100, online_cpus=4)
    m = AppMetrics(gateway, store, bus, interval=0.01)
    await m.start()
    await asyncio.sleep(0.05)
    await m.stop()
    assert not m.history  # nobody watches: no sampling
    assert m.watch("mc") == []
    await m._sample("mc")
    gateway.stats["c1"] = StatsSample(200.0, 1000, 4000, 15000, 100, online_cpus=4)
    await m._sample("mc")
    first, second = list(m.history["mc"])[-2:]
    assert second["cpu_percent"] == 50.0  # 2 cores of 4 = half the machine
    assert first["net_rx_bps"] == 0 and second["net_rx_bps"] > 0
    m.unwatch("mc")
    assert "mc" not in m.history and not m.watchers
