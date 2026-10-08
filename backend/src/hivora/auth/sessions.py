"""Session records: the cookie token (only its hash is stored), CSRF, revocation."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.auth.models import Session, User

LAST_SEEN_RESOLUTION = timedelta(minutes=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_matches(expected: str, provided: str | None) -> bool:
    return provided is not None and hmac.compare_digest(expected, provided)


def new_session(user: User, *, ip: str | None, user_agent: str | None, now: datetime,
                max_days: int) -> tuple[Session, str]:  # fmt: skip
    """A session for this user, and its raw cookie value (never stored)."""
    token = secrets.token_urlsafe(32)
    record = Session(
        user_id=user.id, token_hash=hash_token(token),
        csrf_token=secrets.token_urlsafe(24), ip=ip,
        user_agent=(user_agent or "")[:300] or None, created_at=now, last_seen_at=now,
        expires_at=now + timedelta(days=max_days),
    )  # fmt: skip
    return record, token


async def revoke_sessions(session: AsyncSession, user_id: int, keep: int | None = None) -> None:
    query = delete(Session).where(Session.user_id == user_id)
    if keep is not None:
        query = query.where(Session.id != keep)
    await session.execute(query)
