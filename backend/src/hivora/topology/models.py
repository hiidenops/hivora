"""The declared layer of the topology and the positions the user gave the nodes."""

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base


class TopologyNode(Base):
    """Something Docker cannot see, drawn by the user (dashed on the graph)."""

    __tablename__ = "topology_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # firewall, router, vpn, device, note
    label: Mapped[str] = mapped_column(String(120))


class TopologyEdge(Base):
    """A declared link between two nodes (observed or declared), by their keys."""

    __tablename__ = "topology_edge"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))  # e.g. "decl:3", "app:5", "zone:2"
    target: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80), default="")


class TopologyLayout(Base):
    """Where the user put a node (absolute graph coordinates)."""

    __tablename__ = "topology_layout"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float | None] = mapped_column(Float)  # zones the user resized
    h: Mapped[float | None] = mapped_column(Float)
