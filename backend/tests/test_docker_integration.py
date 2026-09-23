"""End-to-end: real Engine + real `docker compose` + StateService.

Skipped when Docker is unreachable. Uses a tiny multi-arch image.
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from hivora.compose_runner import ComposeRunner, ProgressEvent
from hivora.core.events import EventBus, Subscription
from hivora.docker_gateway import DockerUnavailableError
from hivora.docker_gateway.local import LocalDockerGateway
from hivora.state import AppStatus, StateService

pytestmark = pytest.mark.docker

STATE_BUDGET_S = 2.0  # "state updated < 2 s after a Docker event"

COMPOSE = """\
services:
  web:
    image: traefik/whoami:v1.10
    labels:
      io.hivora.app: {slug}
    environment:
      WHOAMI_NAME: {secret}
    healthcheck:
      test: ["CMD", "/whoami", "--help"]
      interval: 1s
      start_period: 1s
"""


@pytest.fixture
async def gateway() -> AsyncIterator[LocalDockerGateway]:
    gw = LocalDockerGateway()
    try:
        await gw.ping()
    except DockerUnavailableError:
        await gw.close()
        pytest.skip("Docker is not reachable")
    yield gw
    await gw.close()


async def wait_status(
    service: StateService, sub: Subscription, slug: str, status: AppStatus
) -> None:
    """Wait for the app to reach ``status`` within the state-propagation budget."""
    async with asyncio.timeout(STATE_BUDGET_S):
        while service.store.app(slug).status is not status:
            await sub.queue.get()


async def test_deploy_observe_stop_remove(gateway: LocalDockerGateway, tmp_path: Path) -> None:
    slug = f"it-{secrets.token_hex(4)}"
    secret = secrets.token_hex(8)
    runner = ComposeRunner(tmp_path / "apps")
    runner.write(slug, COMPOSE.format(slug=slug, secret=secret))
    bus = EventBus()
    sub = bus.subscribe("state.app.changed")
    service = StateService(gateway, bus)
    await service.start()
    progress: list[ProgressEvent] = []

    async def collect(event: ProgressEvent) -> None:
        progress.append(event)

    try:
        async with asyncio.timeout(5):
            await service.wait_synced()

        config = await runner.config(slug, redact=[secret])
        assert config["name"] == slug
        assert secret not in str(config)

        async with runner.lock(slug):
            await runner.up(slug, on_progress=collect, redact=[secret])
        assert any("Container" in e.resource for e in progress)
        await wait_status(service, sub, slug, AppStatus.HEALTHY)

        [container] = service.store.app(slug).containers
        sample = await gateway.stats_once(container.id)
        assert sample.mem_bytes > 0
        logs = [line async for line in gateway.logs(container.id, tail=20)]
        assert any("80" in line for line in logs)  # whoami logs its listening port

        await runner.stop(slug)
        await wait_status(service, sub, slug, AppStatus.STOPPED)

        await runner.down(slug, remove_volumes=True)
        await wait_status(service, sub, slug, AppStatus.MISSING)
    finally:
        await runner.down(slug, remove_volumes=True)
        await service.stop()
