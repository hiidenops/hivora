"""The System page's health (M12-6): pure checks, the admin-only route, the source link."""

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import API, admin, code, login, other_user

import hivora.system.status as status_module
from hivora.core.config import Settings
from hivora.docker_gateway import ContainerInfo, ContainerState, PublishedPort
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.jobs import Job, JobKind, JobStatus
from hivora.jobs.queries import job_health
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.system.status import (
    Check,
    check_admin_vpn,
    check_database,
    check_exposure,
    check_jobs,
    check_panel_backup,
    check_tls,
    disk_level,
    worst,
)

GB = 1024**3
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_disk_thresholds() -> None:
    assert disk_level(1000 * GB, 150 * GB) == "ok"
    assert disk_level(1000 * GB, 50 * GB) == "ok"  # 5 %, but 50 GB free: a big disk is calm
    assert disk_level(100 * GB, 8 * GB) == "warn"  # under 10 % and under 20 GB
    assert disk_level(100 * GB, 2 * GB) == "error"  # under 3 %
    assert disk_level(4000 * GB, GB // 4) == "error"  # under 500 MB, whatever the size
    assert disk_level(0, 0) == "unknown"


def test_database_tls_jobs_backup_vpn_checks() -> None:
    assert check_database("current", 10, 10, None).level == "ok"
    assert check_database("current", 10, 300 * 1024**2, None).level == "warn"  # a big WAL
    assert check_database("behind", 10, 10, None).level == "error"
    assert check_database("current", 10, 10, "*** in database main ***").level == "error"
    assert check_database("current", 10, 10, "ok").values["quick_check"] == "ok"
    assert check_tls(False, None, NOW).level == "ok"
    assert check_tls(True, None, NOW).level == "unknown"
    assert check_tls(True, NOW - timedelta(days=1), NOW).level == "error"
    assert check_tls(True, NOW + timedelta(days=10), NOW).level == "warn"
    assert check_tls(True, NOW + timedelta(days=365), NOW).values["days"] == 365
    assert check_jobs({"running": 1, "queued": 2, "failed": 0, "stuck": 0}).level == "ok"
    assert check_jobs({"running": 0, "queued": 0, "failed": 1, "stuck": 0}).level == "warn"
    assert check_jobs({"running": 1, "queued": 0, "failed": 0, "stuck": 1}).level == "warn"
    assert check_panel_backup(None).level == "warn" and check_panel_backup(NOW).level == "ok"
    assert check_admin_vpn({"initialized": True, "conf": True, "running": True}).level == "ok"
    assert check_admin_vpn({"initialized": True, "conf": True, "running": False}).level == "warn"
    assert worst([Check("a", "ok"), Check("b", "unknown")]) == "unknown"
    assert worst([Check("a", "warn"), Check("b", "error"), Check("c", "ok")]) == "error"
    assert worst([]) == "ok"


def test_exposure() -> None:
    assert check_exposure("lan", ["192.168.1.10"]).level == "ok"
    assert check_exposure("lan", ["0.0.0.0"]).level == "error"  # Internet, no mandatory TOTP
    assert check_exposure("vpn+lan", ["::"]).level == "error"
    assert check_exposure("vpn", []).level == "ok"  # nothing published: the VPN only
    assert check_exposure("public", ["0.0.0.0"]).level == "warn"  # wanted: a reminder
    assert check_exposure("lan", None).level == "unknown"  # not in a container (sources)


def test_job_counts(sessions: Any) -> None:
    async def scenario() -> dict[str, int]:
        async with sessions() as session, session.begin():
            old, recent = NOW - timedelta(days=2), NOW - timedelta(hours=2)
            for status, started, finished in (
                (JobStatus.FAILED, recent, recent),  # counted
                (JobStatus.FAILED, old, old),  # too old
                (JobStatus.RUNNING, recent, None),  # running for 2 hours: stuck
                (JobStatus.RUNNING, NOW, None),
                (JobStatus.QUEUED, None, None),
            ):
                session.add(Job(kind=JobKind.DEPLOY, status=status, created_at=old, params={},
                                started_at=started, finished_at=finished))  # fmt: skip
        async with sessions() as session:
            return await job_health(session, NOW - timedelta(hours=24), NOW - timedelta(hours=1))

    assert asyncio.run(scenario()) == {"running": 2, "queued": 1, "failed": 1, "stuck": 1}


@contextmanager
def panel(tmp_path: Path, **settings: Any) -> Iterator[TestClient]:
    s = Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                 catalog_dir=Path(__file__).parents[2] / "templates", dev_insecure_cookies=True,
                 puid=os.getuid(), pgid=os.getgid(), **settings)  # fmt: skip
    with TestClient(create_app(runtime=Runtime.build(s, gateway=FakeDockerGateway()))) as c:
        yield c


