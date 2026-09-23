"""Programmatic Alembic entrypoint: the app upgrades its own schema on startup."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["db_path"] = db_path
    return cfg


def upgrade_to_head(db_path: Path) -> None:
    command.upgrade(alembic_config(db_path), "head")
