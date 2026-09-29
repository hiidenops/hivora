"""Types and writes shared by the app commands (deploy, settings update, hand-written
compose, free images)."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import Application, AppRevision, AppSecret, DesiredState, Service
from hivora.core.errors import ValidationError
from hivora.crypto.cipher import Purpose, SecretBox
from hivora.jobs import Job, JobKind, JobQueue

LABEL_COMPOSE_SERVICE = "com.docker.compose.service"


class UnsupportedArchitectureError(ValidationError):
    code = "unsupported_architecture"


@dataclass(frozen=True, slots=True)
class DeployRequest:
    template: str
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    slug: str | None = None
    zone: str | None = None  # zone slug; None: "unclassified"


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:50].strip("-") or "app"


def secret_context(app_id: int, key: str) -> str:
    return f"app:{app_id}:{key}"


def store_secrets(session: AsyncSession, box: SecretBox, app_id: int,
                  secrets: dict[str, str]) -> None:  # fmt: skip
    """Seal each secret value and add it to the caller's transaction."""
    for key, value in secrets.items():
        sealed = box.seal(Purpose.APP_SECRET, value, secret_context(app_id, key))
        session.add(
            AppSecret(app_id=app_id, key=key, ciphertext=sealed.ciphertext, nonce=sealed.nonce)
        )


async def queue_revision(
    session: AsyncSession, jobs: JobQueue, app: Application, revision: AppRevision,
    services: list[Service], params: dict[str, Any] | None = None,
) -> Job:  # fmt: skip
    """The declared services now describe ``revision``: replace them, add the revision and
    queue the job applying it, all in the caller's transaction."""
    # Delete the old services first (orphan cascade + flush): same names, unique per app.
    app.services.clear()
    await session.flush()
    app.services = services
    session.add(revision)
    await session.flush()
    app.desired_state = DesiredState.RUNNING
    return jobs.add(session, JobKind.UPDATE, app_id=app.id, app_slug=app.slug,
                    params={"revision_id": revision.id} | (params or {}))  # fmt: skip
