"""HTTP helpers shared by the API tests."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
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
