"""HTTP helpers shared by the API tests."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"
STRONG = "correct-horse-battery"


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
