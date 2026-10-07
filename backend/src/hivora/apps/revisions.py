"""Revisions of an app: settings changes, upgrades to a newer template or image, restores
of an earlier revision, zone moves. Each one is a new revision applied by a job."""

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.compose_edit import ComposeEdit
from hivora.apps.core import (
    PortConflictError,
    conflict_dict,
    decrypt_secrets,
    get_app,
    latest_revision,
    queue_revision,
    store_secrets,
)
from hivora.apps.custom_images import CustomImages
from hivora.apps.models import Application, AppRevision, AppSecret, RevisionStatus
from hivora.apps.planner import AppPlanner, DeployPlan, services_from
from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.core.fs import tree_size
from hivora.crypto.cipher import SecretBox
from hivora.jobs import Job, JobQueue
from hivora.templates import Catalog, CatalogEntry
from hivora.templates.catalog import CUSTOM_SOURCE, TemplateInvalidError, parse_template
from hivora.templates.models import TemplateVersion
from hivora.templates.overrides import Overrides
from hivora.zones import Zone, get_zone


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    plan: DeployPlan
    number: int  # the revision this change would create
    diff: str  # unified diff against the latest revision's compose
    # Fields flagged `reset_data_on_change` whose value changed: applying wipes
    # the volumes below (host path -> top-level names kept), after confirmation.
    reset_fields: list[str] = field(default_factory=list)
    reset_volumes: dict[str, list[str]] = field(default_factory=dict)
    reset_size: int = 0  # bytes currently stored in those volumes
    replaces_custom: bool = False  # the current compose was written by hand: it goes away


class DataResetRequiredError(ConflictError):
    code = "data_reset_required"


class RevisionNotRestorableError(ConflictError):
    code = "revision_not_restorable"


@dataclass(frozen=True, slots=True)
class UpgradeStatus:
    kind: Literal["template", "image"]  # newer template version / newer free-image digest
    current: str
    latest: str
    available: bool


