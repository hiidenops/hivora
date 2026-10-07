"""Topology routes (/api/v1/topology): the graph, the declared layer, positions."""

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.topology.declared import DeclaredLayer
from hivora.topology.service import GraphBuilder
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["topology"])
KEY = r"^(internet|firewall|zone:(\d+|none)|app:\d+|decl:\d+)$"


class GraphOut(BaseModel):
    host: dict[str, Any]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    positions: dict[str, dict[str, float | None]]


class DeclaredIn(BaseModel):
    kind: Literal["firewall", "router", "vpn", "device", "note"]
    label: str = Field(min_length=1, max_length=120)


class EdgeIn(BaseModel):
    source: str = Field(pattern=KEY)
    target: str = Field(pattern=KEY)
    label: str = Field(default="", max_length=80)


class Position(BaseModel):
    x: float = Field(ge=-1e6, le=1e6)
    y: float = Field(ge=-1e6, le=1e6)
    w: float | None = Field(default=None, ge=40, le=1e5)  # zone boxes only
    h: float | None = Field(default=None, ge=40, le=1e5)


class LayoutIn(BaseModel):
    positions: dict[str, Position] = Field(max_length=2000)


def declared(rt: RuntimeDep) -> DeclaredLayer:
    return DeclaredLayer(rt.sessions, rt.bus)


@router.get("")
async def graph(_: Viewer, rt: RuntimeDep) -> GraphOut:
    g = await GraphBuilder(
        lan_ip=rt.settings.host_lan_ip, public_ip=rt.public_address.current,
        sessions=rt.sessions, catalog=rt.catalog, planner=rt.apps.planner, hostfw=rt.hostfw,
        store=rt.state.store, icons=rt.icons, adoption=rt.apps.adoption,
    ).build()  # fmt: skip
    return GraphOut(host=g.host, nodes=g.nodes, edges=g.edges, alerts=g.alerts,
                    positions=g.positions)  # fmt: skip


@router.post("/nodes", status_code=201)
async def add_node(body: DeclaredIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    return {"id": await declared(rt).add_node(body.kind, body.label)}


@router.put("/nodes/{node_id}", status_code=204)
async def edit_node(node_id: int, body: DeclaredIn, _: Operator, rt: RuntimeDep) -> None:
    await declared(rt).edit_node(node_id, body.kind, body.label)


@router.delete("/nodes/{node_id}", status_code=204)
async def remove_node(node_id: int, _: Operator, rt: RuntimeDep) -> None:
    await declared(rt).remove_node(node_id)


@router.post("/edges", status_code=201)
async def add_edge(body: EdgeIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    return {"id": await declared(rt).add_edge(body.source, body.target, body.label)}


@router.delete("/edges/{edge_id}", status_code=204)
async def remove_edge(edge_id: int, _: Operator, rt: RuntimeDep) -> None:
    await declared(rt).remove_edge(edge_id)


@router.put("/layout", status_code=204)
async def save_layout(body: LayoutIn, _: Operator, rt: RuntimeDep) -> None:
    """Positions after a drag; an empty map resets to the automatic layout."""
    positions = {key: (p.x, p.y, p.w, p.h) for key, p in body.positions.items()}
    await declared(rt).save_layout(positions)
