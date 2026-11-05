"""Addressing routes (/api/v1/addressing): the plan and what Docker applied; changes to
a zone's subnet, a service's address, the Hivora range, each applied by redeploy jobs."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.addressing.service import AppRef, zone_network_name
from hivora.apps.api.common import JobRef, job_ref
from hivora.apps.core import get_app
from hivora.apps.models import Application, AppRevision, Origin
from hivora.core.errors import ConflictError
from hivora.runtime import Runtime
from hivora.web.deps import Admin, Operator, RuntimeDep, Viewer, client_ip
from hivora.zones import get_zone

router = APIRouter(tags=["addressing"])


class ZoneSubnetFixedError(ConflictError):
    code = "zone_subnet_fixed"


class RowOut(BaseModel):
    app_id: int | None
    app: str
    name: str
    service: str
    network: str
    planned: str
    actual: str | None
    manual: bool
    state: str  # ok, drift (Docker gave another one), pending (not applied yet)


class OwnRowOut(RowOut):
    subnet: str
    actual_subnets: list[str]


class AppNetworkOut(BaseModel):
    app: str
    name: str
    subnet: str


class ZonePlanOut(BaseModel):
    slug: str
    name: str
    color: str
    subnet: str | None
    network: str | None  # its shared network; None: each app has its own /28 in it
    mode: str
    origin: str  # range, vpn (next to the VPN's), manual, system (Administration)
    vpn: str | None
    actual_subnets: list[str]
    size: int
    used: int
    app_networks: list[AppNetworkOut]
    rows: list[RowOut]


class ExcludedOut(BaseModel):
    network: str
    owner: str  # host:<dev>, docker:<network>, vpn:<app>, zone:administration...


class AddressingOut(BaseModel):
    range: str
    zones_block: str
    apps_block: str
    excluded: list[ExcludedOut]
    zones: list[ZonePlanOut]
    app_networks: list[OwnRowOut]


class ChangeOut(BaseModel):
    """A change, previewed (``dry_run``) or applied: what it gives and what it redeploys."""

    value: str | None
    apps: list[str]  # names of the apps redeployed to apply it
    commands: list[str]  # the Docker equivalent
    diff: str = ""  # compose diff (an app's address)
    vpn: str | None = None  # a VPN reaches the zone: its clients' routes change
    jobs: list[JobRef] = Field(default_factory=list)


class ZoneSubnetIn(BaseModel):
    subnet: str | None = Field(default=None, max_length=18)  # None: automatic again
    dry_run: bool = False


class AppIpIn(BaseModel):
    service: str = Field(max_length=63)
    network: str = Field(max_length=128)
    address: str | None = Field(default=None, max_length=15)  # None: automatic again
    dry_run: bool = False


class RangeIn(BaseModel):
    range: str = Field(max_length=18)
    dry_run: bool = False


async def _apps(session: AsyncSession) -> list[Application]:
    return list(await session.scalars(select(Application).order_by(Application.name)))


def _redeployable(apps: list[Application], slugs: set[str] | None = None) -> list[Application]:
    """Apps a new revision can be made for (from a template, already deployed)."""
    return [a for a in apps if a.origin is Origin.TEMPLATE and a.current_revision_id
            and (slugs is None or a.slug in slugs)]  # fmt: skip


async def _apply(rt: Runtime, apps: list[Application]) -> list[JobRef]:
    return [job_ref(j) for j in await rt.apps.revisions.redeploy([a.id for a in apps])]


@router.get("")
async def overview(_: Viewer, rt: RuntimeDep) -> AddressingOut:
    async with rt.sessions() as session, session.begin():  # the range may be picked now
        apps = [AppRef(a.id, a.slug, a.name, a.zone_id) for a in await _apps(session)]
        vpns = {z: name for z, (_, name) in (await rt.apps.planner.vpn_zones(session)).items()}
        data = await rt.addressing.overview(session, apps, rt.state.store.containers(), vpns)
    return AddressingOut.model_validate(data)


@router.put("/zones/{slug}")
async def zone_subnet(slug: str, body: ZoneSubnetIn, _: Operator, rt: RuntimeDep) -> ChangeOut:
    """A zone's subnet chosen by hand (or automatic again): its apps and the ones joining
    its network (VPN, HTTPS proxy) are redeployed on it."""
    async with rt.sessions() as session:
        zone = await get_zone(session, slug)
        if zone.is_system:
            raise ZoneSubnetFixedError("the Administration zone's network is the installer's",
                                       zone=slug)  # fmt: skip
        subnet = await rt.addressing.set_zone_subnet(session, zone, body.subnet)
        network = zone_network_name(zone)
        joining = set(await rt.addressing.joiners(session, network))
        apps = await _apps(session)
        touched = _redeployable(apps, joining | {a.slug for a in apps if a.zone_id == zone.id})
        vpn = (await rt.apps.planner.vpn_zones(session)).get(slug)
        out = ChangeOut(value=subnet, apps=[a.name for a in touched],
                        commands=[f"docker network rm {network}",
                                  f"docker network create --subnet {subnet} {network}"],
                        vpn=vpn[1] if vpn else None)  # fmt: skip
        if body.dry_run:
            await session.rollback()
            return out
        await session.commit()
    out.jobs = await _apply(rt, touched)
    rt.bus.publish(
        "addressing.zone_subnet", target=slug, subnet=subnet, manual=body.subnet is not None
    )
    return out


@router.put("/apps/{app_id}/ip")
async def app_ip(app_id: int, body: AppIpIn, _: Operator, rt: RuntimeDep) -> ChangeOut:
    """A service's address chosen by hand in one of its networks (or automatic again)."""
    async with rt.sessions() as session:
        app = await get_app(session, app_id)
        address = await rt.addressing.set_ip(session, app.slug, body.service, body.network,
                                             body.address)  # fmt: skip
        values = (await rt.apps.planner.current_settings(session, app_id)).values
        diff = (await rt.apps.revisions.plan_update(session, app_id, values)).diff
        out = ChangeOut(value=address, apps=[app.name], diff=diff, commands=[])
        if body.dry_run:
            await session.rollback()
            return out
        await session.commit()
    out.jobs = await _apply(rt, _redeployable([app]))
    rt.bus.publish("addressing.app_ip", target=app.slug, service=body.service,
                   network=body.network, address=address)  # fmt: skip
    return out


