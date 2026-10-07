"""The site_config job: Hivora's nginx files written, checked by nginx, then reloaded,
or put back as they were."""

import os
import stat
import time
from pathlib import Path
from typing import Any

import pytest
from helpers import API, admin, nginx_host, wait_job

from hivora.core.errors import HivoraError
from hivora.sites import nginx
from hivora.sites.config import CHECK, RELOAD

CHECK_KEY, RELOAD_KEY = " ".join(CHECK), " ".join(RELOAD)
BLOG = {"slug": "blog", "root": "blog", "port": 8096, "server_name": "blog.example.com"}
WIKI = {"slug": "wiki", "root": "wiki", "port": 8097, "server_name": None}


def _host(client: Any, running: bool = True) -> tuple[int, Path]:
    """A site host (nginx 1.1.0), with its nginx container running unless asked."""
    admin(client)
    app_id = nginx_host(client, running=running)
    return app_id, client.app.state.runtime.settings.volumes_root / "vitrine" / "conf"


def _add_site(client: Any, app_id: int, **fields: Any) -> None:
    from hivora.sites.models import Site

    rt = client.app.state.runtime

    async def add() -> None:
        async with rt.sessions() as session, session.begin():
            enabled = fields.pop("enabled", True)
            session.add(Site(app_id=app_id, name=fields["slug"], enabled=enabled,
                             created_at=rt.clock.now(), **fields))  # fmt: skip

    client.portal.call(add)


def _sql(client: Any, statement: str) -> None:
    from sqlalchemy import text

    rt = client.app.state.runtime

    async def run() -> None:
        async with rt.sessions() as session, session.begin():
            await session.execute(text(statement))

    client.portal.call(run)


def _apply(client: Any, app_id: int) -> dict[str, Any]:
    rt = client.app.state.runtime
    job = client.portal.call(rt.site_config.request, app_id)
    return wait_job(client, job.id)


def _files(conf: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(conf.iterdir())}


def _leftovers(conf: Path) -> list[str]:
    return sorted(p.name for p in conf.parent.iterdir() if p.name.startswith(".hivora-conf-"))


