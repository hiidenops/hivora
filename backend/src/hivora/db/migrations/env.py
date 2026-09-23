"""Alembic environment. The database path comes from the caller or from Settings."""

from pathlib import Path
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext

import hivora.db.all_models  # noqa: F401  (register every table on the metadata)
from hivora.core.config import Settings
from hivora.db.base import Base, UTCDateTime
from hivora.db.engine import make_sync_engine

db_path: Path = context.config.attributes.get("db_path") or Settings().db_path


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    # Migrations must not import application types: UTCDateTime is a DATETIME.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


with make_sync_engine(db_path).connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things in place
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()
