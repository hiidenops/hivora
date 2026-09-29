"""Hand-written compose files (admin): resolved by Compose, checked, applied as a revision."""

import difflib
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.compose_check import problems as compose_problems
from hivora.apps.core import (
    PortConflictError,
    conflict_dict,
    decrypt_secrets,
    get_app,
    latest_revision,
    queue_revision,
)
from hivora.apps.models import (
    Application,
    AppRevision,
    Exposure,
    PortBinding,
    RevisionStatus,
    Service,
    ServiceRole,
    VolumeKind,
    VolumeMount,
)
from hivora.apps.ports import PortConflict, find_conflicts, used_ports
from hivora.compose_runner import ComposeError, ComposeRunner
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ValidationError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.jobs import Job, JobQueue
from hivora.state import StateStore
from hivora.templates.compiler import PortPlan
from hivora.templates.expressions import secret_env_name


class ComposeRejectedError(ValidationError):
    code = "compose_rejected"


@dataclass(frozen=True, slots=True)
class ComposePlan:
    app: Application
    compose_yaml: str
    diff: str
    problems: list[str]  # what forbids applying it (empty: fine)
    conflicts: list[PortConflict]
    services: list[Service]  # declared services, read from the resolved model


class ComposeEdit:
    def __init__(
        self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession],
        runner: ComposeRunner, state: StateStore, jobs: JobQueue, box: SecretBox,
        bus: EventBus, clock: Clock,
    ) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.runner = runner
        self.state = state
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock

    async def plan(self, session: AsyncSession, app_id: int, compose_yaml: str) -> ComposePlan:
        """Validate a hand-written compose file: resolved by Compose, then checked."""
        app = await get_app(session, app_id)
        secrets = await decrypt_secrets(session, self.box, app.id)
        env = {secret_env_name(k): v for k, v in secrets.items()}
        try:
            model = await self.runner.check(app.slug, compose_yaml, env)
        except ComposeError as exc:
            return ComposePlan(app, compose_yaml, "", [f"compose: {exc}"[:500]], [], [])
        roots = [self.settings.volumes_root / app.slug, self.runner.project_dir(app.slug),
                 self.runner.apps_dir / f".check-{app.slug}"]  # fmt: skip
        found = compose_problems(model, app.slug, roots)
        services = [] if found else _services_from_model(model)
        used = await used_ports(session, self.state, exclude_app=app.slug)
        conflicts = find_conflicts((
            PortPlan(sv.name, p.container_port, p.host_port, p.protocol, "other",
                     p.exposure.value, p.host_ip)
            for sv in services for p in sv.ports
        ), used)  # fmt: skip
        latest = await latest_revision(session, app.id)
        diff = "".join(difflib.unified_diff(
            (latest.compose_yaml if latest else "").splitlines(keepends=True),
            compose_yaml.splitlines(keepends=True),
            fromfile="current", tofile="edited",
        ))  # fmt: skip
        return ComposePlan(app, compose_yaml, diff, found, conflicts, services)

    async def apply(self, app_id: int, compose_yaml: str, *,
                    event: str = "app.compose_edited") -> Job:  # fmt: skip
        async with self.sessions() as session, session.begin():
            plan = await self.plan(session, app_id, compose_yaml)
            if plan.problems:
                raise ComposeRejectedError("this compose file cannot be applied",
                                           problems=plan.problems)  # fmt: skip
            if plan.conflicts:
                conflicts = [conflict_dict(c) for c in plan.conflicts]
                raise PortConflictError("host ports already in use", conflicts=conflicts)
            app = plan.app
            latest = await latest_revision(session, app.id)
            revision = AppRevision(
                app_id=app.id, number=(latest.number if latest else 0) + 1,
                inputs=dict(latest.inputs) if latest else {}, compose_yaml=compose_yaml,
                diff_from_previous=plan.diff, created_at=self.clock.now(),
                status=RevisionStatus.PENDING, custom_compose=True,
                template_version_id=latest.template_version_id if latest else None,
                overrides=latest.overrides if latest else None,
            )  # fmt: skip
            job = await queue_revision(session, self.jobs, app, revision, plan.services)
        self.jobs.wake()
        self.bus.publish(event, app=app.slug, revision=revision.number, job=job.id)
        return job


def _services_from_model(model: dict[str, Any]) -> list[Service]:
    """Services, ports and bind mounts of a resolved compose model (hand-written file)."""
    out: list[Service] = []
    for name, svc in (model.get("services") or {}).items():
        ports = []
        for p in svc.get("ports") or []:
            if not isinstance(p, dict) or not p.get("published"):
                continue
            ports.append(PortBinding(
                host_ip=p.get("host_ip") or None, host_port=int(str(p["published"]).split("-")[0]),
                container_port=int(p.get("target", 0)), protocol=p.get("protocol", "tcp"),
                purpose="other", exposure=Exposure.PUBLIC if not p.get("host_ip") else Exposure.LAN,
            ))  # fmt: skip
        volumes = [
            VolumeMount(kind=VolumeKind.BIND, source=str(v["source"]), target=str(v["target"]),
                        read_only=bool(v.get("read_only")), backup=True)
            for v in svc.get("volumes") or []
            if isinstance(v, dict) and v.get("type") == "bind" and v.get("source")
        ]  # fmt: skip
        out.append(Service(
            name=name, image=str(svc.get("image") or ""), role=ServiceRole.MAIN if not out
            else ServiceRole.SIDECAR, restart_policy=str(svc.get("restart") or "no"),
            ports=ports, volumes=volumes,
        ))  # fmt: skip
    return out
