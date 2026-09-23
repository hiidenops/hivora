import asyncio
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps import (
    AppJobHandlers,
    Application,
    AppRevision,
    AppService,
    DeployRequest,
    DesiredState,
    PortConflictError,
    RevisionStatus,
    slugify,
)
from hivora.apps.models import AppSecret, Service
from hivora.compose_runner import ComposeRunner
from hivora.core.config import Settings
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.docker_gateway import ContainerInfo, ContainerState, PublishedPort
from hivora.jobs import Job, JobQueue, JobStatus
from hivora.state import StateStore
from hivora.templates import Catalog, FormValidationError

FAKE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


@dataclass
class Env:
    service: AppService
    settings: Settings
    state: StateStore
    sessions: async_sessionmaker[AsyncSession]


@pytest.fixture
async def env(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], catalog: Catalog
) -> AsyncIterator[Env]:
    settings = Settings(
        data_dir=tmp_path / "data",
        volumes_root=tmp_path / "srv",
        host_lan_ip="192.168.1.10",
        puid=os.getuid(),
        pgid=os.getgid(),
    )
    bus = EventBus()
    state = StateStore()
    jobs = JobQueue(sessions, bus)
    runner = ComposeRunner(settings.apps_dir, compose_cmd=FAKE, env={"FAKE_COMPOSE_MODE": "leak"})
    service = AppService(
        settings=settings,
        sessions=sessions,
        catalog=catalog,
        runner=runner,
        state=state,
        jobs=jobs,
        box=SecretBox(os.urandom(32)),
        bus=bus,
    )
    AppJobHandlers(service).register()
    await jobs.start()
    yield Env(service, settings, state, sessions)
    await jobs.stop()


async def run(env: Env, job: Job) -> Job:
    async with asyncio.timeout(5):
        while True:
            async with env.sessions() as session:
                current = await session.get_one(Job, job.id)
            if current.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                return current
            await asyncio.sleep(0.02)


def test_slugify() -> None:
    assert slugify("Serveur de Léa !") == "serveur-de-lea"
    assert slugify("---") == "app"


async def test_deploy_vaultwarden(env: Env) -> None:
    app, job = await env.service.deploy(DeployRequest("vaultwarden", "Coffre fort"))
    assert app.slug == "coffre-fort"
    done = await run(env, job)
    assert done.status is JobStatus.SUCCEEDED, done.error

    async with env.sessions() as session:
        app = await session.get_one(Application, app.id)
        rev = await session.get_one(AppRevision, app.current_revision_id)
        [secret] = (await session.scalars(select(AppSecret))).all()
        [svc] = (await session.scalars(select(Service))).all()
        token = (await env.service.decrypt_secrets(session, app.id))["admin_token"]

    assert rev.status is RevisionStatus.APPLIED and rev.applied_at is not None
    assert "admin_token" not in rev.inputs and rev.inputs["web_port"] == 8080
    assert token.encode() not in secret.ciphertext
    assert [(p.host_port, p.host_ip, p.exposure.value) for p in svc.ports] == [
        (8080, "192.168.1.10", "lan")
    ]

    project = env.settings.apps_dir / "coffre-fort"
    compose = (project / "compose.yaml").read_text()
    dotenv = project / ".env"
    assert compose == rev.compose_yaml and token not in compose
    assert dotenv.read_text() == f"HV_SECRET_ADMIN_TOKEN='{token}'\n"
    assert oct(dotenv.stat().st_mode & 0o777) == "0o600"
    assert (env.settings.volumes_root / "coffre-fort" / "data").is_dir()
    # The fake compose echoes .env: the job log must only show the mask.
    assert "leak HV_SECRET_ADMIN_TOKEN" in done.log and token not in done.log


async def test_invalid_form_creates_nothing(env: Env) -> None:
    with pytest.raises(FormValidationError):
        await env.service.deploy(DeployRequest("minecraft", "Cube", {"eula": False}))
    async with env.sessions() as session:
        assert (await session.scalars(select(Application))).all() == []


async def test_port_conflicts_with_containers_and_other_apps(env: Env) -> None:
    env.state.upsert(ContainerInfo(
        id="x", name="legacy-nginx", image="nginx", state=ContainerState.RUNNING,
        ports=(PublishedPort(80, "tcp", "0.0.0.0", 8080),),
    ))  # fmt: skip
    with pytest.raises(PortConflictError) as err:
        await env.service.deploy(DeployRequest("vaultwarden", "vw"))
    assert err.value.details["conflicts"] == [
        {"port": 8080, "protocol": "tcp", "used_by": "legacy-nginx", "suggestion": 8081}
    ]

    await env.service.deploy(DeployRequest("vaultwarden", "vw", {"web_port": 8081}))
    async with env.sessions() as session:
        plan = await env.service.plan_deploy(
            session, DeployRequest("vaultwarden", "vw", {"web_port": 8081})
        )
    assert plan.slug == "vw-2"
    assert [(c.port, c.used_by, c.suggestion) for c in plan.conflicts] == [(8081, "vw", 8082)]


async def test_explicit_slug_must_be_free(env: Env) -> None:
    await env.service.deploy(DeployRequest("vaultwarden", "vw", slug="vault"))
    with pytest.raises(ConflictError):
        await env.service.deploy(
            DeployRequest("vaultwarden", "vw", {"web_port": 9000}, slug="vault")
        )


async def test_stop_start_record_intent(env: Env) -> None:
    app, job = await env.service.deploy(DeployRequest("vaultwarden", "vw"))
    await run(env, job)
    assert (await run(env, await env.service.stop(app.id))).status is JobStatus.SUCCEEDED
    async with env.sessions() as session:
        assert (await session.get_one(Application, app.id)).desired_state is DesiredState.STOPPED
    assert (await run(env, await env.service.start(app.id))).status is JobStatus.SUCCEEDED
    async with env.sessions() as session:
        assert (await session.get_one(Application, app.id)).desired_state is DesiredState.RUNNING


@pytest.mark.parametrize("remove_data", [False, True])
async def test_remove(env: Env, remove_data: bool) -> None:
    app, job = await env.service.deploy(DeployRequest("vaultwarden", "vw"))
    await run(env, job)
    data = env.settings.volumes_root / "vw"
    (data / "data" / "db.sqlite3").write_text("precious")

    plan = await env.service.removal_plan(app.id)
    assert plan.files == [str(env.settings.apps_dir / "vw" / f) for f in (".env", "compose.yaml")]
    assert plan.data == [str(data)]

    done = await run(env, await env.service.remove(app.id, remove_data=remove_data))
    assert done.status is JobStatus.SUCCEEDED, done.error
    assert done.app_id is None and done.app_slug == "vw"  # job history survives
    assert not (env.settings.apps_dir / "vw").exists()
    assert data.exists() is not remove_data
    async with env.sessions() as session:
        assert (await session.scalars(select(Application))).all() == []
        assert (await session.scalars(select(AppSecret))).all() == []
