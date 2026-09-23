"""ASGI factory for the frontend end-to-end tests: real API and UI, fake Docker.

uvicorn --factory e2e_app:app --app-dir tests   (settings from HIVORA_* env)
"""

import sys
from pathlib import Path

from fastapi import FastAPI

from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime

FAKE_COMPOSE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


def app() -> FastAPI:
    runtime = Runtime.build(
        Settings(),
        gateway=FakeDockerGateway(),
        compose_cmd=FAKE_COMPOSE,
        compose_env={"FAKE_COMPOSE_MODE": "ok"},
    )
    return create_app(runtime=runtime)