def published(c: TestClient, host_ip: str, cid: str = "self") -> None:
    """The panel's own container, as the installer starts it."""
    c.app.state.runtime.gateway.put(ContainerInfo(  # type: ignore[attr-defined]
        id=cid, name=f"hivora-{cid}", image="hivora", state=ContainerState.RUNNING,
        labels={"io.hivora.self": "true"},
        ports=(PublishedPort(8443, "tcp", host_ip, 8443),)))  # fmt: skip


def test_the_status_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    real = status_module.quick_check

    def counted(path: Path) -> str:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(status_module, "quick_check", counted)
    with panel(tmp_path) as c:
        admin(c)
        r = c.get(f"{API}/system/status")
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [x["id"] for x in body["checks"]]
        assert ids == ["version", "database", "disk", "docker", "jobs", "panel_backup",
                       "exposure", "tls"]  # fmt: skip
        by = {x["id"]: x for x in body["checks"]}
        assert body["access"] == "lan" and by["exposure"]["level"] == "unknown"
        assert by["database"]["values"]["schema"] == "current" and calls == []
        assert by["database"]["values"]["quick_check"] is None  # only when asked
        assert by["docker"]["level"] == "ok" and by["tls"]["values"]["enabled"] is True
        deep = c.get(f"{API}/system/status", params={"deep": "true"}).json()
        assert calls and next(x for x in deep["checks"] if x["id"] == "database")[
            "values"]["quick_check"] == "ok"  # fmt: skip
        published(c, "0.0.0.0")  # published everywhere, outside the public mode
        r = c.get(f"{API}/system/status").json()
        assert r["worst"] == "error"
        assert next(x for x in r["checks"] if x["id"] == "exposure")["values"]["published"] == [
            "0.0.0.0"]  # fmt: skip
        for role in ("viewer", "operator"):
            c.post(f"{API}/users", json={"username": role, "password": f"{role}-pass-1",
                                         "role": role})  # fmt: skip
            with other_user(c) as other:
                login(other, role, f"{role}-pass-1")
                other.post(f"{API}/auth/password",
                           json={"current": f"{role}-pass-1", "new": f"{role}-pass-2"})  # fmt: skip
                r = other.get(f"{API}/system/status")
                assert r.status_code == 403 and code(r) == "insufficient_role", role


def test_a_public_panel_is_a_reminder(tmp_path: Path) -> None:
    import pyotp

    with panel(tmp_path, access="public") as c:
        admin(c)
        secret = c.post(f"{API}/auth/totp/enroll").json()["secret"]  # mandatory in public mode
        c.post(f"{API}/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})
        published(c, "0.0.0.0")
        r = c.get(f"{API}/system/status").json()
        exposure = next(x for x in r["checks"] if x["id"] == "exposure")
        assert r["access"] == "public" and exposure["level"] == "warn"


def test_the_source_link(tmp_path: Path) -> None:
    with panel(tmp_path / "a") as c:
        assert c.get(f"{API}/system/health").json()["source_url"] == (
            "https://github.com/hiidenops/hivora"
        )
    with panel(tmp_path / "b", source_url="https://git.example.org/fork/hivora") as c:
        assert c.get(f"{API}/system/health").json()["source_url"] == (
            "https://git.example.org/fork/hivora"
        )
    with pytest.raises(ValueError):
        Settings(source_url="javascript:alert(1)")


def test_two_panels_on_one_docker_each_read_their_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with panel(tmp_path) as c:
        admin(c)
        published(c, "192.168.1.10", cid="aaaa1111bbbb")  # this one, on the LAN
        published(c, "0.0.0.0", cid="cccc2222dddd")  # another Hivora, published everywhere
        monkeypatch.setattr("socket.gethostname", lambda: "aaaa1111bbbb")
        exposure = next(x for x in c.get(f"{API}/system/status").json()["checks"]
                        if x["id"] == "exposure")  # fmt: skip
        assert exposure["level"] == "ok" and exposure["values"]["published"] == ["192.168.1.10"]
