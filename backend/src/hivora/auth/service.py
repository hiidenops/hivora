"""Authentication, sessions, TOTP and user management."""

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from functools import cache

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.auth.models import Role, Session, User
from hivora.auth.ratelimit import LoginRateLimiter
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, HivoraError, NotFoundError, ValidationError
from hivora.core.events import EventBus
from hivora.crypto.cipher import Purpose, Sealed, SecretBox
from hivora.crypto.passwords import hash_password, needs_rehash, verify_password
from hivora.crypto.totp import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    match_recovery_code,
    provisioning_uri,
    verify_totp,
)

logger = logging.getLogger(__name__)

DEFAULT_ADMIN = "admin"
MIN_PASSWORD_LENGTH = 10
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_LAST_SEEN_RESOLUTION = timedelta(minutes=1)


@cache
def _dummy_hash() -> str:
    """Verified when the user does not exist, so timing does not reveal usernames."""
    return hash_password(secrets.token_hex(16))


class AuthError(HivoraError):
    code = "not_authenticated"


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"


class TotpRequiredError(AuthError):
    code = "totp_required"


class UserNotFoundError(NotFoundError):
    code = "user_not_found"


class LastAdminError(ConflictError):
    code = "last_admin"


class WeakPasswordError(ValidationError):
    code = "weak_password"


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    session: Session
    token: str  # raw cookie value, never stored


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    secret: str
    uri: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_password_policy(password: str, username: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError("password too short", min_length=MIN_PASSWORD_LENGTH)
    if password.lower() in (username.lower(), DEFAULT_ADMIN):
        raise WeakPasswordError("password too easy to guess")


def validate_username(username: str) -> str:
    username = username.strip().lower()
    if not _USERNAME.match(username):
        raise ValidationError("invalid username", field="username")
    return username


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        box: SecretBox,
        bus: EventBus,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.box = box
        self.bus = bus
        self.clock = clock or SystemClock()
        self.limiter = LoginRateLimiter(self.clock)

    # --- bootstrap ------------------------------------------------------------
    async def ensure_initial_admin(self) -> bool:
        """First start: create admin/admin, which must change its password."""
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(func.count(User.id))):
                return False
            session.add(
                User(
                    username=DEFAULT_ADMIN,
                    password_hash=hash_password(DEFAULT_ADMIN),
                    role=Role.ADMIN,
                    must_change_password=True,
                    created_at=self.clock.now(),
                )
            )
        logger.warning("initial account created: admin / admin (password change required)")
        return True

    # --- login / sessions -----------------------------------------------------
    async def login(
        self,
        username: str,
        password: str,
        *,
        totp_code: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginResult:
        username = username.strip().lower()
        keys = (f"ip:{ip}", f"user:{username}")
        self.limiter.check(*keys)
        async with self.sessions() as session, session.begin():
            user = await session.scalar(select(User).where(User.username == username))
            valid = verify_password(user.password_hash if user else _dummy_hash(), password)
            if not user or not valid or user.disabled:
                self.limiter.failure(*keys)
                self.bus.publish("auth.login_failed", username=username, ip=ip)
                raise InvalidCredentialsError("invalid username or password")
            if user.totp_enabled:
                if not totp_code:
                    raise TotpRequiredError("TOTP code required")
                if not self._check_second_factor(user, totp_code):
                    self.limiter.failure(*keys)
                    self.bus.publish("auth.login_failed", username=username, ip=ip, step="totp")
                    raise InvalidCredentialsError("invalid TOTP code")
            self.limiter.success(*keys)
            if needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            now = self.clock.now()
            user.last_login_at = now
            token = secrets.token_urlsafe(32)
            record = Session(
                user_id=user.id, token_hash=hash_token(token),
                csrf_token=secrets.token_urlsafe(24), ip=ip,
                user_agent=(user_agent or "")[:300] or None, created_at=now, last_seen_at=now,
                expires_at=now + timedelta(days=self.settings.session_max_days),
            )  # fmt: skip
            session.add(record)
        self.bus.publish("auth.login", user_id=user.id, username=user.username, ip=ip)
        return LoginResult(user, record, token)

    def _check_second_factor(self, user: User, code: str) -> bool:
        if verify_totp(self._totp_secret(user), code, self.clock.now()):
            return True
        index = match_recovery_code(code, user.recovery_codes)
        if index is None:
            return False
        user.recovery_codes = [h for i, h in enumerate(user.recovery_codes) if i != index]
        return True

    async def authenticate(self, token: str) -> tuple[User, Session] | None:
        now = self.clock.now()
        async with self.sessions() as session, session.begin():
            record = await session.scalar(
                select(Session).where(Session.token_hash == hash_token(token))
            )
            if record is None:
                return None
            idle = timedelta(hours=self.settings.session_idle_hours)
            user = await session.get(User, record.user_id)
            if (
                record.expires_at <= now
                or record.last_seen_at + idle <= now
                or (user is None or user.disabled)
            ):
                await session.delete(record)
                return None
            if now - record.last_seen_at >= _LAST_SEEN_RESOLUTION:
                record.last_seen_at = now
            return user, record

    async def logout(self, session_id: int) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(delete(Session).where(Session.id == session_id))
        self.bus.publish("auth.logout")

    # --- self service -----------------------------------------------------------
    async def change_password(
        self, user_id: int, current: str, new: str, *, keep_session: int | None = None
    ) -> None:
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            if not verify_password(user.password_hash, current):
                raise InvalidCredentialsError("current password is wrong")
            check_password_policy(new, user.username)
            user.password_hash = hash_password(new)
            user.must_change_password = False
            await self._revoke_sessions(session, user.id, keep=keep_session)
        self.bus.publish("auth.password_changed", user_id=user_id)

    async def totp_enroll(self, user_id: int) -> TotpEnrollment:
        secret = generate_totp_secret()
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            if user.totp_enabled:
                raise ConflictError("TOTP already enabled")
            sealed = self.box.seal(Purpose.TOTP, secret, f"user:{user.id}")
            user.totp_ciphertext, user.totp_nonce = sealed.ciphertext, sealed.nonce
            return TotpEnrollment(secret, provisioning_uri(secret, user.username))

    async def totp_confirm(self, user_id: int, code: str) -> list[str]:
        """Enable TOTP after a first valid code; returns the recovery codes (shown once)."""
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            if user.totp_enabled or user.totp_ciphertext is None:
                raise ConflictError("no TOTP enrollment in progress")
            if not verify_totp(self._totp_secret(user), code, self.clock.now()):
                raise InvalidCredentialsError("invalid TOTP code")
            codes = generate_recovery_codes()
            user.recovery_codes = [hash_recovery_code(c) for c in codes]
            user.totp_enabled = True
        self.bus.publish("auth.totp_enabled", user_id=user_id)
        return codes

    async def totp_disable(self, user_id: int, password: str) -> None:
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            if not verify_password(user.password_hash, password):
                raise InvalidCredentialsError("password is wrong")
            _clear_totp(user)
        self.bus.publish("auth.totp_disabled", user_id=user_id)

    # --- administration -----------------------------------------------------
    async def list_users(self) -> list[User]:
        async with self.sessions() as session:
            return list(await session.scalars(select(User).order_by(User.username)))

    async def create_user(self, username: str, role: Role, password: str) -> User:
        username = validate_username(username)
        check_password_policy(password, username)
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(User.id).where(User.username == username)):
                raise ConflictError("username already taken", field="username")
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                must_change_password=True,
                created_at=self.clock.now(),
            )
            session.add(user)
        self.bus.publish("user.created", target=username, role=role.value)
        return user

    async def update_user(
        self, user_id: int, *, role: Role | None = None, disabled: bool | None = None
    ) -> User:
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            new_role = role if role is not None else user.role
            new_disabled = disabled if disabled is not None else user.disabled
            if (
                user.role is Role.ADMIN
                and not user.disabled
                and (new_role is not Role.ADMIN or new_disabled)
            ):
                await self._ensure_other_admin(session, user.id)
            user.role, user.disabled = new_role, new_disabled
            if new_disabled:
                await self._revoke_sessions(session, user.id)
        self.bus.publish(
            "user.updated", target=user.username, role=user.role.value, disabled=user.disabled
        )
        return user

    async def reset_password(self, user_id: int, temporary: str) -> None:
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            check_password_policy(temporary, user.username)
            user.password_hash = hash_password(temporary)
            user.must_change_password = True
            await self._revoke_sessions(session, user.id)
        self.bus.publish("user.password_reset", target=user.username)

    async def reset_totp(self, user_id: int) -> None:
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            _clear_totp(user)
        self.bus.publish("user.totp_reset", target=user.username)

    async def delete_user(self, user_id: int, *, acting_user_id: int) -> None:
        if user_id == acting_user_id:
            raise ConflictError("you cannot delete your own account")
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            if user.role is Role.ADMIN and not user.disabled:
                await self._ensure_other_admin(session, user.id)
            await session.delete(user)
        self.bus.publish("user.deleted", target=user.username)

    async def list_sessions(self, user_id: int) -> list[Session]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(Session).where(Session.user_id == user_id).order_by(Session.id.desc())
            )
            return list(rows)

    async def revoke_sessions(self, user_id: int, *, keep: int | None = None) -> None:
        async with self.sessions() as session, session.begin():
            user = await self._user(session, user_id)
            await self._revoke_sessions(session, user.id, keep=keep)
        self.bus.publish("user.sessions_revoked", target=user.username)

    # --- helpers --------------------------------------------------------------
    async def _user(self, session: AsyncSession, user_id: int) -> User:
        user = await session.get(User, user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))
        return user

    async def _ensure_other_admin(self, session: AsyncSession, user_id: int) -> None:
        others = await session.scalar(
            select(func.count(User.id)).where(
                User.role == Role.ADMIN, User.disabled.is_(False), User.id != user_id
            )
        )
        if not others:
            raise LastAdminError("at least one active admin is required")

    @staticmethod
    async def _revoke_sessions(
        session: AsyncSession, user_id: int, keep: int | None = None
    ) -> None:
        query = delete(Session).where(Session.user_id == user_id)
        if keep is not None:
            query = query.where(Session.id != keep)
        await session.execute(query)

    def _totp_secret(self, user: User) -> str:
        if user.totp_ciphertext is None or user.totp_nonce is None:
            raise HivoraError("TOTP not configured")
        return self.box.open(
            Purpose.TOTP, Sealed(user.totp_nonce, user.totp_ciphertext), f"user:{user.id}"
        )


def _clear_totp(user: User) -> None:
    user.totp_enabled = False
    user.totp_ciphertext = user.totp_nonce = None
    user.recovery_codes = []


def csrf_matches(expected: str, provided: str | None) -> bool:
    return provided is not None and hmac.compare_digest(expected, provided)
