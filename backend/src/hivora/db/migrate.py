"""Programmatic Alembic entrypoint: the app upgrades its own schema on startup."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

SchemaState = Literal["fresh", "current", "behind", "newer"]


class SchemaTooNewError(RuntimeError):
    """The database was migrated by a newer Hivora: this code must not touch it."""

    def __init__(self, revision: str) -> None:
        super().__init__(
            f"the database was written by a newer version of Hivora (schema revision "
            f"{revision}, unknown to this one): nothing was changed. Install that version "
            f"again (install.sh --version …) or restore a panel backup "
            f"(<data>/backups/_hivora/)."
        )
        self.revision = revision


def alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["db_path"] = db_path
    return cfg


def upgrade_to_head(db_path: Path) -> None:
    command.upgrade(alembic_config(db_path), "head")


def db_revision(db_path: Path) -> str | None:
    """The schema revision stored in the database (None: no file, or never migrated).
    Read-only: the file is opened in ``mode=ro``."""
    if not db_path.is_file():
        return None
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as conn:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:  # no alembic_version table yet
            return None
    return str(row[0]) if row else None


def schema_state(db_path: Path) -> SchemaState:
    """Where the database stands against this code's migrations, without writing to it."""
    revision = db_revision(db_path)
    if revision is None:
        return "fresh"
    script = ScriptDirectory.from_config(alembic_config(db_path))
    if revision == script.get_current_head():
        return "current"
    known = {r.revision for r in script.walk_revisions()}
    return "behind" if revision in known else "newer"
