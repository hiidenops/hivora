from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, text

import hivora.db.models  # noqa: F401
from hivora.db.base import Base
from hivora.db.engine import make_engine, make_sessionmaker, make_sync_engine
from hivora.db.migrate import upgrade_to_head
from hivora.db.models import Setting


def test_migrations_match_models(tmp_path: Path) -> None:
    db = tmp_path / "hivora.db"
    upgrade_to_head(db)
    with make_sync_engine(db).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


async def test_engine_uses_wal_and_foreign_keys(tmp_path: Path) -> None:
    db = tmp_path / "hivora.db"
    upgrade_to_head(db)
    engine = make_engine(db)
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA journal_mode"))).scalar() == "wal"
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1

    sessions = make_sessionmaker(engine)
    async with sessions() as session, session.begin():
        session.add(Setting(key="language", value={"code": "fr"}))
    async with sessions() as session:
        row = (await session.execute(select(Setting))).scalar_one()
        assert row.value == {"code": "fr"}
    await engine.dispose()
