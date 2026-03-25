"""POST /api/topology/domain-stats handler matches simulation.topology_runtime.domain_stats."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.topology_domain import TopologyDomainStatsBody, post_domain_stats
from simulation.topology_runtime import build_graph, domain_stats


def test_domain_stats_star_switch():
    devices = [
        {"id": "sw", "type": "switch", "label": "s", "mac": "00:00:00:00:00:01", "ip": "10.0.0.1"},
        {"id": "h1", "type": "end_host", "label": "a", "mac": "00:00:00:00:00:02", "ip": "10.0.0.2"},
        {"id": "h2", "type": "end_host", "label": "b", "mac": "00:00:00:00:00:03", "ip": "10.0.0.3"},
    ]
    links = [
        {"id": "l1", "src": "h1", "dst": "sw", "medium": "wired"},
        {"id": "l2", "src": "h2", "dst": "sw", "medium": "wired"},
    ]
    body = post_domain_stats(TopologyDomainStatsBody(topology_devices=devices, topology_links=links))
    g = build_graph(devices, links)
    expected = domain_stats(g)
    assert body["broadcast_domains"] == expected["broadcast_domains"]
    assert body["collision_domains"] == expected["collision_domains"]
    assert body["status"] == "ok"


def test_domain_stats_empty():
    body = post_domain_stats(TopologyDomainStatsBody())
    assert body == {"status": "ok", "broadcast_domains": 0, "collision_domains": 0}
