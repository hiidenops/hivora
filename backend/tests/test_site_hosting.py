"""SiteHosting: the sites an nginx hosts, each on its own port. A port change makes a
revision (the container is recreated) then the site_config job; turning a site on or
off, or naming it, only rewrites nginx's files."""

import functools
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import API, admin, nginx_host, wait_job

from hivora.core.errors import HivoraError
from hivora.sites.config import CHECK, RELOAD


def _host(client: Any) -> tuple[int, Path]:
    """A site host (nginx 1.1.0), its nginx container running."""
    admin(client)
    app_id = nginx_host(client, running=True)
    return app_id, client.app.state.runtime.settings.volumes_root / "vitrine"


def _call(client: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    rt = client.app.state.runtime
    return client.portal.call(functools.partial(getattr(rt.site_hosting, method), *args, **kwargs))


def _refused(client: Any, error: str, method: str, *args: Any, **kwargs: Any) -> Any:
    """The error's details (a refused change raises before anything is written)."""
    with pytest.raises(HivoraError) as err:
        _call(client, method, *args, **kwargs)
    assert err.value.code == error, err.value
    return err.value.details


def _state(client: Any) -> tuple[Any, ...]:
    """Everything a refused change must leave as it was: sites, revisions, jobs."""
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:
        return (
            conn.execute("SELECT * FROM site ORDER BY id").fetchall(),
            conn.execute("SELECT * FROM app_revision ORDER BY id").fetchall(),
            conn.execute("SELECT * FROM job ORDER BY id").fetchall(),
        )


def _published(client: Any, app_id: int) -> list[int]:
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    return [int(p["published"]) for p in compose["services"]["server"]["ports"]]


def _site_id(client: Any, slug: str) -> int:
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:
        site_id: int = conn.execute("SELECT id FROM site WHERE slug = ?", (slug,)).fetchone()[0]
    return site_id


def _revisions(client: Any, app_id: int) -> int:
    return len(client.get(f"{API}/apps/{app_id}/revisions").json())


def test_plan_shows_the_recreation_and_writes_nothing(client: Any) -> None:
    app_id, _ = _host(client)
    before = _state(client)
    plan = _call(client, "plan_add", app_id, "Blog", 8096)
    assert (plan.recreate, plan.revision) == (True, 2)
    assert (plan.ports_before, plan.ports_after) == ([], [8096])
    assert "published: '8096'" in plan.diff
    assert _state(client) == before  # nothing written


def test_add_publishes_the_port_then_configures_nginx(client: Any) -> None:
    app_id, app_dir = _host(client)
    gw = client.app.state.runtime.gateway
    calls = len(gw.exec_calls)
    site_id, update, config = _call(client, "add", app_id, "Blog", 8096,
                                    server_name="blog.example.com")  # fmt: skip
    assert (update.kind, config.kind) == ("update", "site_config") and update.id < config.id
    assert wait_job(client, update.id)["status"] == "succeeded"
    assert wait_job(client, config.id)["status"] == "succeeded"
    assert _revisions(client, app_id) == 2 and _published(client, app_id) == [8190, 8096]
    conf = (app_dir / "conf" / "site-blog.conf").read_text()
    assert "listen 8096;" in conf and "server_name blog.example.com;" in conf
    assert f"(id {site_id})" in conf
    assert gw.exec_calls[calls:] == [CHECK, RELOAD]
    time.sleep(0.8)  # the recorder writes in small batches
    added = [a for a in client.get(f"{API}/audit", params={"limit": 1000}).json()
             if a["action"] == "site.added"]  # fmt: skip
    assert [(a["target"], a["payload"]["site"], a["payload"]["port"]) for a in added] == [
        ("vitrine", "blog", 8096)
    ]


def test_conflicts_are_refused_before_anything_is_written(client: Any) -> None:
    app_id, _ = _host(client)
    other = client.post(f"{API}/apps", json={"template": "nginx", "name": "Autre",
                                             "inputs": {"web_port": 8097}}).json()  # fmt: skip
    wait_job(client, other["job"]["id"])
    _, _, config = _call(client, "add", app_id, "Blog", 8096)
    wait_job(client, config.id)
    before = _state(client)

    _refused(client, "invalid_site_config", "add", app_id, "Port 80", 80)
    _refused(client, "invalid_site_config", "add", app_id, "Main", 8100, slug="main")
    _refused(client, "invalid_site_config", "add", app_id, "Bad", 8100, server_name="a;b")
    details = _refused(client, "port_conflict", "add", app_id, "Same", 8190)  # the app's web port
    assert details["conflicts"][0]["used_by"] == "server (this app)"
    details = _refused(client, "port_conflict", "add", app_id, "Wiki", 8096)  # another site's
    assert details["conflicts"][0]["used_by"] == "site blog"
    details = _refused(client, "port_conflict", "add", app_id, "Wiki", 8097)  # another app's
    [conflict] = details["conflicts"]
    assert conflict["used_by"] == "autre" and conflict["suggestion"] not in (None, 8097)
    _refused(client, "port_conflict", "plan_add", app_id, "Wiki", 8097)  # the preview too
    _refused(client, "site_exists", "add", app_id, "Blog", 8100)
    assert _state(client) == before  # none of them wrote anything

    # One of the user's own extra ports (advanced settings).
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE app_revision SET overrides = ? WHERE app_id = ? AND number = 2",
                     ('{"services": {"server": {"ports": [{"container": 9000, "host": 9000}]}}}',
                      app_id))  # fmt: skip
    before = _state(client)
    details = _refused(client, "port_conflict", "add", app_id, "Wiki", 9000)
    assert details["conflicts"][0]["used_by"] == "advanced settings"
    assert _state(client) == before


