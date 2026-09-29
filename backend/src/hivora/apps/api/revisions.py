"""Revision routes: settings, zone move, upgrade, restore. Each change is a new revision.

Two routers: in the public route order, the zone move sits between the lifecycle
actions and the removal routes, the other revision routes after them; that order is kept.
"""

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from hivora.apps.api.common import JobRef, PlanOut, job_ref, plan_out
from hivora.apps.core import latest_revision
from hivora.apps.service import UpdatePlan
from hivora.templates.overrides import Overrides
from hivora.templates.schema import Localized
from hivora.web.deps import Operator, RuntimeDep, Viewer

zone_router = APIRouter()
router = APIRouter()


class UpgradeOut(BaseModel):
    kind: Literal["template", "image"]
    current: str  # template version, or tag@digest for a free image
    latest: str
    available: bool


class ApplyIn(BaseModel):
    reset_data: bool = False  # confirms erasing the data when the change requires it


class SettingsOut(BaseModel):
    template: str
    version: str
    form: dict[str, Any]
    values: dict[str, Any]
    secrets_set: list[str]
    services: list[str]  # what advanced settings can target
    overrides: Overrides  # the advanced settings in force
    custom_compose: bool  # the compose was written by hand: saving the form replaces it


class SettingsIn(BaseModel):
    inputs: dict[str, Any] = {}
    reset_data: bool = False  # confirms a change that erases the app data
    overrides: Overrides | None = None  # None: keep the current advanced settings


class ResetOut(BaseModel):
    fields: list[str]
    labels: list[Localized]  # of those fields, in the applied template
    volumes: list[str]
    size: int


class UpdatePlanOut(PlanOut):
    revision: int
    diff: str
    reset: ResetOut | None  # set when applying erases the app data
    replaces_custom: bool = False  # the hand-written compose goes away


class ZoneIn(BaseModel):
    # Two models are named ZoneIn (here and in zones/api.py): their OpenAPI schemas are
    # then named after their module, fixed when the class is created. Keep the public
    # name it had before the route moved here (hivora__apps__api__ZoneIn): same contract.
    __module__ = "hivora.apps.api"

    zone: str | None  # zone slug; None: no zone


@zone_router.put("/{app_id}/zone", status_code=202)
async def move_zone(app_id: int, body: ZoneIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """New revision in the target zone (joins its network if it shares one)."""
    return job_ref(await rt.apps.move_zone(app_id, body.zone))


@router.get("/{app_id}/settings")
async def get_settings(app_id: int, _: Operator, rt: RuntimeDep) -> SettingsOut:
    async with rt.sessions() as session:
        st = await rt.apps.current_settings(session, app_id)
        latest = await latest_revision(session, app_id)
    t = st.entry.template
    return SettingsOut(template=st.entry.slug, version=t.metadata.version,
                       form=t.form.model_dump(by_alias=True, exclude_none=True),
                       values=st.values, secrets_set=st.secrets_set, services=list(t.services),
                       overrides=Overrides.model_validate(latest.overrides or {} if latest else {}),
                       custom_compose=bool(latest and latest.custom_compose))  # fmt: skip


def update_plan_out(upd: UpdatePlan) -> UpdatePlanOut:
    fields = {f.id: f.label for f in upd.plan.entry.template.form.fields}
    reset = (
        ResetOut(fields=upd.reset_fields, labels=[fields[f] for f in upd.reset_fields],
                 volumes=sorted(upd.reset_volumes), size=upd.reset_size)
        if upd.reset_fields else None
    )  # fmt: skip
    return UpdatePlanOut(**plan_out(upd.plan).model_dump(), revision=upd.number, diff=upd.diff,
                         reset=reset, replaces_custom=upd.replaces_custom)  # fmt: skip


@router.post("/{app_id}/settings/plan")
async def plan_settings(
    app_id: int, body: SettingsIn, _: Operator, rt: RuntimeDep
) -> UpdatePlanOut:
    """Preview: new compose and its diff against the current revision. Nothing is written."""
    async with rt.sessions() as session:
        return update_plan_out(
            await rt.apps.plan_update(session, app_id, body.inputs, overrides=body.overrides)
        )


@router.put("/{app_id}/settings", status_code=202)
async def update_settings(app_id: int, body: SettingsIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """New revision from these inputs, applied by a job (secrets left empty are kept)."""
    return job_ref(await rt.apps.update(app_id, body.inputs, reset_data=body.reset_data,
                                        overrides=body.overrides))  # fmt: skip


@router.get("/{app_id}/upgrade")
async def upgrade_status(app_id: int, _: Viewer, rt: RuntimeDep) -> UpgradeOut:
    """Newer template version, or newer image for a free image (asks its registry)."""
    async with rt.sessions() as session:
        st = await rt.apps.upgrade_status(session, app_id)
    return UpgradeOut(kind=st.kind, current=st.current, latest=st.latest, available=st.available)


@router.post("/{app_id}/upgrade/plan")
async def plan_upgrade(app_id: int, _: Operator, rt: RuntimeDep) -> UpdatePlanOut:
    async with rt.sessions() as session:
        return update_plan_out(await rt.apps.plan_upgrade(session, app_id))


@router.post("/{app_id}/upgrade", status_code=202)
async def upgrade(app_id: int, body: ApplyIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """Same settings, newest template (or image): a new revision."""
    return job_ref(await rt.apps.upgrade(app_id, reset_data=body.reset_data))


@router.post("/{app_id}/revisions/{number}/plan")
async def plan_restore(app_id: int, number: int, _: Operator, rt: RuntimeDep) -> UpdatePlanOut:
    async with rt.sessions() as session:
        return update_plan_out(await rt.apps.plan_restore(session, app_id, number))


@router.post("/{app_id}/revisions/{number}/restore", status_code=202)
async def restore(app_id: int, number: int, body: ApplyIn, _: Operator,
                  rt: RuntimeDep) -> JobRef:  # fmt: skip
    """A new revision with that revision's settings and template version."""
    return job_ref(await rt.apps.restore(app_id, number, reset_data=body.reset_data))
