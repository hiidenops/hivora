"""Users, roles and sessions."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime, str_enum


class Role(StrEnum):
    VIEWER = "viewer"  # read-only
    OPERATOR = "operator"  # run and deploy apps, no accounts nor configuration
    ADMIN = "admin"  # everything

    @property
    def level(self) -> int:
        return _LEVELS[self]

    def allows(self, required: "Role") -> bool:
        return self.level >= required.level


_LEVELS = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(str_enum(Role))
    must_change_password: Mapped[bool] = mapped_column(default=False)
    disabled: Mapped[bool] = mapped_column(default=False)
    # TOTP seed, AES-GCM encrypted; set during enrollment, enabled once verified.
    totp_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    recovery_codes: Mapped[list[str]] = mapped_column(JSON, default=list)  # sha256 hashes
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Session(Base):
    __tablename__ = "session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)  # absolute limit
