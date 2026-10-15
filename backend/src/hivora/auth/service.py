"""Authentication, sessions and the second factor; user administration in `auth.users`.

Rules and pieces it relies on: `passwords` (policy, Argon2id), `sessions` (cookie token,
CSRF, revocation), `totp` (codes accepted once, recovery codes), `ratelimit` (attempts).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.auth.initial import INITIAL_PASSWORD, mark_chosen
from hivora.auth.models import Role, Session, User
from hivora.auth.passwords import DEFAULT_ADMIN, check_password_policy, dummy_hash
from hivora.auth.ratelimit import LoginRateLimiter
from hivora.auth.sessions import (
    LAST_SEEN_RESOLUTION,
    hash_token,
    new_session,
    revoke_sessions,
)
from hivora.auth.totp import TotpEnrollment, TotpGuard, clear_totp
from hivora.auth.users import UserAdmin, get_user
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, HivoraError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.crypto.passwords import hash_password, needs_rehash, verify_password
from hivora.crypto.totp import generate_recovery_codes, hash_recovery_code
from hivora.db.models import Setting

logger = logging.getLogger(__name__)

CONSOLE_CONFIRMATION = timedelta(minutes=15)


class AuthError(HivoraError):
    code = "not_authenticated"


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"


class TotpRequiredError(AuthError):
    code = "totp_required"


class TotpMandatoryError(ConflictError):
    code = "totp_mandatory"  # a public panel: TOTP cannot be turned off


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    session: Session
    token: str  # raw cookie value, never stored


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
        self.totp = TotpGuard(box, self.clock)
        self.limiter = LoginRateLimiter(self.clock)
        self.users = UserAdmin(sessions=sessions, bus=bus, clock=self.clock)
        # session id -> until when consoles are allowed without a new TOTP code
        self._console_ok: dict[int, datetime] = {}

    # --- bootstrap ------------------------------------------------------------
    async def first_start(self) -> bool:
        """True while the only account is the initial admin/admin, not yet changed (not when
        the installer chose its password: see `auth.initial`)."""
        async with self.sessions() as session:
            users = (await session.scalars(select(User).limit(2))).all()
            chosen = await session.get(Setting, INITIAL_PASSWORD)
        return (
            chosen is None
            and len(users) == 1
            and users[0].username == DEFAULT_ADMIN
            and users[0].must_change_password
        )

    async def ensure_initial_admin(self, password: str | None = None) -> bool:
        """First start: create admin, which must change its password: admin/admin, or
        ``password`` when the installer chose it (`python -m hivora bootstrap`)."""
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(func.count(User.id))):
                return False
            session.add(
                User(
                    username=DEFAULT_ADMIN,
                    password_hash=hash_password(password or DEFAULT_ADMIN),
                    role=Role.ADMIN,
                    must_change_password=True,
                    created_at=self.clock.now(),
                )
            )
            if password:
                await mark_chosen(session)
        if password:  # never the password itself: the installer shows it
            logger.warning("initial account created: admin (password shown by the installer)")
        else:
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
            valid = verify_password(user.password_hash if user else dummy_hash(), password)
            if not user or not valid or user.disabled:
                self.limiter.failure(*keys)
                self.bus.publish("auth.login_failed", username=username, ip=ip)
                raise InvalidCredentialsError("invalid username or password")
            if user.totp_enabled:
                if not totp_code:
                    raise TotpRequiredError("TOTP code required")
                if not self.totp.check(user, totp_code):
                    self.limiter.failure(*keys)
                    self.bus.publish("auth.login_failed", username=username, ip=ip, step="totp")
                    raise InvalidCredentialsError("invalid TOTP code")
            self.limiter.success(*keys)
            if needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            now = self.clock.now()
            user.last_login_at = now
            record, token = new_session(user, ip=ip, user_agent=user_agent, now=now,
                                        max_days=self.settings.session_max_days)  # fmt: skip
            session.add(record)
        self.bus.publish("auth.login", user_id=user.id, username=user.username, ip=ip)
        return LoginResult(user, record, token)

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
            if now - record.last_seen_at >= LAST_SEEN_RESOLUTION:
                record.last_seen_at = now
            return user, record

    async def logout(self, session_id: int) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(delete(Session).where(Session.id == session_id))
        self.bus.publish("auth.logout")

    async def list_sessions(self, user_id: int) -> list[Session]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(Session).where(Session.user_id == user_id).order_by(Session.id.desc())
            )
            return list(rows)

    # --- console re-confirmation ---------------------------------------------
    def recently_confirmed(self, session_id: int, totp_enabled: bool) -> bool:
        """A TOTP code confirmed on this session in the last minutes (console, host)."""
        if not totp_enabled:
            return True
        until = self._console_ok.get(session_id)
        return until is not None and until > self.clock.now()

    def console_confirmed(self, user: User, session_id: int) -> bool:
        if not user.totp_enabled:
            return True
        until = self._console_ok.get(session_id)
        return until is not None and until > self.clock.now()

    async def confirm_console(self, user_id: int, session_id: int, code: str) -> None:
        async with self.sessions() as session, session.begin():
            user = await get_user(session, user_id)
            if user.totp_enabled and not self.totp.check(user, code):
                raise InvalidCredentialsError("invalid TOTP code")
        self._console_ok[session_id] = self.clock.now() + CONSOLE_CONFIRMATION

    # --- self service -----------------------------------------------------------
    async def change_password(
        self, user_id: int, current: str, new: str, *, keep_session: int | None = None
    ) -> None:
        async with self.sessions() as session, session.begin():
            user = await get_user(session, user_id)
            if not verify_password(user.password_hash, current):
                raise InvalidCredentialsError("current password is wrong")
            check_password_policy(new, user.username)
            user.password_hash = hash_password(new)
            user.must_change_password = False
            await revoke_sessions(session, user.id, keep=keep_session)
        self.bus.publish("auth.password_changed", user_id=user_id)

    async def totp_enroll(self, user_id: int) -> TotpEnrollment:
        async with self.sessions() as session, session.begin():
            user = await get_user(session, user_id)
            if user.totp_enabled:
                raise ConflictError("TOTP already enabled")
            return self.totp.enroll(user)

    async def totp_confirm(self, user_id: int, code: str) -> list[str]:
        """Enable TOTP after a first valid code; returns the recovery codes (shown once)."""
        async with self.sessions() as session, session.begin():
            user = await get_user(session, user_id)
            if user.totp_enabled or user.totp_ciphertext is None:
                raise ConflictError("no TOTP enrollment in progress")
            if not self.totp.accept(user, code):
                raise InvalidCredentialsError("invalid TOTP code")
            codes = generate_recovery_codes()
            user.recovery_codes = [hash_recovery_code(c) for c in codes]
            user.totp_enabled = True
        self.bus.publish("auth.totp_enabled", user_id=user_id)
        return codes

    async def totp_disable(self, user_id: int, password: str) -> None:
        async with self.sessions() as session, session.begin():
            user = await get_user(session, user_id)
            if not verify_password(user.password_hash, password):
                raise InvalidCredentialsError("password is wrong")
            if self.settings.access == "public":
                raise TotpMandatoryError(
                    "this panel is public: two-factor authentication is required"
                )
            clear_totp(user)
        self.bus.publish("auth.totp_disabled", user_id=user_id)
