"""Backups of an app's volumes and the schedule that makes them."""

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime


class Backup(Base):
    __tablename__ = "backup"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    scheduled: Mapped[bool] = mapped_column(default=False)  # retention applies to these only
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending, ok, failed
    path: Mapped[str] = mapped_column(String(1000))  # the .tar.gz under <data>/backups/<slug>/
    size: Mapped[int] = mapped_column(default=0)


class BackupSchedule(Base):
    __tablename__ = "backup_schedule"

    app_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(default=False)
    frequency: Mapped[str] = mapped_column(String(10), default="daily")  # daily, weekly, hours
    hour: Mapped[int] = mapped_column(default=4)  # local time (HIVORA_TIMEZONE)
    minute: Mapped[int] = mapped_column(default=0)
    weekday: Mapped[int] = mapped_column(default=0)  # weekly: 0 = Monday
    every_hours: Mapped[int] = mapped_column(default=6)  # frequency "hours"
    keep: Mapped[int] = mapped_column(default=7)  # scheduled backups kept
    stop: Mapped[bool] = mapped_column(default=True)  # stop the app while archiving
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
