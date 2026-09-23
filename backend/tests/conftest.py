from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hivora.db.all_models  # noqa: F401
from hivora.db.engine import make_engine, make_sessionmaker
from hivora.db.migrate import upgrade_to_head
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
