"""The Update button (M13): the release's image only, a fixed sequence, a roll back."""

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from helpers import API, admin, code, wait_job

from hivora import __version__
from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.system.releases import release_digest
from hivora.system.self_update import STATE, clone, read_state, run_updater, write_state

DIGEST = "sha256:" + "a" * 64
NEW = f"ghcr.io/hivora-suite/hivora-panel@{DIGEST}"
IMAGE_ENV = ["PATH=/venv/bin:/usr/bin", "HIVORA_COMPOSE_CMD=docker-compose"]
OLD = {
    "Id": "0123456789abcdef", "Name": "/hivora", "Image": "sha256:old",
    "Config": {"Env": [*IMAGE_ENV, "HIVORA_ACCESS=vpn+lan", "HIVORA_DATA_DIR=/opt/hivora/data"],
               "Labels": {"io.hivora.self": "true", "org.opencontainers.image.version": "0.3.5"},
               "ExposedPorts": {"8443/tcp": {}}},
    "HostConfig": {"Binds": ["/var/run/docker.sock:/var/run/docker.sock",
                             "/opt/hivora/data:/opt/hivora/data", "/srv/hivora:/srv/hivora"],
                   "PortBindings": {"8443/tcp": [{"HostIp": "192.168.1.10", "HostPort": "8443"}]},
                   "RestartPolicy": {"Name": "unless-stopped"},
                   "NetworkMode": "hivora-zone-administration"},
    "NetworkSettings": {"Networks": {"hivora-zone-administration": {
        "IPAMConfig": {"IPv4Address": "10.254.254.2"}, "Aliases": ["0123456789ab"]}}},
}  # fmt: skip
OLD_IMAGE = {"Config": {"Env": IMAGE_ENV,
                        "Labels": {"org.opencontainers.image.version": "0.3.5"}}}  # fmt: skip


class FakeSelf:
    """Hivora's container and what the update does to it."""

    def __init__(self, *, health: str = "healthy", digests: list[str] | None = None) -> None:
        self.containers: dict[str, dict[str, Any]] = {"hivora": OLD}
        self.running = {"hivora"}
        self.calls: list[str] = []
        self.health_now, self.digests = health, digests if digests is not None else [NEW]
        self.launched: list[Any] = []

    async def find_self(self) -> dict[str, Any] | None:
        return self.containers.get("hivora")

    async def inspect(self, name: str) -> dict[str, Any]:
        return self.containers[name]

    async def exists(self, name: str) -> bool:
        return name in self.containers

    async def image(self, ref: str) -> dict[str, Any]:
        return OLD_IMAGE

    async def pull(self, ref: str) -> list[str]:
        self.calls.append(f"pull {ref}")
        return self.digests

    async def stop(self, name: str, grace: int = 30) -> None:
        self.calls.append(f"stop {name}")
        self.running.discard(name)

    async def rename(self, name: str, new: str) -> None:
        self.calls.append(f"rename {name} {new}")
        self.containers[new] = self.containers.pop(name)

    async def start(self, name: str) -> None:
        self.calls.append(f"start {name}")
        self.running.add(name)

    async def remove(self, name: str) -> None:
        self.calls.append(f"remove {name}")
        self.containers.pop(name)

    async def create(self, name: str, body: dict[str, Any]) -> None:
        self.calls.append(f"create {name} {body['Image']}")
        self.containers[name] = {**body, "Image": body["Image"]}

    async def connect(self, network: str, name: str, endpoint: dict[str, Any]) -> None:
        self.calls.append(f"connect {network}")

    async def run(self, image: str, cmd: list[str], binds: list[str],
                  env: list[str]) -> tuple[int, str]:  # fmt: skip
        self.calls.append(f"run {image} {' '.join(cmd)} {' '.join(binds)}")
        return 0, ""

    async def launch_updater(self, image: str, cmd: list[str], data_dir: str,
                             env: list[str]) -> None:  # fmt: skip
        self.launched.append((image, cmd, data_dir))

    async def wait_healthy(self, name: str, within: float, every: float = 2) -> str:
        return self.health_now

    async def close(self) -> None:
        pass


def test_the_new_container_is_the_old_one_with_another_image() -> None:
    body, others = clone(OLD, OLD_IMAGE, NEW)
    assert body["Image"] == NEW and others == {}
    assert body["Env"] == ["HIVORA_ACCESS=vpn+lan", "HIVORA_DATA_DIR=/opt/hivora/data"]
    assert body["Labels"] == {"io.hivora.self": "true"}  # the version label: the new image's
    assert body["HostConfig"] == OLD["HostConfig"]
    endpoint = body["NetworkingConfig"]["EndpointsConfig"]["hivora-zone-administration"]
    assert endpoint == {"IPAMConfig": {"IPv4Address": "10.254.254.2"}}  # its fixed IP kept
    assert release_digest(f"Image : `x`, digest `{DIGEST}` (`x@{DIGEST}`).") == DIGEST


def data_dir(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "hivora.db") as db:
        db.execute("CREATE TABLE t (v TEXT)")
        db.execute("INSERT INTO t VALUES ('before')")
    write_state(data, {"job": 7, "from": "0.3.5", "tag": "v0.3.6", "image": NEW,
                       "container": "hivora", "status": "running", "error": None,
                       "log": []})  # fmt: skip
    return Settings(data_dir=data)


