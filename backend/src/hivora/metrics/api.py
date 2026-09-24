"""Metrics routes (/api/v1/metrics)."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from hivora.web.deps import RuntimeDep, Viewer

router = APIRouter(tags=["metrics"])


class HostSampleOut(BaseModel):
    ts: float
    cpu_percent: float
    mem_used: int
    mem_total: int
    net_rx_bps: float
    net_tx_bps: float


@router.get("/host")
async def host_history(_: Viewer, rt: RuntimeDep) -> list[HostSampleOut]:
    return [HostSampleOut(**asdict(s)) for s in rt.metrics.samples]
