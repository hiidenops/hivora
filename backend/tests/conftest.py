import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hivora.db.all_models  # noqa: F401
from hivora.core.config import Settings
from hivora.db.engine import make_engine, make_sessionmaker
from hivora.db.migrate import upgrade_to_head
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.templates import Catalog

REPO_TEMPLATES = Path(__file__).parents[2] / "templates"


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db = tmp_path / "hivora.db"
    upgrade_to_head(db)
    engine = make_engine(db)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
def catalog() -> Catalog:
    c = Catalog()
    assert c.load_directory(REPO_TEMPLATES) == []
    return c


FAKE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        volumes_root=tmp_path / "srv",
        catalog_dir=Path(__file__).parents[2] / "templates",
        dev_insecure_cookies=True,
        puid=os.getuid(),
        pgid=os.getgid(),
        host_lan_ip="192.168.1.10",
        host_public_ip="203.0.113.7",
    )
    runtime = Runtime.build(
        settings,
        gateway=FakeDockerGateway(),
        compose_cmd=FAKE,
        compose_env={"FAKE_COMPOSE_MODE": "leak"},
    )
    with TestClient(create_app(runtime=runtime)) as c:
        yield c
