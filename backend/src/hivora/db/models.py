"""Tables owned by the db module itself. Other modules declare their own models."""

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base


class Setting(Base):
    """Global key/value settings (panel port, volumes root, language, ...)."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