@router.put("/range")
async def hivora_range(body: RangeIn, request: Request, _: Admin, rt: RuntimeDep) -> ChangeOut:
    """A new Hivora range: zones and apps' networks taken from the old one move to it;
    every app is redeployed."""
    async with rt.sessions() as session:
        chosen = await rt.addressing.set_range(session, body.range, client_ip(request))
        touched = _redeployable(await _apps(session))
        out = ChangeOut(value=chosen, apps=[a.name for a in touched], commands=[])
        if body.dry_run:
            await session.rollback()
            return out
        await session.commit()
    out.jobs = await _apply(rt, touched)
    rt.bus.publish("addressing.range", target=chosen)
    return out


@router.post("/apply")
async def apply_plan(_: Operator, rt: RuntimeDep) -> ChangeOut:
    """Redeploys the apps whose applied compose differs from the plan (apps from before
    static addressing, or after a change made while they were stopped)."""
    async with rt.sessions() as session:
        apps = _redeployable(await _apps(session))
        composes = {}
        for a in apps:
            revision = await session.get(AppRevision, a.current_revision_id)
            composes[a.slug] = revision.compose_yaml if revision else ""
        stale = set(await rt.addressing.stale(session, composes))
    touched = [a for a in apps if a.slug in stale]
    out = ChangeOut(value=None, apps=[a.name for a in touched], commands=[])
    out.jobs = await _apply(rt, touched)
    if touched:
        rt.bus.publish("addressing.applied", apps=len(touched))
    return out
