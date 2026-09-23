import asyncio
from collections.abc import AsyncIterator

import pytest

from hivora.core.events import Event, EventBus, Subscription
from hivora.docker_gateway import ContainerInfo, ContainerState, Health
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.state import AppStatus, StateService, aggregate_status, app_key

R, X, C = ContainerState.RUNNING, ContainerState.EXITED, ContainerState.CREATED


def ctr(
    cid: str = "c1",
    state: ContainerState = R,
    health: Health = Health.NONE,
    exit_code: int | None = None,
    app: str | None = "demo",
    project: str | None = None,
) -> ContainerInfo:
    labels = {}
    if app:
        labels["io.hivora.app"] = app
    if project:
        labels["com.docker.compose.project"] = project
    return ContainerInfo(
        id=cid,
        name=cid,
        image="img",
        state=state,
        health=health,
        exit_code=exit_code,
        labels=labels,
    )


@pytest.mark.parametrize(
    ("containers", "expected"),
    [
        ([], AppStatus.MISSING),
        ([ctr()], AppStatus.HEALTHY),
        ([ctr(health=Health.HEALTHY), ctr("c2", X, exit_code=0)], AppStatus.HEALTHY),
        ([ctr(health=Health.STARTING)], AppStatus.STARTING),
        ([ctr(), ctr("c2", X, exit_code=1)], AppStatus.DEGRADED),
        ([ctr(), ctr("c2", health=Health.UNHEALTHY)], AppStatus.DEGRADED),
        ([ctr(), ctr("c2", C)], AppStatus.DEGRADED),
        ([ctr(state=X, exit_code=0)], AppStatus.STOPPED),
        ([ctr(state=X, exit_code=137)], AppStatus.ERROR),
        ([ctr(state=ContainerState.RESTARTING)], AppStatus.ERROR),
        ([ctr(health=Health.UNHEALTHY)], AppStatus.ERROR),
    ],
)
def test_aggregate_status(containers: list[ContainerInfo], expected: AppStatus) -> None:
    assert aggregate_status(containers) is expected


def test_requested_stop_is_not_a_failure() -> None:
    stopped = ctr("c1", X, exit_code=2)
    assert aggregate_status([stopped]) is AppStatus.ERROR
    assert aggregate_status([stopped], {"c1"}) is AppStatus.STOPPED


def test_app_key() -> None:
    assert app_key(ctr(app="demo", project="demo")) == "demo"
    assert app_key(ctr(app=None, project="karim")) == "compose:karim"
    assert app_key(ctr(app=None)) is None


async def next_event(sub: Subscription, topic: str) -> Event:
    async with asyncio.timeout(1):
        async for event in sub:
            if event.topic == topic:
                return event
    raise AssertionError


@pytest.fixture
async def running() -> AsyncIterator[tuple[FakeDockerGateway, StateService, Subscription]]:
    gw, bus = FakeDockerGateway(), EventBus()
    gw.put(ctr("c1", health=Health.STARTING))
    sub = bus.subscribe("state.*")
    service = StateService(gw, bus, reconnect_delays=(0.01,))
    await service.start()
    async with asyncio.timeout(1):
        await service.wait_synced()
    yield gw, service, sub
    await service.stop()


async def test_initial_sync_publishes_app_status(
    running: tuple[FakeDockerGateway, StateService, Subscription],
) -> None:
    _, service, sub = running
    event = await next_event(sub, "state.app.changed")
    assert event.payload == {"app": "demo", "status": "starting", "previous": "missing"}
    assert service.store.app("demo").status is AppStatus.STARTING


async def test_events_update_status(
    running: tuple[FakeDockerGateway, StateService, Subscription],
) -> None:
    gw, service, sub = running
    await next_event(sub, "state.synced")
    await asyncio.sleep(0)  # let the service subscribe to the fake stream

    gw.update("c1", "health_status: healthy", health=Health.HEALTHY)
    assert (await next_event(sub, "state.app.changed")).payload["status"] == "healthy"

    gw.update("c1", "kill")
    gw.update("c1", "die", state=X, exit_code=2)
    assert (await next_event(sub, "state.app.changed")).payload["status"] == "stopped"

    gw.update("c1", "start", state=R, exit_code=None)
    assert (await next_event(sub, "state.app.changed")).payload["status"] == "healthy"

    gw.update("c1", "die", state=X, exit_code=1)  # crash: no kill before
    assert (await next_event(sub, "state.app.changed")).payload["status"] == "error"

    gw.remove("c1")
    assert (await next_event(sub, "state.app.changed")).payload["status"] == "missing"
    assert service.store.containers() == []


async def test_irrelevant_actions_are_ignored(
    running: tuple[FakeDockerGateway, StateService, Subscription],
) -> None:
    gw, _, sub = running
    await next_event(sub, "state.synced")
    await asyncio.sleep(0)
    gw.update("c1", "exec_start: sh", health=Health.HEALTHY)
    with pytest.raises(TimeoutError):
        await next_event(sub, "state.container.changed")


async def test_resyncs_after_stream_drop(
    running: tuple[FakeDockerGateway, StateService, Subscription],
) -> None:
    gw, service, sub = running
    await next_event(sub, "state.synced")
    await asyncio.sleep(0)
    # Change happens while disconnected: no event, only the resync can see it.
    gw.containers["c1"] = ctr("c1", health=Health.HEALTHY)
    gw.disconnect()
    await next_event(sub, "state.synced")
    assert service.store.app("demo").status is AppStatus.HEALTHY
