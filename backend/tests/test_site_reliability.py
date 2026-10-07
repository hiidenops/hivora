"""A host's nginx configuration as it really is (its last job, applied again on request or
after a start), files removed when asked even if nginx refuses, and free ports suggested."""

import time
from pathlib import Path
from typing import Any

from helpers import API, admin, code, nginx_host, wait_job

CHECK_KEY = "nginx -t"


def _sites(client: Any, app_id: int) -> dict[str, Any]:
    host: dict[str, Any] = client.get(f"{API}/apps/{app_id}/sites").json()
    return host


def _add(client: Any, app_id: int, name: str, port: int) -> dict[str, Any]:
    added = client.post(f"{API}/apps/{app_id}/sites", json={"name": name, "port": port})
    assert added.status_code == 202, added.text
    change: dict[str, Any] = added.json()
    assert wait_job(client, change["config_job"]["id"])["status"] == "succeeded"
    return change


def _conf(client: Any, slug: str = "vitrine") -> Path:
    path: Path = client.app.state.runtime.settings.volumes_root / slug / "conf"
    return path


def test_the_last_configuration_shown_and_applied_again(client: Any) -> None:
    admin(client)
    gw = client.app.state.runtime.gateway
    app_id = nginx_host(client, running=True)
    assert _sites(client, app_id)["config"] is None  # nothing applied yet
    [listed] = [a for a in client.get(f"{API}/apps").json() if a["id"] == app_id]
    assert listed["hosting"] is True

    change = _add(client, app_id, "Blog", 8096)
    assert _sites(client, app_id)["config"] == {
        "job_id": change["config_job"]["id"], "status": "succeeded", "error": None,
    }  # fmt: skip

    # Its file lost, and nginx refusing: the failure is shown with nginx's words.
    (_conf(client) / "site-blog.conf").unlink()
    gw.exec_results[CHECK_KEY] = (1, "nginx: [emerg] boom")
    sent = client.post(f"{API}/apps/{app_id}/sites/config")
    assert sent.status_code == 202 and sent.json()["kind"] == "site_config"
    assert wait_job(client, sent.json()["id"])["status"] == "failed"
    config = _sites(client, app_id)["config"]
    assert (config["job_id"], config["status"]) == (sent.json()["id"], "failed")
    assert "nginx refused the configuration" in config["error"] and "boom" in config["error"]

    # Applied again once nginx accepts: the file is back.
    del gw.exec_results[CHECK_KEY]
    again = client.post(f"{API}/apps/{app_id}/sites/config").json()
    assert wait_job(client, again["id"])["status"] == "succeeded"
    assert (_conf(client) / "site-blog.conf").is_file()
    assert _sites(client, app_id)["config"]["status"] == "succeeded"

    nginx_host(client, "Autre", 8191)  # hosts sites; a catalog nginx that does not:
    plain = client.post(f"{API}/apps", json={"template": "nginx", "name": "Simple",
                                             "inputs": {"web_port": 8192}}).json()  # fmt: skip
    wait_job(client, plain["job"]["id"])
    flags = {a["slug"]: a["hosting"] for a in client.get(f"{API}/apps").json()}
    assert flags == {"vitrine": True, "autre": True, "simple": False}
    for unknown in (plain["app"]["id"], 9999):
        r = client.post(f"{API}/apps/{unknown}/sites/config")
        assert (r.status_code, code(r)) == (404, "site_not_found")


