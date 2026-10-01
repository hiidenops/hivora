"""Persisted job queue: every mutating action runs as a job."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime, str_enum


class JobKind(StrEnum):
    DEPLOY = "deploy"
    UPDATE = "update"
    REMOVE = "remove"
    PULL = "pull"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    ROLLBACK = "rollback"
    ADOPT = "adopt"
    CONVERT = "convert"
    MOVE_ZONE = "move_zone"
    WORLD_IMPORT = "world_import"
    WORLD_DELETE = "world_delete"
    BACKUP = "backup"
    BACKUP_RESTORE = "backup_restore"
    SITE_CONTENT = "site_content"
    SITE_FILE = "site_file"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # Hivora stopped while the job was running


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (Index("ix_job_status_id", "status", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[JobKind] = mapped_column(str_enum(JobKind))
    app_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), index=True
    )
    app_slug: Mapped[str | None] = mapped_column(String(63))  # kept after app removal
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.QUEUED)
    progress: Mapped[int] = mapped_column(default=0)
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