def test_thirty_sites_at_most(client: Any) -> None:
    app_id, _ = _host(client)
    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:
        rows = [(app_id, f"s{i}", f"s{i}", f"s{i}", 9100 + i) for i in range(30)]
        conn.executemany("INSERT INTO site (app_id, slug, name, root, port, enabled, created_at)"
                         " VALUES (?, ?, ?, ?, ?, 1, '2026-10-05 12:00:00.000000')",
                         rows)  # fmt: skip
    before = _state(client)
    details = _refused(client, "too_many_sites", "add", app_id, "Encore", 9200)
    assert details == {"limit": 30} and _state(client) == before


def test_on_off_and_names_only_rewrite_nginx_files(client: Any) -> None:
    app_id, app_dir = _host(client)
    _, _, config = _call(client, "add", app_id, "Blog", 8096)
    wait_job(client, config.id)
    blog, main = _site_id(client, "blog"), _site_id(client, "main")
    revisions = _revisions(client, app_id)

    job = _call(client, "set_enabled", app_id, blog, False)
    assert job.kind == "site_config" and wait_job(client, job.id)["status"] == "succeeded"
    assert not (app_dir / "conf" / "site-blog.conf").exists()
    assert _published(client, app_id) == [8190, 8096]  # the port stays published
    wait_job(client, _call(client, "set_enabled", app_id, blog, True).id)
    assert (app_dir / "conf" / "site-blog.conf").exists()

    wait_job(client, _call(client, "set_enabled", app_id, main, False).id)
    assert (app_dir / "conf" / "main-off.conf").read_text() == "return 503;\n"

    wait_job(client, _call(client, "set_server_name", app_id, blog, "blog.example.com").id)
    assert "server_name blog.example.com;" in (app_dir / "conf" / "site-blog.conf").read_text()
    _refused(client, "invalid_site_config", "set_server_name", app_id, blog, "a b")
    _refused(client, "main_site_fixed", "set_server_name", app_id, main, "a.com")
    assert _revisions(client, app_id) == revisions  # no revision, nothing recreated


def test_change_port_moves_the_published_port(client: Any) -> None:
    app_id, app_dir = _host(client)
    _, _, config = _call(client, "add", app_id, "Blog", 8096)
    wait_job(client, config.id)
    blog, main = _site_id(client, "blog"), _site_id(client, "main")

    same = _call(client, "plan_port", app_id, blog, 8096)
    assert (same.recreate, same.revision) == (False, None)
    plan = _call(client, "plan_port", app_id, blog, 8099)
    assert plan.recreate and (plan.ports_before, plan.ports_after) == ([8096], [8099])
    update, config = _call(client, "change_port", app_id, blog, 8099)
    assert update.id < config.id and wait_job(client, config.id)["status"] == "succeeded"
    assert _published(client, app_id) == [8190, 8099]
    assert "listen 8099;" in (app_dir / "conf" / "site-blog.conf").read_text()

    # The main site's port is the app's web port: moved the same way, by a new revision.
    same = _call(client, "plan_port", app_id, main, 8190)
    assert (same.recreate, same.revision) == (False, None)
    _refused(client, "port_conflict", "change_port", app_id, main, 8099)  # the blog's
    plan = _call(client, "plan_port", app_id, main, 8100)
    assert plan.recreate and plan.revision is not None and "8100" in plan.diff
    update, config = _call(client, "change_port", app_id, main, 8100)
    assert update.id < config.id and wait_job(client, config.id)["status"] == "succeeded"
    assert _published(client, app_id) == [8100, 8099]
    assert client.get(f"{API}/apps/{app_id}/settings").json()["values"]["web_port"] == 8100


