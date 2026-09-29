"""The declared layer of the topology: what the user draws (nodes Docker cannot see,
links between any two nodes) and where the user put the nodes (positions, zone sizes)."""

from collections.abc import Mapping

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.errors import NotFoundError
from hivora.core.events import EventBus
from hivora.topology.models import TopologyEdge, TopologyLayout, TopologyNode

# x, y, and for zone boxes the size the user gave them (w, h)
Position = tuple[float, float, float | None, float | None]


class NodeNotFoundError(NotFoundError):
    code = "topology_node_not_found"


class DeclaredLayer:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], bus: EventBus) -> None:
        self.sessions = sessions
        self.bus = bus

    async def add_node(self, kind: str, label: str) -> int:
        async with self.sessions() as session, session.begin():
            node = TopologyNode(kind=kind, label=label)
            session.add(node)
            await session.flush()
            nid = node.id
        self.bus.publish("topology.node_added", target=label, kind=kind)
        return nid

    async def edit_node(self, node_id: int, kind: str, label: str) -> None:
        async with self.sessions() as session, session.begin():
            node = await session.get(TopologyNode, node_id)
            if node is None:
                raise NodeNotFoundError("unknown node", id=node_id)
            node.kind, node.label = kind, label

    async def remove_node(self, node_id: int) -> None:
        """The node, its links and its position."""
        key = f"decl:{node_id}"
        async with self.sessions() as session, session.begin():
            node = await session.get(TopologyNode, node_id)
            if node is None:
                raise NodeNotFoundError("unknown node", id=node_id)
            await session.delete(node)
            await session.execute(
                delete(TopologyEdge).where(
                    (TopologyEdge.source == key) | (TopologyEdge.target == key)
                )
            )
            await session.execute(delete(TopologyLayout).where(TopologyLayout.key == key))
        self.bus.publish("topology.node_removed", target=node.label)

    async def add_edge(self, source: str, target: str, label: str) -> int:
        async with self.sessions() as session, session.begin():
            edge = TopologyEdge(source=source, target=target, label=label)
            session.add(edge)
            await session.flush()
            eid = edge.id
        return eid

    async def remove_edge(self, edge_id: int) -> None:
        """No error for an unknown link: removing it again is a no-op."""
        async with self.sessions() as session, session.begin():
            await session.execute(delete(TopologyEdge).where(TopologyEdge.id == edge_id))

    async def save_layout(self, positions: Mapping[str, Position]) -> None:
        """Positions after a drag; an empty map resets to the automatic layout."""
        async with self.sessions() as session, session.begin():
            if not positions:
                await session.execute(delete(TopologyLayout))
            for key, (x, y, w, h) in positions.items():
                await session.merge(TopologyLayout(key=key[:40], x=x, y=y, w=w, h=h))
