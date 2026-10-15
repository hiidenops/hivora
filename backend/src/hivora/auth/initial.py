"""The initial admin account when the installer sets it up (`python -m hivora bootstrap`)
or when someone with access to the machine resets a password (`reset-admin-password`).

The password is random and shown once on the command's output; never logged, never stored
in clear. The account must still change it at first login. ``INITIAL_PASSWORD`` (a
`setting` row) tells `first_start` that admin/admin is not the password any more, without
an Argon2 check on each health request.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.auth.models import User
from hivora.auth.passwords import DEFAULT_ADMIN
from hivora.auth.sessions import revoke_sessions
from hivora.auth.users import UserNotFoundError
from hivora.crypto.passwords import hash_password, verify_password
from hivora.db.models import Setting

# A setting key, not a password: set once the installer chose admin's password.
INITIAL_PASSWORD = "auth.initial_password"  # noqa: S105
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: read from a terminal
GROUPS, GROUP = 4, 5  # 20 characters, about 99 bits


def random_password() -> str:
    """20 random characters in groups of 5 (``kq7mz-x3wpt-…``)."""
    chars = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP))
    return "-".join(chars[i : i + GROUP] for i in range(0, len(chars), GROUP))


async def mark_chosen(session: AsyncSession) -> None:
    await session.merge(Setting(key=INITIAL_PASSWORD, value=True))


async def secure_default_admin(sessions: async_sessionmaker[AsyncSession], password: str) -> bool:
    """admin/admin, the only account and never changed, gets ``password`` instead
    (still to be changed at first login). False: anything else, left as it is."""
    async with sessions() as session, session.begin():
        users = (await session.scalars(select(User).limit(2))).all()
        if len(users) != 1:
            return False
        user = users[0]
        if not (user.username == DEFAULT_ADMIN and user.must_change_password
                and verify_password(user.password_hash, DEFAULT_ADMIN)):  # fmt: skip
            return False
        user.password_hash = hash_password(password)
        await revoke_sessions(session, user.id)
        await mark_chosen(session)
    return True


async def reset_password(sessions: async_sessionmaker[AsyncSession], username: str,
                         password: str) -> None:  # fmt: skip
    """A new password for ``username``, to change at next login; its sessions end."""
    async with sessions() as session, session.begin():
        user = await session.scalar(select(User).where(User.username == username))
        if user is None:
            raise UserNotFoundError(username)
        user.password_hash = hash_password(password)
        user.must_change_password = True
        await revoke_sessions(session, user.id)
        if username == DEFAULT_ADMIN:
            await mark_chosen(session)