def test_remove_unconfigures_first_and_keeps_files_unless_asked(client: Any) -> None:
    app_id, app_dir = _host(client)
    for name, port in (("Blog", 8096), ("Wiki", 8097)):
        wait_job(client, _call(client, "add", app_id, name, port)[2].id)
    (app_dir / "sites" / "blog").mkdir(exist_ok=True)
    (app_dir / "sites" / "blog" / "index.html").write_text("blog")
    (app_dir / "sites" / "wiki").mkdir(exist_ok=True)
    (app_dir / "sites" / "wiki" / "index.html").write_text("wiki")

    plan = _call(client, "plan_remove", app_id, _site_id(client, "blog"))
    assert plan.recreate and plan.ports_after == [8097]
    config, update = _call(client, "remove", app_id, _site_id(client, "blog"))
    assert config.id < update.id  # nginx stops serving it, then the port goes
    assert wait_job(client, update.id)["status"] == "succeeded"
    assert not (app_dir / "conf" / "site-blog.conf").exists()
    assert _published(client, app_id) == [8190, 8097]
    assert (app_dir / "sites" / "blog" / "index.html").read_text() == "blog"  # kept

    config, update = _call(client, "remove", app_id, _site_id(client, "wiki"), remove_data=True)
    assert wait_job(client, update.id)["status"] == "succeeded"
    assert not (app_dir / "sites" / "wiki").exists()
    assert "removed the files of wiki" in client.get(f"{API}/jobs/{config.id}").json()["log"]

    _refused(client, "main_site_fixed", "remove", app_id, _site_id(client, "main"))
    _refused(client, "site_not_found", "remove", app_id, 9999)


def test_a_stopped_or_old_host_refuses_port_changes(client: Any) -> None:
    app_id, app_dir = _host(client)
    stop = client.post(f"{API}/apps/{app_id}/stop").json()
    wait_job(client, stop["id"])
    before = _state(client)
    _refused(client, "site_host_stopped", "add", app_id, "Blog", 8096)
    _refused(client, "site_host_stopped", "plan_add", app_id, "Blog", 8096)
    assert _state(client) == before
    # Files only (no revision): still allowed on a stopped host.
    job = _call(client, "set_enabled", app_id, _site_id(client, "main"), False)
    assert wait_job(client, job.id)["status"] == "succeeded"
    assert (app_dir / "conf" / "main-off.conf").exists()

    db = client.app.state.runtime.settings.db_path
    with sqlite3.connect(db) as conn:  # as an nginx deployed from template 1.0.0
        conn.execute("DELETE FROM volume_mount WHERE target = '/etc/nginx/hivora.d'")
    _refused(client, "host_upgrade_required", "set_enabled", app_id, _site_id(client, "main"), True)


def test_a_failed_redeploy_keeps_the_intent(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from hivora.compose_runner import ComposeError

    app_id, _ = _host(client)
    rt = client.app.state.runtime

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise ComposeError("docker compose up failed")

    monkeypatch.setattr(rt.runner, "up", broken)
    _, update, config = _call(client, "add", app_id, "Blog", 8096)
    assert wait_job(client, update.id)["status"] == "failed"
    assert wait_job(client, config.id)["status"] == "succeeded"  # the lane goes on
    assert _site_id(client, "blog")  # the intent stays
    monkeypatch.undo()
    values = client.get(f"{API}/apps/{app_id}/settings").json()["values"]
    job = client.put(f"{API}/apps/{app_id}/settings", json={"inputs": values}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"  # the next revision converges
    assert _published(client, app_id) == [8190, 8096]
