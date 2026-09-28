"""Topology routes (/api/v1/topology): the graph, the declared layer, positions."""

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete

from hivora.core.errors import NotFoundError
from hivora.topology.models import TopologyEdge, TopologyLayout, TopologyNode
from hivora.topology.service import build
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["topology"])
KEY = r"^(internet|zone:(\d+|none)|app:\d+|decl:\d+)$"


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


class NodeNotFoundError(NotFoundError):
    code = "topology_node_not_found"


@router.get("")
async def graph(_: Viewer, rt: RuntimeDep) -> GraphOut:
    g = await build(rt)
    return GraphOut(host=g.host, nodes=g.nodes, edges=g.edges, alerts=g.alerts,
                    positions=g.positions)  # fmt: skip


@router.post("/nodes", status_code=201)
async def add_node(body: DeclaredIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    async with rt.sessions() as session, session.begin():
        node = TopologyNode(kind=body.kind, label=body.label)
        session.add(node)
        await session.flush()
        nid = node.id
    rt.bus.publish("topology.node_added", target=body.label, kind=body.kind)
    return {"id": nid}


@router.put("/nodes/{node_id}", status_code=204)
async def edit_node(node_id: int, body: DeclaredIn, _: Operator, rt: RuntimeDep) -> None:
    async with rt.sessions() as session, session.begin():
        node = await session.get(TopologyNode, node_id)
        if node is None:
            raise NodeNotFoundError("unknown node", id=node_id)
        node.kind, node.label = body.kind, body.label


@router.delete("/nodes/{node_id}", status_code=204)
async def remove_node(node_id: int, _: Operator, rt: RuntimeDep) -> None:
    key = f"decl:{node_id}"
    async with rt.sessions() as session, session.begin():
        node = await session.get(TopologyNode, node_id)
        if node is None:
            raise NodeNotFoundError("unknown node", id=node_id)
        await session.delete(node)
        await session.execute(
            delete(TopologyEdge).where((TopologyEdge.source == key) | (TopologyEdge.target == key))
        )
        await session.execute(delete(TopologyLayout).where(TopologyLayout.key == key))
    rt.bus.publish("topology.node_removed", target=node.label)


@router.post("/edges", status_code=201)
async def add_edge(body: EdgeIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    async with rt.sessions() as session, session.begin():
        edge = TopologyEdge(source=body.source, target=body.target, label=body.label)
        session.add(edge)
        await session.flush()
        eid = edge.id
    return {"id": eid}


@router.delete("/edges/{edge_id}", status_code=204)
async def remove_edge(edge_id: int, _: Operator, rt: RuntimeDep) -> None:
    async with rt.sessions() as session, session.begin():
        await session.execute(delete(TopologyEdge).where(TopologyEdge.id == edge_id))


@router.put("/layout", status_code=204)
async def save_layout(body: LayoutIn, _: Operator, rt: RuntimeDep) -> None:
    """Positions after a drag; an empty map resets to the automatic layout."""
    async with rt.sessions() as session, session.begin():
        if not body.positions:
            await session.execute(delete(TopologyLayout))
        for key, pos in body.positions.items():
            await session.merge(TopologyLayout(key=key[:40], x=pos.x, y=pos.y, w=pos.w, h=pos.h))