def test_updated_then_the_previous_one_removed(tmp_path: Path) -> None:
    settings, docker = data_dir(tmp_path), FakeSelf()
    state = asyncio.run(run_updater(settings, docker))
    assert state["status"] == "succeeded" and read_state(settings.data_dir) == state
    assert docker.calls == [
        "stop hivora", "rename hivora hivora-previous",
        f"run {NEW} python -m hivora bootstrap /opt/hivora/data:/opt/hivora/data "
        "/srv/hivora:/srv/hivora",  # no socket for bootstrap
        f"create hivora {NEW}", "start hivora", "remove hivora-previous",
    ]  # fmt: skip
    assert list((settings.data_dir / "backups" / "_hivora").glob("panel-*.tar.gz"))


def test_not_healthy_rolled_back_with_the_database(tmp_path: Path) -> None:
    settings, docker = data_dir(tmp_path), FakeSelf(health="unhealthy")
    real_run = docker.run

    async def migrating(image: str, cmd: list[str], binds: list[str], env: list[str]) -> Any:
        with sqlite3.connect(settings.data_dir / "hivora.db") as db:  # a migration
            db.execute("UPDATE t SET v = 'migrated'")
        return await real_run(image, cmd, binds, env)

    docker.run = migrating  # type: ignore[method-assign]
    state = asyncio.run(run_updater(settings, docker))
    assert state["status"] == "rolled_back" and "not healthy (unhealthy)" in state["error"]
    assert docker.calls[-3:] == ["remove hivora", "rename hivora-previous hivora", "start hivora"]
    assert docker.containers["hivora"] is OLD and "hivora" in docker.running
    with sqlite3.connect(settings.data_dir / "hivora.db") as db:
        assert db.execute("SELECT v FROM t").fetchone() == ("before",)


def panel(tmp_path: Path, docker: FakeSelf | None, **settings: Any) -> TestClient:
    s = Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                 catalog_dir=Path(__file__).parents[2] / "templates", dev_insecure_cookies=True,
                 puid=os.getuid(), pgid=os.getgid(), **settings)  # fmt: skip
    gateway = FakeDockerGateway()
    gateway.self_docker = lambda: docker  # type: ignore[method-assign,assignment,return-value]
    runtime = Runtime.build(s, gateway=gateway)
    tag = "v99.0.0"
    body = f"Notes.\n\nImage : `ghcr.io/hivora-suite/hivora-panel:{tag}`, digest `{DIGEST}`."

    async def github(url: str, headers: dict[str, str]) -> tuple[int, Any]:
        return 200, [{"tag_name": tag, "prerelease": False, "draft": False, "body": body,
                      "published_at": "2026-11-02T10:00:00Z", "html_url": "x"}]  # fmt: skip

    runtime.releases.fetch = github
    return TestClient(create_app(runtime=runtime))


def test_the_button_hands_over_to_the_updater_and_the_next_start_closes_the_job(
    tmp_path: Path,
) -> None:
    import hivora.system.self_update as su

    su.TAKEOVER = 0.2  # the updater never stops this test's Hivora
    docker = FakeSelf()
    with panel(tmp_path, docker) as c:
        admin(c)
        view = c.get(f"{API}/system/releases").json()
        assert view["newer"] and view["self_update"]
        assert code(c.post(f"{API}/system/update", json={"tag": "v1.0.0"})) == "self_update_refused"
        job = c.post(f"{API}/system/update", json={"tag": "v99.0.0"}).json()
        done = wait_job(c, job["id"])
        assert done["status"] == "failed" and "did not stop Hivora" in done["error"]
        assert docker.calls == ["pull ghcr.io/hivora-suite/hivora-panel:v99.0.0"]
        assert docker.launched == [("sha256:old", ["python", "-m", "hivora", "self-update"],
                                    str(tmp_path / "data"))]  # the CURRENT image  # fmt: skip
        state = read_state(tmp_path / "data")
        assert state and state["image"] == NEW and state["from"] == __version__

        # Pretend it ran: the job is "running" again, the updater reported success.
        runtime = c.app.state.runtime  # type: ignore[attr-defined]

        async def reopen() -> None:
            from sqlalchemy import update as sql_update

            from hivora.jobs.models import Job, JobStatus

            async with runtime.sessions() as s, s.begin():
                await s.execute(sql_update(Job).where(Job.id == job["id"]).values(
                    status=JobStatus.RUNNING, error=None, finished_at=None))  # fmt: skip

        c.portal.call(reopen)  # type: ignore[union-attr]
        write_state(tmp_path / "data", {**state, "status": "succeeded",
                                        "log": ["12:00:00 succeeded"]})  # fmt: skip
        c.portal.call(runtime.self_update.settle)  # type: ignore[union-attr]
        closed = c.get(f"{API}/jobs/{job['id']}").json()
        assert closed["status"] == "succeeded" and not (tmp_path / "data" / STATE).exists()


def test_refused_off_or_with_a_digest_not_the_releases(tmp_path: Path) -> None:
    with panel(tmp_path / "a", FakeSelf(), self_update=False) as c:
        admin(c)
        assert c.get(f"{API}/system/releases").json()["self_update"] is False
        refused = c.post(f"{API}/system/update", json={"tag": "v99.0.0"})
        assert code(refused) == "self_update_refused"
    docker = FakeSelf(digests=["ghcr.io/hivora-suite/hivora-panel@sha256:" + "b" * 64])
    with panel(tmp_path / "b", docker) as c:
        admin(c)
        done = wait_job(c, c.post(f"{API}/system/update", json={"tag": "v99.0.0"}).json()["id"])
        assert done["status"] == "failed" and "not the release's" in done["error"]
        assert docker.launched == [] and read_state(tmp_path / "b" / "data") is None
