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


def test_migration_0016_sites_up_and_down(tmp_path: Path) -> None:
    db = tmp_path / "hivora.db"
    cfg = alembic_config(db)
    command.upgrade(cfg, "0015")
    engine = make_sync_engine(db)
    now = "2026-10-02 12:00:00.000000"
    apps = [  # (id, slug, name, kind): two static sites (one stopped), a catalog nginx
        (1, "vitrine", "Vitrine", "static-site", "running"),
        (2, "blog", "Mon blog", "static-site", "stopped"),
        (3, "manuel", "Manuel", None, "running"),
    ]
    with engine.begin() as conn:
        for app_id, slug, name, kind, state in apps:
            conn.execute(text("INSERT INTO application (id, slug, name, origin, desired_state,"
                              " notes, created_at, kind) VALUES (:i, :s, :n, 'template', :d, '',"
                              " :t, :k)"),
                         dict(i=app_id, s=slug, n=name, d=state, t=now, k=kind))  # fmt: skip

    command.upgrade(cfg, "0016")
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT app_id, slug, name, root, port, server_name, enabled,"
                                 " created_at FROM site ORDER BY app_id")).all()  # fmt: skip
    # One main site per static site, none for the catalog nginx; the app's state is not copied.
    assert [tuple(r) for r in rows] == [
        (1, "main", "Vitrine", "", None, None, 1, now),
        (2, "main", "Mon blog", "", None, None, 1, now),
    ]

    def add(conn: Connection, app_id: int, slug: str, root: str, port: int | None) -> None:
        conn.execute(text("INSERT INTO site (app_id, slug, name, root, port, created_at)"
                          " VALUES (:a, :s, :s, :r, :p, :t)"),
                     {"a": app_id, "s": slug, "r": root, "p": port, "t": now})  # fmt: skip

    with engine.begin() as conn:  # added sites: their own folder and port
        add(conn, 1, "docs", "docs", 9001)
        add(conn, 2, "docs", "docs", 9001)  # same slug and port on another app: allowed
        assert conn.execute(
            text("SELECT enabled FROM site WHERE slug = 'docs'")
        ).scalars().all() == [1, 1]
    refused = [
        (1, "main2", "", None),  # a second main site (same root "")
        (1, "main", "main", 9002),  # same slug on the same app
        (1, "wiki", "wiki", 9001),  # same port on the same app
        (1, "wiki", "", 9003),  # the main site with a port of its own
        (1, "wiki", "wiki", None),  # an added site without a port
        (1, "wiki", "wiki", 70000),  # out of range
        (1, "wiki", "other", 9004),  # a folder that is not the slug
        (1, "", "", None),  # an empty slug
        (99, "wiki", "wiki", 9005),  # an unknown app
    ]
    for app_id, slug, root, port in refused:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            add(conn, app_id, slug, root, port)

    with engine.begin() as conn:  # removing an app removes its sites
        conn.execute(text("DELETE FROM application WHERE id = 1"))
    with engine.connect() as conn:
        left = conn.execute(text("SELECT app_id, slug FROM site ORDER BY id"))
        assert [tuple(r) for r in left] == [
            (2, "main"), (2, "docs"),
        ]  # fmt: skip
        assert conn.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []

    command.downgrade(cfg, "0015")
    with engine.connect() as conn:
        assert "site" not in inspect(engine).get_table_names()
        assert conn.execute(text("SELECT slug FROM application ORDER BY id")).scalars().all() == [
            "blog", "manuel",
        ]  # fmt: skip

    command.upgrade(cfg, "head")  # and back up again: the main site is taken over again
    with engine.connect() as conn:
        sites = [tuple(r) for r in conn.execute(text("SELECT app_id, slug, root FROM site"))]
        assert sites == [(2, "main", "")]
        assert conn.execute(text("PRAGMA integrity_check")).scalar() == "ok"
    engine.dispose()
