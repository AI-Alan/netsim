"""
Topology-only REST: broadcast / collision domain counts (CCNA-style rules in simulation.topology_runtime).
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from simulation.topology_runtime import build_graph, domain_stats

router = APIRouter(prefix="/api/topology", tags=["topology"])


class TopologyDomainStatsBody(BaseModel):
    topology_devices: List[Dict[str, Any]] = Field(default_factory=list)
    topology_links: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/domain-stats")
def post_domain_stats(body: TopologyDomainStatsBody) -> Dict[str, Any]:
    graph = build_graph(body.topology_devices or [], body.topology_links or [])
    stats = domain_stats(graph)
    return {"status": "ok", **stats}
