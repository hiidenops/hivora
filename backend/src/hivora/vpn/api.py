"""VPN routes, mounted under /api/v1/apps: /{app_id}/vpn/..."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from hivora.vpn.service import VpnTools
from hivora.web.deps import Operator, RuntimeDep

router = APIRouter(tags=["vpn"])
IP_LIST = r"^[0-9a-fA-F.:/]{3,49}$"


class VpnClientOut(BaseModel):
    id: int
    name: str
    address: str | None
    enabled: bool
    allowed_ips: list[str] | None  # None: the VPN's default
    public_key: str | None
    latest_handshake: str | None
    rx: int
    tx: int


class VpnOut(BaseModel):
    running: bool
    subnet: str  # VPN network, e.g. 10.8.0.0/24
    server_address: str  # the WireGuard gateway
    default_allowed_ips: str  # traffic sent through the VPN when a client sets none
    clients: list[VpnClientOut]
    zones: list[str]  # zones whose networks the VPN reaches


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9 _.-]+$")
    allowed_ips: list[str] | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=45)  # None: next free address


class ClientUpdateIn(BaseModel):
    enabled: bool | None = None
    allowed_ips: list[str] | None = Field(default=None, max_length=32)
    clear_allowed_ips: bool = False  # back to the VPN's default
    address: str | None = Field(default=None, max_length=45)


class ZonesIn(BaseModel):
    zones: list[str] = Field(default=[], max_length=20)


class JobRefOut(BaseModel):
    id: int
    kind: str
    status: str


def _check_ips(ips: list[str] | None) -> None:
    import re

    from hivora.core.errors import ValidationError

    if ips and not all(re.match(IP_LIST, ip) for ip in ips):
        raise ValidationError("invalid allowed IPs", field="allowed_ips")


@router.get("/{app_id}/vpn")
async def overview(app_id: int, _: Operator, rt: RuntimeDep) -> VpnOut:
    return VpnOut(**await VpnTools(rt).overview(app_id))


@router.post("/{app_id}/vpn/clients", status_code=201)
async def create(app_id: int, body: ClientIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    _check_ips(body.allowed_ips)
    return {"id": await VpnTools(rt).create(app_id, body.name, body.allowed_ips, body.address)}


@router.put("/{app_id}/vpn/clients/{cid}", status_code=204)
async def update(app_id: int, cid: int, body: ClientUpdateIn, _: Operator, rt: RuntimeDep) -> None:
    _check_ips(body.allowed_ips)
    await VpnTools(rt).update(
        app_id, cid, enabled=body.enabled, allowed_ips=body.allowed_ips,
        clear_allowed=body.clear_allowed_ips, address=body.address,
    )  # fmt: skip


@router.delete("/{app_id}/vpn/clients/{cid}", status_code=204)
async def delete(app_id: int, cid: int, _: Operator, rt: RuntimeDep) -> None:
    await VpnTools(rt).delete(app_id, cid)


@router.post("/{app_id}/vpn/clients/{cid}/renew")
async def renew(app_id: int, cid: int, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    """New key pair (the client must import its new configuration)."""
    return {"id": await VpnTools(rt).renew(app_id, cid)}


@router.get("/{app_id}/vpn/clients/{cid}/config")
async def config(app_id: int, cid: int, _: Operator, rt: RuntimeDep) -> PlainTextResponse:
    text = await VpnTools(rt).configuration(app_id, cid)
    return PlainTextResponse(text, headers={
        "Content-Disposition": f'attachment; filename="wireguard-{cid}.conf"',
        "Cache-Control": "no-store",
    })  # fmt: skip


@router.get("/{app_id}/vpn/clients/{cid}/qrcode")
async def qrcode(app_id: int, cid: int, _: Operator, rt: RuntimeDep) -> Response:
    svg = await VpnTools(rt).qrcode(app_id, cid)
    return Response(svg, media_type="image/svg+xml", headers={
        "Content-Security-Policy": "sandbox", "Cache-Control": "no-store",
    })  # fmt: skip


@router.put("/{app_id}/vpn/zones", status_code=202)
async def zones(app_id: int, body: ZonesIn, _: Operator, rt: RuntimeDep) -> JobRefOut:
    """Join these zones' networks (new revision); clients then reach their apps."""
    job = await VpnTools(rt).set_zones(app_id, body.zones)
    return JobRefOut(id=job.id, kind=job.kind.value, status=job.status.value)
