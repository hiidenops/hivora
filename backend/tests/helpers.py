"""HTTP helpers shared by the API tests."""

import io
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

API = "/api/v1"
STRONG = "correct-horse-battery"
# A main site's page, as its owner would put it (a host starts with an empty html volume).
MAIN_PAGE = "<!doctype html>\n<title>Vitrine</title>\n<h1>Vitrine</h1>\n"


def login(c: TestClient, username: str, password: str, **extra: Any) -> dict[str, Any]:
    r = c.post(f"{API}/auth/login", json={"username": username, "password": password, **extra})
    assert r.status_code == 200, r.text
    me: dict[str, Any] = r.json()
    c.headers["X-CSRF-Token"] = me["csrf_token"]
    return me


def admin(c: TestClient) -> None:
    login(c, "admin", "admin")
    assert (
        c.post(f"{API}/auth/password", json={"current": "admin", "new": STRONG}).status_code == 204
    )


@contextmanager
def other_user(c: TestClient) -> Iterator[TestClient]:
    """Act as another browser on the same app: separate cookies and CSRF token."""
    cookies, csrf = dict(c.cookies), c.headers.pop("X-CSRF-Token", None)
    c.cookies.clear()
    try:
        yield c
    finally:
        c.cookies.clear()
        c.cookies.update(cookies)
        c.headers.pop("X-CSRF-Token", None)
        if csrf:
            c.headers["X-CSRF-Token"] = csrf


def code(r: Any) -> str:
    return str(r.json()["error"]["code"])


def wait_job(c: TestClient, job_id: int, within: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        job: dict[str, Any] = c.get(f"{API}/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def nginx_host(c: TestClient, name: str = "Vitrine", port: int = 8190, *,
               running: bool = False) -> int:  # fmt: skip
    """An nginx from the catalog that hosts sites (POST /apps, then .../sites/hosting): its
    app id. ``running``: its container reported running by the fake Docker (it reports
    none until told), as the routes that reload nginx need."""
    deployed = c.post(f"{API}/apps", json={"template": "nginx", "name": name,
                                           "inputs": {"web_port": port}})  # fmt: skip
    assert deployed.status_code == 202, deployed.text
    app: dict[str, Any] = deployed.json()["app"]
    assert wait_job(c, deployed.json()["job"]["id"])["status"] == "succeeded"
    hosted = c.post(f"{API}/apps/{app['id']}/sites/hosting")
    assert hosted.status_code == 200, hosted.text
    if running:
        from hivora.docker_gateway import ContainerInfo, ContainerState

        rt = cast(Any, c.app).state.runtime
        rt.gateway.put(ContainerInfo(
            id=f"ctr-{app['slug']}", name=f"{app['slug']}-server-1", image="nginx",
            state=ContainerState.RUNNING,
            labels={"io.hivora.app": app["slug"], "com.docker.compose.service": "server"},
        ), "start")  # fmt: skip
        deadline = time.monotonic() + 3
        while not rt.state.store.app(app["slug"]).containers:
            assert time.monotonic() < deadline
            time.sleep(0.02)
    app_id: int = app["id"]
    return app_id


# --- the sites' tests ---------------------------------------------------------------------


def deploy_nginx(c: TestClient, name: str, port: int) -> Any:
    """POST /apps for an nginx from the catalog (not waited for, not hosting sites)."""
    return c.post(f"{API}/apps", json={"template": "nginx", "name": name,
                                       "inputs": {"web_port": port}})  # fmt: skip


# The bind-mounted folders of an nginx app (template 1.1.0): the main site, the added
# sites, and the files Hivora writes for nginx. Nothing else is ever left next to them.
NGINX_VOLUMES = ["conf", "html", "sites"]


def spy_events(c: TestClient) -> tuple[list[tuple[str, dict[str, Any]]], Callable[[], None]]:
    """Record the events published; returns them and an undo."""
    bus = cast(Any, c.app).state.runtime.bus
    published: list[tuple[str, dict[str, Any]]] = []
    real_publish = bus.publish

    def publish(topic: str, **payload: Any) -> Any:
        published.append((topic, payload))
        return real_publish(topic, **payload)

    bus.publish = publish

    def undo() -> None:
        bus.publish = real_publish

    return published, undo


def zip_bytes(*members: Any) -> bytes:
    """A zip in memory. Members: (name, data) or (ZipInfo, data)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def volumes_of(c: TestClient, slug: str = "vitrine") -> Path:
    """An app's folder under the volumes root (its bind mounts, and Hivora's work files)."""
    path: Path = cast(Any, c.app).state.runtime.settings.volumes_root / slug
    return path


def paths_under(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def main_site_url(c: TestClient) -> str:
    """A host (nginx_host) whose main site has a page: the main site's base on the hosted
    routes (/apps/{app}/sites/{site})."""
    app_id = nginx_host(c)
    (volumes_of(c) / "html" / "index.html").write_text(MAIN_PAGE)
    main = c.get(f"{API}/apps/{app_id}/sites").json()["sites"][0]["id"]
    return f"{API}/apps/{app_id}/sites/{main}"


def site_id_of(url: str) -> int:
    """The site's id, last in its base."""
    return int(url.rsplit("/", 1)[1])


def host_before_deploy(c: TestClient, app_id: int) -> str:
    """An nginx whose deploy has not run yet starts hosting: its main site's base."""
    hosted = c.post(f"{API}/apps/{app_id}/sites/hosting")
    assert hosted.status_code == 200, hosted.text
    return f"{API}/apps/{app_id}/sites/{hosted.json()['sites'][0]['id']}"


def upload_zip(c: TestClient, url: str, body: bytes, filename: str = "site.zip") -> Any:
    """A site's content replaced from a zip (PUT {url}/content)."""
    return c.put(f"{url}/content", params={"filename": filename}, content=body,
                 headers={"content-type": "application/zip"})  # fmt: skip


def read_file(c: TestClient, url: str, path: str) -> Any:
    return c.get(f"{url}/files/content", params={"path": path})


def save_file(c: TestClient, url: str, path: str, content: str, base: str | None) -> Any:
    """``base``: the sha256 read (None: a new file)."""
    return c.put(f"{url}/files/content",
                 json={"path": path, "content": content, "base_sha256": base})  # fmt: skip
