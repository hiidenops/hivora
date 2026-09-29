import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.models import Application, Origin
from hivora.core.clock import SystemClock
from hivora.core.errors import HivoraError
from hivora.core.events import EventBus, Subscription
from hivora.jobs import Job, JobContext, JobKind, JobQueue, JobStatus


async def add(
    queue: JobQueue, kind: JobKind = JobKind.START, app_id: int | None = None, **params: object
) -> int:
    async with queue.sessions() as session, session.begin():
        job = queue.add(session, kind, app_id=app_id, params=dict(params))
        await session.flush()
        job_id = job.id
    queue.wake()
    return job_id


async def wait_finished(sub: Subscription, count: int = 1) -> list[dict[str, object]]:
    done = []
    async with asyncio.timeout(3):
        async for event in sub:
            if event.topic == "job.finished":
                done.append(event.payload)
                if len(done) == count:
                    return done
    raise AssertionError


async def get(sessions: async_sessionmaker[AsyncSession], job_id: int) -> Job:
    async with sessions() as session:
        return await session.get_one(Job, job_id)


@pytest.fixture(autouse=True)
async def two_apps(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        for i in (1, 2):
            session.add(
                Application(
                    id=i,
                    slug=f"app{i}",
                    name=f"app{i}",
                    origin=Origin.TEMPLATE,
                    created_at=SystemClock().now(),
                )
            )


@pytest.fixture
async def queue(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[JobQueue]:
    q = JobQueue(sessions, EventBus(), workers=2)
    yield q
    await q.stop()


async def test_success_logs_and_progress(queue: JobQueue) -> None:
    async def handler(ctx: JobContext) -> None:
        ctx.add_secrets(["hunter2-secret"])
        await ctx.progress(50, "half way with hunter2-secret")
        await ctx.log(f"param={ctx.params['x']}")

    queue.register(JobKind.START, handler)
    sub = queue.bus.subscribe("job.*")
    await queue.start()
    job_id = await add(queue, x=1)
    [done] = await wait_finished(sub)

    job = await get(queue.sessions, job_id)
    assert done["status"] == "succeeded" and job.status is JobStatus.SUCCEEDED
    assert job.progress == 100 and job.finished_at is not None
    assert job.log == "half way with ••••••\nparam=1\n"


async def test_failure_is_recorded_redacted(queue: JobQueue) -> None:
    async def handler(ctx: JobContext) -> None:
        ctx.add_secrets(["topsecret"])
        raise HivoraError("login failed with topsecret")

    queue.register(JobKind.START, handler)
    sub = queue.bus.subscribe("job.finished")
    await queue.start()
    job_id = await add(queue)
    await wait_finished(sub)
    job = await get(queue.sessions, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error == "login failed with ••••••"
    assert "topsecret" not in job.log


async def test_same_app_jobs_are_serialized_other_apps_run_concurrently(queue: JobQueue) -> None:
    running: set[int | None] = set()
    order: list[str] = []
    overlap_same_app = False

    async def handler(ctx: JobContext) -> None:
        nonlocal overlap_same_app
        if ctx.app_id in running:
            overlap_same_app = True
        running.add(ctx.app_id)
        order.append(f"start {ctx.params['n']}")
        await asyncio.sleep(0.05)
        order.append(f"end {ctx.params['n']}")
        running.discard(ctx.app_id)

    queue.register(JobKind.START, handler)
    sub = queue.bus.subscribe("job.finished")
    await add(queue, app_id=1, n=1)  # created before the (2) workers start
    await add(queue, app_id=1, n=2)
    await add(queue, app_id=2, n=3)
    await queue.start()
    await wait_finished(sub, 3)
    assert not overlap_same_app
    assert order.index("end 1") < order.index("start 2")  # FIFO within an app
    assert order.index("start 3") < order.index("end 1")  # app 2 did not wait for app 1


async def test_cancel_queued_and_running(queue: JobQueue) -> None:
    started = asyncio.Event()

    async def slow(ctx: JobContext) -> None:
        started.set()
        await asyncio.sleep(10)

    queue.register(JobKind.START, slow)
    sub = queue.bus.subscribe("job.finished")
    await queue.start()
    running_id = await add(queue, app_id=1)
    queued_id = await add(queue, app_id=1)
    await asyncio.wait_for(started.wait(), 1)
    await queue.cancel(queued_id)
    await queue.cancel(running_id)
    await wait_finished(sub, 2)
    assert (await get(queue.sessions, queued_id)).status is JobStatus.CANCELLED
    assert (await get(queue.sessions, running_id)).status is JobStatus.CANCELLED


async def test_recover_after_crash(sessions: async_sessionmaker[AsyncSession]) -> None:
    started = asyncio.Event()

    async def slow(ctx: JobContext) -> None:
        started.set()
        await asyncio.sleep(10)

    first = JobQueue(sessions, EventBus())
    first.register(JobKind.DEPLOY, slow)
    first.register(JobKind.STOP, slow)
    await first.start()
    deploy_id = await add(first, JobKind.DEPLOY, app_id=1)
    stop_id = await add(first, JobKind.STOP, app_id=2)
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.sleep(0.05)
    await first.stop()  # simulated crash: both still "running" in the database
    assert (await get(sessions, deploy_id)).status is JobStatus.RUNNING

    second = JobQueue(sessions, EventBus())
    await second.recover()
    assert (await get(sessions, deploy_id)).status is JobStatus.QUEUED  # resumable
    stop_job = await get(sessions, stop_id)
    assert stop_job.status is JobStatus.INTERRUPTED and stop_job.error


def test_job_routes_list_detail_and_clear(client: object) -> None:
    """The /jobs routes' behaviour, pinned before their SQL moves into JobQueue."""
    import time
    from typing import Any

    from helpers import API, admin, code, wait_job

    c: Any = client
    admin(c)
    rt = c.app.state.runtime
    ids = []
    for name, inputs in (("vw1", {}), ("vw2", {"web_port": 8096})):
        deployed = c.post(f"{API}/apps", json={"template": "vaultwarden", "name": name,
                                               "inputs": inputs}).json()  # fmt: skip
        assert wait_job(c, deployed["job"]["id"])["status"] == "succeeded"
        ids.append(deployed["app"]["id"])
    app1, app2 = ids

    # No worker from here on: queued and running jobs keep their status.
    c.portal.call(rt.jobs.stop)

    async def insert() -> None:
        async with rt.sessions() as session, session.begin():
            now = rt.clock.now()
            rows = ((app1, JobStatus.QUEUED), (app2, JobStatus.RUNNING),
                    (app1, JobStatus.FAILED), (app2, JobStatus.CANCELLED))  # fmt: skip
            for app_id, status in rows:
                session.add(Job(kind=JobKind.RESTART, app_id=app_id, app_slug="x", params={},
                                status=status, log=f"log of {status.value}",
                                created_at=now))  # fmt: skip

    c.portal.call(insert)

    # GET /jobs: newest first, filter by app, limit.
    every = c.get(f"{API}/jobs").json()
    assert [j["id"] for j in every] == sorted((j["id"] for j in every), reverse=True)
    assert len(every) == 6  # 2 deploys + 4 inserted
    of_app1 = c.get(f"{API}/jobs", params={"app_id": app1}).json()
    assert of_app1 and {j["app_id"] for j in of_app1} == {app1}
    assert [j["id"] for j in of_app1] == sorted((j["id"] for j in of_app1), reverse=True)
    assert [j["id"] for j in c.get(f"{API}/jobs", params={"limit": 2}).json()] == [
        every[0]["id"], every[1]["id"],
    ]  # fmt: skip
    assert c.get(f"{API}/jobs", params={"limit": 0}).status_code == 422

    # GET /jobs/{id}: the detail adds the log; an unknown id is a plain 404.
    newest = c.get(f"{API}/jobs/{every[0]['id']}").json()
    assert newest["log"] == "log of cancelled" and newest["status"] == "cancelled"
    missing = c.get(f"{API}/jobs/999999")
    assert missing.status_code == 404 and code(missing) == "not_found"
    assert missing.json()["error"]["message"] == "job not found"

    # DELETE /jobs: finished jobs go, queued and running ones stay; jobs.cleared is audited.
    bus = rt.bus
    published: list[tuple[str, dict[str, Any]]] = []
    real_publish = bus.publish

    def spy(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real_publish(topic, **payload)

    bus.publish = spy
    try:
        assert c.delete(f"{API}/jobs").json() == {"deleted": 4}  # 2 deploys, failed, cancelled
    finally:
        bus.publish = real_publish
    assert ("jobs.cleared", {"deleted": 4}) in published
    left = c.get(f"{API}/jobs").json()
    assert sorted(j["status"] for j in left) == ["queued", "running"]
    time.sleep(0.8)  # the audit recorder writes in small batches
    cleared = [a for a in c.get(f"{API}/audit").json() if a["action"] == "jobs.cleared"]
    assert len(cleared) == 1 and cleared[0]["payload"] == {"deleted": 4}
    assert cleared[0]["username"] == "admin"