class Revisions:
    def __init__(
        self, *, planner: AppPlanner, sessions: async_sessionmaker[AsyncSession],
        catalog: Catalog, jobs: JobQueue, box: SecretBox, bus: EventBus, clock: Clock,
        custom: CustomImages, compose: ComposeEdit,
    ) -> None:  # fmt: skip
        self.planner = planner
        self.sessions = sessions
        self.catalog = catalog
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock
        self.custom = custom
        self.compose = compose

    async def plan_update(
        self, session: AsyncSession, app_id: int, inputs: dict[str, Any],
        entry: CatalogEntry | None = None, overrides: Overrides | None = None,
    ) -> UpdatePlan:  # fmt: skip
        """Preview a settings change: new compose, its diff, port conflicts.

        Secret fields left empty keep their current value. ``entry``: another
        template version (upgrade, restore); default: the catalog's.
        """
        app = await get_app(session, app_id)
        entry = entry or await self.planner.entry_of(session, app)
        current = await decrypt_secrets(session, self.box, app.id)
        fields = {f.id for f in entry.template.form.fields}
        kept = {k: v for k, v in current.items() if not inputs.get(k) and k in fields}
        latest = await latest_revision(session, app.id)
        number = (latest.number if latest else 0) + 1
        zone = await session.get(Zone, app.zone_id) if app.zone_id else None
        if overrides is None:  # unchanged: the latest revision's advanced settings
            overrides = Overrides.model_validate(latest.overrides or {}) if latest else None
        plan = await self.planner.plan(session, entry, app.slug, app.name, zone, {**inputs, **kept},
                                revision=number, overrides=overrides)  # fmt: skip
        previous = latest.compose_yaml if latest else ""
        new = plan.compiled.compose_yaml
        diff = "".join(difflib.unified_diff(
            previous.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"revision {number - 1}", tofile=f"revision {number}",
        ))  # fmt: skip
        # Compare with the revision the data was produced by (the applied one),
        # not a failed attempt after it.
        applied = (
            await session.get(AppRevision, app.current_revision_id)
            if app.current_revision_id else latest
        )  # fmt: skip
        before = dict(applied.inputs) if applied else {}
        reset_fields = [
            f.id for f in entry.template.form.fields
            if f.reset_data_on_change and f.id in before
            and before[f.id] != plan.form.values.get(f.id)
        ]  # fmt: skip
        custom = bool(latest and latest.custom_compose)
        if not reset_fields:
            return UpdatePlan(plan, number, diff, replaces_custom=custom)
        # The template's volumes only: extra folders (advanced settings) are the user's own.
        keep = {(n, v.name): v.reset_keep for n, sp in entry.template.services.items()
                for v in sp.volumes}  # fmt: skip
        reset_volumes = {
            str(v.source): keep[(v.service, v.name)]
            for svc in plan.compiled.services for v in svc.volumes
            if not v.read_only and (v.service, v.name) in keep
        }  # fmt: skip
        size = sum(tree_size(Path(p)) for p in reset_volumes)
        return UpdatePlan(plan, number, diff, reset_fields, reset_volumes, size,
                          replaces_custom=custom)  # fmt: skip

    async def update(
        self, app_id: int, inputs: dict[str, Any], *, reset_data: bool = False,
        entry: CatalogEntry | None = None, event: str = "app.updated",
        overrides: Overrides | None = None,
    ) -> Job:  # fmt: skip
        async with self.sessions() as session, session.begin():
            job, number = await self.queue_update(session, app_id, inputs, reset_data=reset_data,
                                                  entry=entry, overrides=overrides)  # fmt: skip
        self.jobs.wake()
        self.bus.publish(event, app=job.app_slug, revision=number, job=job.id)
        return job

    async def queue_update(
        self, session: AsyncSession, app_id: int, inputs: dict[str, Any], *,
        reset_data: bool = False, entry: CatalogEntry | None = None,
        overrides: Overrides | None = None,
    ) -> tuple[Job, int]:  # fmt: skip
        """The new revision and its job, in the caller's transaction (not yet woken)."""
        upd = await self.plan_update(session, app_id, inputs, entry, overrides)
        plan = upd.plan
        if upd.reset_fields and not reset_data:
            raise DataResetRequiredError(
                "this change erases the app data and must be confirmed",
                fields=upd.reset_fields,
            )
        if plan.conflicts:
            raise PortConflictError(
                "host ports already in use",
                conflicts=[conflict_dict(c) for c in plan.conflicts],
            )
        app = await get_app(session, app_id)
        version = await self.planner.template_version(session, plan.entry)
        app.template_version_id = version.id
        await session.execute(delete(AppSecret).where(AppSecret.app_id == app.id))
        store_secrets(session, self.box, app.id, plan.form.secrets)
        revision = AppRevision(
            app_id=app.id, number=upd.number, inputs=plan.form.values,
            compose_yaml=plan.compiled.compose_yaml, diff_from_previous=upd.diff,
            template_version_id=version.id,
            overrides=plan.overrides.model_dump(exclude_defaults=True) or None,
            created_at=self.clock.now(), status=RevisionStatus.PENDING,
        )  # fmt: skip
        job = await queue_revision(
            session, self.jobs, app, revision, services_from(plan.compiled),
            {"reset_volumes": upd.reset_volumes} if upd.reset_fields else None,
        )  # fmt: skip
        return job, upd.number

    async def upgrade_status(self, session: AsyncSession, app_id: int) -> UpgradeStatus:
        """Is a newer template version (or, for a free image, a newer image) available?"""
        app = await get_app(session, app_id)
        current = await session.get(TemplateVersion, app.template_version_id)
        entry = await self.planner.entry_of(session, app)
        if current is None:  # pragma: no cover - every template app has one
            raise ConflictError("this app has no template version", slug=app.slug)
        if entry.source != CUSTOM_SOURCE:
            latest = entry.template.metadata.version
            return UpgradeStatus("template", current.version, latest, latest != current.version)
        return UpgradeStatus("image", *await self.custom.image_status(entry))

    async def _upgrade_entry(self, session: AsyncSession, app: Application) -> CatalogEntry:
        """The entry an upgrade applies: the catalog's, or the free image re-pinned."""
        entry = await self.planner.entry_of(session, app)
        return entry if entry.source != CUSTOM_SOURCE else await self.custom.repin(entry)

    async def plan_upgrade(self, session: AsyncSession, app_id: int) -> UpdatePlan:
        app = await get_app(session, app_id)
        entry = await self._upgrade_entry(session, app)
        values = (await self.planner.current_settings(session, app_id)).values
        return await self.plan_update(session, app_id, values, entry)

    async def upgrade(self, app_id: int, *, reset_data: bool = False) -> Job:
        async with self.sessions() as session:
            app = await get_app(session, app_id)
            entry = await self._upgrade_entry(session, app)
            values = (await self.planner.current_settings(session, app_id)).values
        job = await self.update(app_id, values, reset_data=reset_data, entry=entry,
                                event="app.upgraded")  # fmt: skip
        if entry.source == CUSTOM_SOURCE:
            self.catalog.add_custom(entry.manifest)  # the new pin becomes the app's template
        return job

    async def _revision_entry(self, session: AsyncSession, app_id: int,
                              number: int) -> tuple[AppRevision, CatalogEntry]:  # fmt: skip
        rev = await session.scalar(
            select(AppRevision).where(AppRevision.app_id == app_id, AppRevision.number == number)
        )
        if rev is None:
            raise NotFoundError("no such revision", revision=number)
        if rev.template_version_id is None:
            raise RevisionNotRestorableError("this revision predates restore support",
                                             revision=number)  # fmt: skip
        tv = await session.get_one(TemplateVersion, rev.template_version_id)
        try:
            template = parse_template(tv.manifest, require_pinned=False)
        except TemplateInvalidError as exc:
            raise RevisionNotRestorableError("its template no longer loads",
                                             revision=number) from exc  # fmt: skip
        return rev, CatalogEntry(template, tv.manifest, tv.checksum, tv.source)

    async def plan_restore(self, session: AsyncSession, app_id: int, number: int) -> UpdatePlan:
        rev, entry = await self._revision_entry(session, app_id, number)
        return await self.plan_update(session, app_id, dict(rev.inputs), entry,
                                      Overrides.model_validate(rev.overrides or {}))  # fmt: skip

    async def restore(self, app_id: int, number: int, *, reset_data: bool = False) -> Job:
        """A new revision with the settings and template version of revision ``number``."""
        async with self.sessions() as session:
            rev, entry = await self._revision_entry(session, app_id, number)
            inputs, overrides = dict(rev.inputs), Overrides.model_validate(rev.overrides or {})
            custom = rev.compose_yaml if rev.custom_compose else None
        if custom is not None:  # a hand-written compose comes back as it was
            return await self.compose.apply(app_id, custom, event="app.restored")
        job = await self.update(app_id, inputs, reset_data=reset_data, entry=entry,
                                event="app.restored", overrides=overrides)  # fmt: skip
        if entry.source == CUSTOM_SOURCE:
            self.catalog.add_custom(entry.manifest)  # that pin is the app's template again
        return job

    async def move_zone(self, app_id: int, zone_slug: str | None) -> Job:
        """Put the app in another zone (or none): a new revision joins the zone's network."""
        async with self.sessions() as session, session.begin():
            app = await get_app(session, app_id)
            zone = await get_zone(session, zone_slug) if zone_slug else None
            app.zone_id = zone.id if zone else None
        async with self.sessions() as session:
            values = (await self.planner.current_settings(session, app_id)).values
        job = await self.update(app_id, values)
        self.bus.publish("app.zone_changed", app=app.slug, zone=zone_slug)
        return job

    async def redeploy_zone(self, zone_id: int) -> list[Job]:
        """A zone's network changed: every app in it gets a new revision."""
        async with self.sessions() as session:
            ids = list(
                await session.scalars(select(Application.id).where(Application.zone_id == zone_id))
            )
        jobs = []
        for app_id in ids:
            async with self.sessions() as session:
                values = (await self.planner.current_settings(session, app_id)).values
            jobs.append(await self.update(app_id, values))
        return jobs
