"""`python -m hivora bootstrap` and `reset-admin-password`: run by the installer (or by
hand on the machine) in a one-off container, before the server starts. They build only
what they use: the prepared database, the auth service; no Docker.

Output: ``KEY=value`` lines a shell script reads without jq. The password appears there
only (shown once): never in the logs.
"""

import asyncio

from hivora.auth.initial import random_password, reset_password, secure_default_admin
from hivora.auth.passwords import DEFAULT_ADMIN
from hivora.auth.service import AuthService
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox, load_or_create_master_key
from hivora.db.engine import make_engine, make_sessionmaker
from hivora.runtime import prepare_database


def bootstrap(settings: Settings) -> dict[str, str]:
    """The initial admin: created with a random password on a new panel (``created``),
    admin/admin never changed given one (``secured``), any other account left (``kept``)."""
    return asyncio.run(_bootstrap(settings))


def reset_admin_password(settings: Settings, username: str = DEFAULT_ADMIN) -> dict[str, str]:
    """A new random password for ``username`` (to change at next login)."""
    return asyncio.run(_reset(settings, username))


async def _bootstrap(settings: Settings) -> dict[str, str]:
    prepare_database(settings)
    engine = make_engine(settings.db_path)
    sessions = make_sessionmaker(engine)
    box = SecretBox(load_or_create_master_key(settings.secret_key_path))
    auth = AuthService(settings=settings, sessions=sessions, box=box, bus=EventBus())
    password = random_password()
    try:
        if await auth.ensure_initial_admin(password):
            state = "created"
        elif await secure_default_admin(sessions, password):
            state = "secured"
        else:
            return {"ADMIN": "kept"}
    finally:
        await engine.dispose()
    return {"ADMIN": state, "ADMIN_USER": DEFAULT_ADMIN, "ADMIN_PASSWORD": password}


async def _reset(settings: Settings, username: str) -> dict[str, str]:
    prepare_database(settings)
    engine = make_engine(settings.db_path)
    password = random_password()
    try:
        await reset_password(make_sessionmaker(engine), username, password)
    finally:
        await engine.dispose()
    return {"ADMIN": "reset", "ADMIN_USER": username, "ADMIN_PASSWORD": password}
