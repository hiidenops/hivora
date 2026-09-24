"""ASGI factory for the frontend end-to-end tests: real API and UI, fake Docker.

uvicorn --factory e2e_app:app --app-dir tests   (settings from HIVORA_* env)
"""

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from hivora.core.config import Settings
from hivora.core.events import Event
from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime

FAKE_COMPOSE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


def app() -> FastAPI:
    gateway = FakeDockerGateway()
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
        elif topic == "app.removed" and f"ctr-{slug}" in gateway.containers:
            gateway.remove(f"ctr-{slug}")
        return publish(topic, **payload)

    runtime.bus.publish = with_fake_containers  # type: ignore[method-assign]
    return create_app(runtime=runtime)
