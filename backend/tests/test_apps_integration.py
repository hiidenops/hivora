"""M3 exit criterion: Vaultwarden deployed through AppService + jobs on a real Engine."""

import asyncio
import os
import socket
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps import AppJobHandlers, AppService, DeployRequest
from hivora.compose_runner import ComposeRunner
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.docker_gateway import DockerUnavailableError
from hivora.docker_gateway.local import LocalDockerGateway
from hivora.jobs import Job, JobQueue, JobStatus
from hivora.state import AppStatus, StateService
from hivora.templates import Catalog

pytestmark = pytest.mark.docker


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def stack(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], catalog: Catalog
) -> AsyncIterator[tuple[AppService, StateService]]:
    gateway = LocalDockerGateway()
    try:
        await gateway.ping()
    except DockerUnavailableError:
        await gateway.close()
        pytest.skip("Docker is not reachable")
    settings = Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv")
    bus = EventBus()
    state = StateService(gateway, bus)
    jobs = JobQueue(sessions, bus)
    service = AppService(
        settings=settings,
        sessions=sessions,
        catalog=catalog,
        runner=ComposeRunner(settings.apps_dir),
        state=state.store,
        jobs=jobs,
        box=SecretBox(os.urandom(32)),
        bus=bus,
    )
    AppJobHandlers(service).register()
    await state.start()
    await jobs.start()
    yield service, state
    await jobs.stop()
    await state.stop()
    await gateway.close()


async def finished(service: AppService, job: Job, within: float) -> Job:
    async with asyncio.timeout(within):
        while True:
            async with service.sessions() as session:
                current = await session.get_one(Job, job.id)
            if current.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                assert current.status is JobStatus.SUCCEEDED, current.log
                return current
            await asyncio.sleep(0.2)


async def status_becomes(state: StateService, slug: str, status: AppStatus) -> None:
    async with state.bus.subscribe("state.app.changed") as sub, asyncio.timeout(2):  # budget
        while state.store.app(slug).status is not status:
            await sub.queue.get()


async def test_vaultwarden_end_to_end(stack: tuple[AppService, StateService]) -> None:
    service, state = stack
    port = free_port()
    app, job = await service.deployer.deploy(
        DeployRequest("vaultwarden", "Coffre IT", {"web_port": port,
                                                   "domain": f"http://localhost:{port}"})
    )  # fmt: skip
    try:
        done = await finished(service, job, within=300)  # includes the image pull
        assert "Pulling images" in done.log
        await status_becomes(state, app.slug, AppStatus.HEALTHY)

        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/alive", timeout=5).read()
        )
        assert body  # Vaultwarden answers with a timestamp

        await finished(service, await service.lifecycle.stop(app.id), within=60)
        await status_becomes(state, app.slug, AppStatus.STOPPED)
        await finished(service, await service.lifecycle.start(app.id), within=120)
        await status_becomes(state, app.slug, AppStatus.HEALTHY)
    finally:
        await finished(service, await service.lifecycle.remove(app.id, remove_data=True), within=60)
    await status_becomes(state, app.slug, AppStatus.MISSING)
    assert not service.volumes_dir(app.slug).exists()
