"""ASGI factory for the frontend end-to-end tests: real API and UI, fake Docker.

uvicorn --factory e2e_app:app --app-dir tests   (settings from HIVORA_* env)
"""

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from hivora.core.config import Settings
from hivora.core.events import Event
from hivora.docker_gateway import ContainerInfo, ContainerState, StatsSample
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.hostfw.service import HOST
from hivora.main import create_app
from hivora.runtime import Runtime

FAKE_COMPOSE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]
# The host's routing table as the agent would read it: a LAN, a Docker bridge, the default
# route. The routes Hivora sets (proto 241) are kept in memory, changed by replace and del.
HOST_TABLE = [
    {"dst": "default", "gateway": "192.168.1.1", "dev": "eth0", "protocol": "dhcp"},
    {"dst": "172.18.0.0/16", "dev": "br-1", "protocol": "kernel", "scope": "link"},
    {"dst": "192.168.1.0/24", "dev": "eth0", "protocol": "kernel", "scope": "link"},
]


def fake_ip(gateway: FakeDockerGateway) -> None:
    """``ip`` on the host, behind the fake host agent (only what the static routes use)."""
    marked: dict[str, dict[str, Any]] = {}
    real = gateway.exec_run

    async def exec_run(
        container_id: str, cmd: list[str], user: str | None = None
    ) -> tuple[int, str]:
        argv = cmd[len(HOST) :]
        if argv == ["ip", "-j", "route"]:
            return 0, json.dumps(HOST_TABLE + list(marked.values()))
        if argv == ["ip", "-j", "route", "show", "proto", "241"]:
            return 0, json.dumps(list(marked.values()))
        if argv[:3] == ["ip", "route", "replace"]:
            marked[argv[3]] = {"dst": argv[3].removesuffix("/32"), "gateway": argv[5]}
            return 0, ""
        if argv[:3] == ["ip", "route", "del"]:
            marked.pop(argv[3], None)
            return 0, ""
        return await real(container_id, cmd, user)

    gateway.exec_run = exec_run  # type: ignore[method-assign]


def app() -> FastAPI:
    gateway = FakeDockerGateway()
    fake_ip(gateway)
    runtime = Runtime.build(
        Settings(),
        gateway=gateway,
        compose_cmd=FAKE_COMPOSE,
        compose_env={"FAKE_COMPOSE_MODE": "ok"},
    )
    publish = runtime.bus.publish

    def with_fake_containers(topic: str, **payload: Any) -> Event:
        # Emulate Docker: a deployed app gets a running main container, so pages
        # that only work on running apps (console) are exercised end to end.
        slug = payload.get("app")
        if topic == "app.deployed":
            gateway.put(ContainerInfo(
                id=f"ctr-{slug}", name=f"{slug}-server-1", image="fake",
                state=ContainerState.RUNNING,
                labels={"io.hivora.app": str(slug), "com.docker.compose.service": "server"},
            ), "start")  # fmt: skip
            gateway.stats[f"ctr-{slug}"] = StatsSample(25.0, 300 * 1024**2, 2 * 1024**3, 0, 0)
        elif topic == "app.removed" and f"ctr-{slug}" in gateway.containers:
            gateway.remove(f"ctr-{slug}")
        return publish(topic, **payload)

    runtime.bus.publish = with_fake_containers  # type: ignore[method-assign]
    runtime.releases.fetch = fake_github  # never the network during the e2e tests
    return create_app(runtime=runtime)


async def fake_github(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    """GitHub Releases as the e2e tests see them: a stable release, a newer candidate."""
    page = "https://github.com/hiidenops/hivora/releases/tag/"
    return 200, [
        {"tag_name": "v9.1.0", "prerelease": False, "draft": False, "html_url": page + "v9.1.0",
         "published_at": "2026-10-20T10:00:00Z", "body": "### Ajouté\n\n- Tout ce qui manquait."},
        {"tag_name": "v9.2.0-rc.1", "prerelease": True, "draft": False,
         "html_url": page + "v9.2.0-rc.1", "published_at": "2026-10-25T10:00:00Z",
         "body": "Candidate"},
    ]  # fmt: skip
