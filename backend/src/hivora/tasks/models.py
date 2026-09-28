"""A task an app runs on a schedule (a simplified cron)."""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime


class ScheduledTask(Base):
    __tablename__ = "scheduled_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(default=True)
    # restart, stop, start, backup, command
    action: Mapped[str] = mapped_column(String(10))
    # command: "shell" (sh -c in the container) or "console" (the game's console command)
    mode: Mapped[str] = mapped_column(String(10), default="shell")
    service: Mapped[str | None] = mapped_column(String(63))  # command: None = main service
    command: Mapped[str] = mapped_column(Text, default="")
    frequency: Mapped[str] = mapped_column(String(10), default="daily")  # daily, weekly, hours
    hour: Mapped[int] = mapped_column(default=4)
    minute: Mapped[int] = mapped_column(default=0)
    weekday: Mapped[int] = mapped_column(default=0)
    every_hours: Mapped[int] = mapped_column(default=6)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status: Mapped[str | None] = mapped_column(String(10))  # ok, failed, queued
    last_output: Mapped[str] = mapped_column(Text, default="")  # tail, secrets masked