def _spy(client: Any) -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    bus = client.app.state.runtime.bus
    published: list[tuple[str, dict[str, Any]]] = []
    real = bus.publish

    def publish(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real(topic, **payload)

    bus.publish = publish
    return published, lambda: setattr(bus, "publish", real)


def _log(client: Any, job: dict[str, Any]) -> str:
    log: str = client.get(f"{API}/jobs/{job['id']}").json()["log"]
    return log


def test_writes_then_checks_then_reloads(client: Any) -> None:
    app_id, conf = _host(client)
    gw = client.app.state.runtime.gateway
    _add_site(client, app_id, **BLOG)
    published, undo = _spy(client)
    try:
        job = _apply(client, app_id)
    finally:
        undo()
    assert job["status"] == "succeeded", job["error"]
    blog = nginx.NginxSite(0, "blog", "blog", 8096, "blog.example.com", enabled=True)
    content = (conf / "site-blog.conf").read_text()
    assert content.split("\n", 1)[1] == nginx.render_site(blog).split("\n", 1)[1]  # past the id
    assert stat.S_IMODE((conf / "site-blog.conf").stat().st_mode) == 0o644
    assert gw.exec_calls[-2:] == [CHECK, RELOAD]  # checked, then reloaded
    assert ("site.config_applied", {"app": "vitrine", "files": ["site-blog.conf"],
                                    "removed": []}) in published  # fmt: skip
    assert _leftovers(conf) == []

    # Nothing changed: nothing written, nothing run.
    calls = len(gw.exec_calls)
    again = _apply(client, app_id)
    assert again["status"] == "succeeded" and len(gw.exec_calls) == calls
    assert "already up to date" in _log(client, again)

    time.sleep(0.8)  # the recorder writes in small batches
    actions = [a["action"] for a in client.get(f"{API}/audit", params={"limit": 1000}).json()]
    assert "site.config_applied" in actions


def test_main_site_off_then_on(client: Any) -> None:
    app_id, conf = _host(client)
    gw = client.app.state.runtime.gateway
    _sql(client, "UPDATE site SET enabled = 0 WHERE slug = 'main'")
    assert _apply(client, app_id)["status"] == "succeeded"
    assert _files(conf) == {"main-off.conf": b"return 503;\n"}
    assert gw.exec_calls[-2:] == [CHECK, RELOAD]
    _sql(client, "UPDATE site SET enabled = 1 WHERE slug = 'main'")
    assert _apply(client, app_id)["status"] == "succeeded"
    assert _files(conf) == {} and gw.exec_calls[-2:] == [CHECK, RELOAD]


def test_refused_by_nginx_puts_every_file_back(client: Any) -> None:
    app_id, conf = _host(client)
    gw = client.app.state.runtime.gateway
    _add_site(client, app_id, **BLOG)
    _apply(client, app_id)
    before = _files(conf)
    _add_site(client, app_id, **WIKI)
    _sql(client, "UPDATE site SET enabled = 0 WHERE slug = 'blog'")
    gw.exec_results[CHECK_KEY] = (1, "nginx: [emerg] bind() to 0.0.0.0:8097 failed")
    calls = len(gw.exec_calls)
    job = _apply(client, app_id)
    assert job["status"] == "failed" and "nginx refused the configuration" in job["error"]
    assert "[emerg] bind()" in job["error"]
    assert _files(conf) == before  # byte for byte: blog back, wiki gone
    assert gw.exec_calls[calls:] == [CHECK, CHECK]  # refused, then the previous files; no reload
    assert "files put back as they were" in _log(client, job)
    assert _leftovers(conf) == []

    # The intent stays in the database: once nginx accepts, the next job converges.
    del gw.exec_results[CHECK_KEY]
    assert _apply(client, app_id)["status"] == "succeeded"
    assert sorted(_files(conf)) == ["site-wiki.conf"]


def test_failed_reload_puts_every_file_back(client: Any) -> None:
    app_id, conf = _host(client)
    gw = client.app.state.runtime.gateway
    gw.exec_results[RELOAD_KEY] = (1, "nginx: [error] invalid PID number")
    _add_site(client, app_id, **BLOG)
    calls = len(gw.exec_calls)
    job = _apply(client, app_id)
    assert job["status"] == "failed" and "nginx could not reload" in job["error"]
    assert _files(conf) == {}
    assert gw.exec_calls[calls:] == [CHECK, RELOAD, CHECK, RELOAD]
    assert _leftovers(conf) == []


def test_a_failed_write_puts_every_file_back(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app_id, conf = _host(client)
    gw = client.app.state.runtime.gateway
    _add_site(client, app_id, **BLOG)
    _apply(client, app_id)
    before = _files(conf)
    _add_site(client, app_id, **WIKI)
    _sql(client, "UPDATE site SET server_name = 'news.example.com' WHERE slug = 'blog'")
    real_replace, calls = os.replace, [0]

    def replace(src: Any, dst: Any) -> None:
        calls[0] += 1
        if calls[0] == 2:  # the second file of this job
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    execs = len(gw.exec_calls)
    job = _apply(client, app_id)
    monkeypatch.undo()
    assert job["status"] == "failed" and "disk full" in job["error"]
    assert _files(conf) == before and gw.exec_calls[execs:] == []  # nothing run
    assert _leftovers(conf) == []


def test_a_stopped_nginx_gets_its_files_without_exec(client: Any) -> None:
    app_id, conf = _host(client, running=False)
    gw = client.app.state.runtime.gateway
    _add_site(client, app_id, **BLOG)
    calls = len(gw.exec_calls)
    job = _apply(client, app_id)
    assert job["status"] == "succeeded" and sorted(_files(conf)) == ["site-blog.conf"]
    assert gw.exec_calls[calls:] == []
    assert "nginx is not running" in _log(client, job)


def test_only_hivoras_files_are_touched(client: Any) -> None:
    app_id, conf = _host(client)
    (conf / "site-ghost.conf").write_text("server { listen 9999; }\n")  # not in the database
    (conf / "notes.txt").write_text("mine")
    (conf.parent / ".hivora-conf-dead").mkdir()  # left by an interrupted job
    (conf.parent / ".hivora-conf-dead" / "site-x.conf").write_text("x")
    _add_site(client, app_id, **BLOG)
    assert _apply(client, app_id)["status"] == "succeeded"
    assert sorted(_files(conf)) == ["notes.txt", "site-blog.conf"]
    assert (conf / "notes.txt").read_text() == "mine" and _leftovers(conf) == []


def test_a_row_outside_the_whitelist_writes_nothing(client: Any) -> None:
    app_id, conf = _host(client)
    gw = client.app.state.runtime.gateway
    _add_site(client, app_id, **BLOG)
    _sql(client, "UPDATE site SET server_name = 'a.com; include /etc/passwd' WHERE slug = 'blog'")
    calls = len(gw.exec_calls)
    job = _apply(client, app_id)
    assert job["status"] == "failed" and "invalid server name" in job["error"]
    assert _files(conf) == {} and gw.exec_calls[calls:] == []


def test_the_conf_folder_never_leads_outside(client: Any, tmp_path: Path) -> None:
    app_id, conf = _host(client)
    outside = tmp_path / "outside"
    outside.mkdir()
    conf.rmdir()
    conf.symlink_to(outside)
    _add_site(client, app_id, **BLOG)
    job = _apply(client, app_id)
    assert job["status"] == "failed" and "outside of its root" in job["error"]
    assert list(outside.iterdir()) == []


def test_no_database_lock_while_nginx_runs(client: Any) -> None:
    from sqlalchemy import text

    app_id, _ = _host(client)
    rt = client.app.state.runtime
    gw = rt.gateway
    real_exec, writes = gw.exec_run, []

    async def exec_while_writing(cid: str, cmd: list[str], user: str | None = None) -> Any:
        async with rt.sessions() as s, s.begin():
            await s.execute(text("UPDATE site SET name = name"))
        writes.append(cmd)
        return await real_exec(cid, cmd, user)

    gw.exec_run = exec_while_writing
    try:
        _add_site(client, app_id, **BLOG)
        job = _apply(client, app_id)
    finally:
        gw.exec_run = real_exec
    assert job["status"] == "succeeded" and writes == [CHECK, RELOAD]


def test_request_needs_a_site_host_on_nginx_1_1_0(client: Any) -> None:
    from hivora.apps.models import Service, VolumeMount

    app_id, _ = _host(client)
    rt = client.app.state.runtime
    with pytest.raises(HivoraError) as err:
        client.portal.call(rt.site_config.request, 9999)
    assert err.value.code == "site_not_found"

    async def drop_conf_volume() -> None:  # as an nginx deployed from template 1.0.0
        from sqlalchemy import delete, select

        async with rt.sessions() as session, session.begin():
            ids = select(Service.id).where(Service.app_id == app_id)
            conf_volume = VolumeMount.target == "/etc/nginx/hivora.d"
            await session.execute(
                delete(VolumeMount).where(VolumeMount.service_id.in_(ids), conf_volume)
            )

    client.portal.call(drop_conf_volume)
    with pytest.raises(HivoraError) as err:
        client.portal.call(rt.site_config.request, app_id)
    assert err.value.code == "host_upgrade_required"
    assert client.get(f"{API}/jobs").json()[0]["kind"] != "site_config"  # nothing queued
