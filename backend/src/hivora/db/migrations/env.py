"""Alembic environment. The database path comes from the caller or from Settings."""

from pathlib import Path

from alembic import context

import hivora.db.models  # noqa: F401  (register tables on the metadata)
from hivora.core.config import Settings
from hivora.db.base import Base
from hivora.db.engine import make_sync_engine

db_path: Path = context.config.attributes.get("db_path") or Settings().db_path

with make_sync_engine(db_path).connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things in place
    )
    with context.begin_transaction():
        context.run_migrations()
