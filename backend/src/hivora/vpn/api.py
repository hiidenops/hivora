"""VPN routes, mounted under /api/v1/apps: /{app_id}/vpn/..."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from hivora.vpn.service import VpnTools
from hivora.web.deps import Operator, RuntimeDep

router = APIRouter(tags=["vpn"])
IP_LIST = r"^[0-9a-fA-F.:/]{3,49}$"


class AccessIO(BaseModel):
    """What the client may reach, enforced by the server whatever its configuration."""

    internet: bool = True
    lan: bool = True  # private networks: the LAN, the host, the VPN itself
    zones: list[str] = Field(default=[], max_length=50)  # among the zones the VPN reaches


Routing = Literal["default", "all", "access", "custom"]
NAME = r"^[A-Za-z0-9 _.-]+$"


class VpnClientOut(BaseModel):
    id: int
    name: str
    address: str | None
    enabled: bool  # wanted
    active: bool  # enabled and not expired
    expires_at: datetime | None
    access: AccessIO
    routing: Routing
    allowed_ips: list[str] | None  # routing "custom"
    public_key: str | None
    latest_handshake: str | None
    online: bool  # handshake in the last 3 minutes
    endpoint: str | None  # where the client connects from
    rx: int
    tx: int


class VpnOut(BaseModel):
    running: bool
    subnet: str  # VPN network, e.g. 10.8.0.0/24
    server_address: str  # the WireGuard gateway
    default_allowed_ips: str  # traffic sent through the VPN with routing "default"
    clients: list[VpnClientOut]
    zones: list[str]  # zones whose networks the VPN reaches


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=32, pattern=NAME)
    allowed_ips: list[str] | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=45)  # None: next free address
    access: AccessIO | None = None  # None: everything
    routing: Routing = "default"
    expires_at: datetime | None = None


class ClientUpdateIn(BaseModel):
    """Only the fields sent change."""

    name: str | None = Field(default=None, min_length=1, max_length=32, pattern=NAME)
    enabled: bool | None = None
    allowed_ips: list[str] | None = Field(default=None, max_length=32)
    clear_allowed_ips: bool = False  # back to the VPN's default
    address: str | None = Field(default=None, max_length=45)
    access: AccessIO | None = None  # null: everything
    routing: Routing | None = None
    expires_at: datetime | None = None  # null: never


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
    extra = body.model_dump(include={"access", "routing", "expires_at"}, exclude_unset=True)
    return {"id": await VpnTools(rt).create(app_id, body.name, body.allowed_ips, body.address,
                                            **extra)}  # fmt: skip


@router.put("/{app_id}/vpn/clients/{cid}", status_code=204)
async def update(app_id: int, cid: int, body: ClientUpdateIn, _: Operator, rt: RuntimeDep) -> None:
    _check_ips(body.allowed_ips)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)
    if changes.get("routing") is None:
        changes.pop("routing", None)
    await VpnTools(rt).update(app_id, cid, **changes)


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
