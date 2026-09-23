"""M4 exit criterion: the whole journey over HTTP, on a real Docker Engine."""

import socket
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import API, admin, wait_job

from hivora.core.config import Settings
from hivora.docker_gateway import DockerUnavailableError
from hivora.docker_gateway.local import LocalDockerGateway
from hivora.main import create_app

pytestmark = pytest.mark.docker


def docker_available() -> bool:
    import asyncio

    async def ping() -> bool:
        gw = LocalDockerGateway()
        try:
            await gw.ping()
            return True
        except DockerUnavailableError:
            return False
        finally:
            await gw.close()

    return asyncio.run(ping())


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    if not docker_available():
        pytest.skip("Docker is not reachable")
    settings = Settings(
        data_dir=tmp_path / "data",
        volumes_root=tmp_path / "srv",
        catalog_dir=Path(__file__).parents[2] / "templates",
        dev_insecure_cookies=True,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def app_status(c: TestClient, app_id: int, expected: str, within: float = 5) -> None:
    deadline = time.monotonic() + within
    while (status := c.get(f"{API}/apps/{app_id}").json()["status"]) != expected:
        assert time.monotonic() < deadline, f"status stayed {status}"
        time.sleep(0.1)


def test_full_journey_over_http(client: TestClient) -> None:
    admin(client)  # admin/admin, forced password change
    port = free_port()
    body = {
        "template": "vaultwarden",
        "name": "Coffre HTTP",
        "inputs": {"web_port": port, "domain": f"http://localhost:{port}"},
    }
    assert client.post(f"{API}/apps/plan", json=body).json()["conflicts"] == []

    deployed = client.post(f"{API}/apps", json=body).json()
    app_id = deployed["app"]["id"]
    try:
        assert wait_job(client, deployed["job"]["id"], within=300)["status"] == "succeeded"
        app_status(client, app_id, "healthy")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/alive", timeout=5) as r:
            assert r.status == 200

        stop = client.post(f"{API}/apps/{app_id}/stop").json()
        assert wait_job(client, stop["id"], within=60)["status"] == "succeeded"
        app_status(client, app_id, "stopped")
        assert client.get(f"{API}/apps/{app_id}").json()["drift"] is False
    finally:
        rm = client.delete(f"{API}/apps/{app_id}", params={"remove_data": "true"}).json()
        assert wait_job(client, rm["id"], within=60)["status"] == "succeeded"
    assert client.get(f"{API}/apps").json() == []
