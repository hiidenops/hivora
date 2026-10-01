from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, select, text
from sqlalchemy.exc import IntegrityError

import hivora.db.all_models  # noqa: F401
from hivora.db.base import Base
from hivora.db.engine import make_engine, make_sessionmaker, make_sync_engine
from hivora.db.migrate import alembic_config, upgrade_to_head
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


def test_migration_0015_static_sites_up_and_down(tmp_path: Path) -> None:
    db = tmp_path / "hivora.db"
    cfg = alembic_config(db)
    command.upgrade(cfg, "0014")
    engine = make_sync_engine(db)
    now = "2026-10-01 12:00:00"
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO application (id, slug, name, origin, desired_state, notes,"
                          " created_at) VALUES (1, 'web', 'web', 'template', 'running', '', :t)"),
                     {"t": now})  # fmt: skip
        conn.execute(text("INSERT INTO job (kind, app_id, params, status, progress, log,"
                          " created_at) VALUES ('deploy', 1, '{}', 'succeeded', 100, '', :t)"),
                     {"t": now})  # fmt: skip

    def columns() -> list[str]:
        return [c["name"] for c in inspect(engine).get_columns("application")]

    def add_job(conn: Connection, kind: str) -> None:
        conn.execute(text("INSERT INTO job (kind, app_id, params, status, progress, log,"
                          " created_at) VALUES (:k, 1, '{}', 'queued', 0, '', :t)"),
                     {"k": kind, "t": now})  # fmt: skip

    assert "kind" not in columns()
    with pytest.raises(IntegrityError), engine.begin() as conn:  # not a job kind yet
        add_job(conn, "site_content")

    command.upgrade(cfg, "0015")
    assert "kind" in columns()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT kind FROM application")).scalar_one() is None
        conn.execute(text("UPDATE application SET kind = 'static-site'"))
        add_job(conn, "site_content")
        add_job(conn, "site_file")
    with pytest.raises(IntegrityError), engine.begin() as conn:  # the CHECK still holds
        add_job(conn, "site_unknown")

    command.downgrade(cfg, "0014")
    assert "kind" not in columns()
    with engine.connect() as conn:  # site jobs removed, the others kept
        assert conn.execute(text("SELECT kind FROM job")).scalars().all() == ["deploy"]
        assert conn.execute(text("SELECT slug FROM application")).scalars().all() == ["web"]

    command.upgrade(cfg, "head")  # and back up again
    assert "kind" in columns()
    engine.dispose()