def test_a_started_host_gets_its_configuration_again(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    rt.site_config.start_wait = 0.5
    app_id = nginx_host(client, running=True)
    _add(client, app_id, "Blog", 8096)
    last = _sites(client, app_id)["config"]["job_id"]
    (_conf(client) / "site-blog.conf").unlink()  # its "conf" volume lost meanwhile

    restart = client.post(f"{API}/apps/{app_id}/restart")
    assert wait_job(client, restart.json()["id"])["status"] == "succeeded"
    deadline = time.monotonic() + 10
    while (config := _sites(client, app_id)["config"])["job_id"] == last or config["status"] in (
        "queued", "running",
    ):  # fmt: skip
        assert time.monotonic() < deadline, config
        time.sleep(0.05)
    assert config["status"] == "succeeded"
    assert (_conf(client) / "site-blog.conf").is_file()

    # A start of an app that hosts no sites queues nothing.
    plain = client.post(f"{API}/apps", json={"template": "nginx", "name": "Simple",
                                             "inputs": {"web_port": 8192}}).json()  # fmt: skip
    wait_job(client, plain["job"]["id"])
    wait_job(client, client.post(f"{API}/apps/{plain['app']['id']}/restart").json()["id"])
    time.sleep(0.3)
    jobs = client.get(f"{API}/jobs").json()
    kinds = [j["kind"] for j in jobs if j["app_id"] == plain["app"]["id"]]
    assert "site_config" not in kinds


def test_files_removed_when_asked_even_if_nginx_refuses(client: Any) -> None:
    admin(client)
    gw = client.app.state.runtime.gateway
    app_id = nginx_host(client, running=True)
    blog = _add(client, app_id, "Blog", 8096)["site"]["id"]
    folder = client.app.state.runtime.settings.volumes_root / "vitrine" / "sites" / "blog"
    folder.mkdir(parents=True)
    (folder / "index.html").write_text("blog")

    gw.exec_results[CHECK_KEY] = (1, "nginx: [emerg] boom")
    gone = client.delete(f"{API}/apps/{app_id}/sites/{blog}", params={"remove_data": "true"})
    assert gone.status_code == 202, gone.text
    config = wait_job(client, gone.json()["config_job"]["id"])
    assert config["status"] == "failed"
    wait_job(client, gone.json()["job"]["id"])
    assert not folder.exists()
    assert "removed the files of blog" in client.get(f"{API}/jobs/{config['id']}").json()["log"]


def test_suggested_ports_are_really_free(client: Any) -> None:
    admin(client)
    app_id = nginx_host(client, running=True)  # its web port: 8190
    other = client.post(f"{API}/apps", json={"template": "nginx", "name": "Autre",
                                             "inputs": {"web_port": 8200}}).json()  # fmt: skip
    wait_job(client, other["job"]["id"])
    blog = _add(client, app_id, "Blog", 8096)["site"]["id"]
    wiki = _add(client, app_id, "Wiki", 8201)["site"]["id"]
    base = f"{API}/apps/{app_id}/sites"

    def conflict(r: Any) -> tuple[str, int | None]:
        assert (r.status_code, code(r)) == (409, "port_conflict"), r.text
        [c] = r.json()["error"]["details"]["conflicts"]
        return c["used_by"], c["suggestion"]

    # Another site of this nginx: a free port, never one of its sites' (8201 is Wiki's).
    assert conflict(client.post(f"{base}/{blog}/port/plan", json={"port": 8201})) == (
        "site wiki", 8202,
    )  # fmt: skip
    # Another app: not the moved site's own port (8201, freed by the move), nor its others'.
    assert conflict(client.post(f"{base}/{wiki}/port/plan", json={"port": 8200})) == (
        "autre", 8202,
    )  # fmt: skip
    assert conflict(client.put(f"{base}/{wiki}/port", json={"port": 8200})) == ("autre", 8202)
    added = client.post(f"{base}/plan", json={"name": "Docs", "port": 8200})
    assert conflict(added) == ("autre", 8202)
    # This nginx's own web port: the next free one, past it.
    assert conflict(client.post(f"{base}/plan", json={"name": "Docs", "port": 8190}))[1] == 8191


def test_a_restored_host_gets_its_configuration_again(client: Any) -> None:
    """Its "conf" volume is not in its backups: applied again after a restore."""
    admin(client)
    client.app.state.runtime.site_config.start_wait = 0.5
    app_id = nginx_host(client, running=True)
    _add(client, app_id, "Blog", 8096)
    backup = client.post(f"{API}/apps/{app_id}/backups").json()
    assert wait_job(client, backup["id"])["status"] == "succeeded"
    [saved] = client.get(f"{API}/apps/{app_id}/backups").json()["backups"]
    last = _sites(client, app_id)["config"]["job_id"]
    (_conf(client) / "site-blog.conf").unlink()  # as on a new machine

    restore = client.post(f"{API}/apps/{app_id}/backups/{saved['id']}/restore").json()
    assert wait_job(client, restore["id"])["status"] == "succeeded"
    deadline = time.monotonic() + 10
    while (config := _sites(client, app_id)["config"])["job_id"] == last or config["status"] in (
        "queued", "running",
    ):  # fmt: skip
        assert time.monotonic() < deadline, config
        time.sleep(0.05)
    assert config["status"] == "succeeded"
    assert (_conf(client) / "site-blog.conf").is_file()
