"""
simulation/topology_runtime.py
------------------------------
Composition-first topology runtime for L2 forwarding behavior.

This models a network as DeviceNode + Port + ForwardingPlane roles.
Switch learning table persists via caller-provided session_state.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from hashlib import sha1
import json
from typing import Any, Dict, List, Optional, Tuple

from layers.base import LayerPDU
from layers.datalink.factory import DataLinkLayerFactory
from simulation.events import EventType, LayerName, PDU, SimEvent


def topology_fingerprint(devices: List[Dict[str, Any]], links: List[Dict[str, Any]]) -> str:
    payload = {
        "devices": sorted(
            [{"id": str(d.get("id", "")), "type": str(d.get("type", ""))} for d in devices],
            key=lambda x: x["id"],
        ),
        "links": sorted(
            [{
                "src": min(str(l.get("src", "")), str(l.get("dst", ""))),
                "dst": max(str(l.get("src", "")), str(l.get("dst", ""))),
                "medium": str(l.get("medium", "wired")),
            } for l in links],
            key=lambda x: (x["src"], x["dst"], x["medium"]),
        ),
    }
    return sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Port:
    port_id: str
    neighbor_id: str
    medium: str = "wired"


@dataclass
class DeviceNode:
    device_id: str
    device_type: str
    mac: str
    ports: List[Port] = field(default_factory=list)


class ForwardingPlane:
    def forward(
        self,
        node: DeviceNode,
        ingress_port: Optional[str],
        dst_mac: str,
        dst_device: str,
        graph: dict[str, DeviceNode],
        switch_table: dict[str, str],
    ) -> tuple[List[Port], dict[str, Any]]:
        raise NotImplementedError


class HostRole(ForwardingPlane):
    @staticmethod
    def _route_next_hop(src: str, dst: str, graph: dict[str, DeviceNode], blocked_neighbor: Optional[str]) -> Optional[str]:
        q: deque[str] = deque([src])
        parent: dict[str, Optional[str]] = {src: None}
        while q:
            cur = q.popleft()
            if cur == dst:
                break
            for p in graph[cur].ports:
                nxt = p.neighbor_id
                if cur == src and blocked_neighbor and nxt == blocked_neighbor:
                    continue
                if nxt in parent:
                    continue
                parent[nxt] = cur
                q.append(nxt)
        if dst not in parent:
            return None
        step = dst
        while parent.get(step) != src:
            step = parent[step]  # type: ignore[index]
            if step is None:
                return None
        return step

    def forward(
        self,
        node: DeviceNode,
        ingress_port: Optional[str],
        dst_mac: str,
        dst_device: str,
        graph: dict[str, DeviceNode],
        switch_table: dict[str, str],
    ) -> tuple[List[Port], dict[str, Any]]:
        blocked = None
        if ingress_port:
            blocked = next((p.neighbor_id for p in node.ports if p.port_id == ingress_port), None)
        next_hop = self._route_next_hop(node.device_id, dst_device, graph, blocked_neighbor=blocked)
        if not next_hop:
            return [], {"mode": "drop", "detail": "No forward path from this node."}
        out = [p for p in node.ports if p.neighbor_id == next_hop]
        return out, {"mode": "route", "detail": "Forward on shortest path."}


class HubRole(ForwardingPlane):
    def forward(
        self,
        node: DeviceNode,
        ingress_port: Optional[str],
        dst_mac: str,
        dst_device: str,
        graph: dict[str, DeviceNode],
        switch_table: dict[str, str],
    ) -> tuple[List[Port], dict[str, Any]]:
        out = [p for p in node.ports if p.port_id != ingress_port]
        return out, {"mode": "flood", "detail": "Hub repeats frame to all ports except ingress."}


class SwitchRole(ForwardingPlane):
    def forward(
        self,
        node: DeviceNode,
        ingress_port: Optional[str],
        dst_mac: str,
        dst_device: str,
        graph: dict[str, DeviceNode],
        switch_table: dict[str, str],
    ) -> tuple[List[Port], dict[str, Any]]:
        learned = None
        src_mac = switch_table.get("__current_src_mac__", "")
        if ingress_port and src_mac:
            switch_table[src_mac] = ingress_port
            learned = {"mac": src_mac, "port": ingress_port}

        broadcast = dst_mac == "ff:ff:ff:ff:ff:ff"
        known_port = switch_table.get(dst_mac)
        if broadcast:
            out = [p for p in node.ports if p.port_id != ingress_port]
            return out, {"mode": "flood", "detail": "Switch flood (broadcast).", "learned": learned}
        if known_port:
            out = [p for p in node.ports if p.port_id == known_port and p.port_id != ingress_port]
            return out, {"mode": "unicast", "detail": "Switch unicast forward (MAC hit).", "learned": learned}
        out = [p for p in node.ports if p.port_id != ingress_port]
        return out, {"mode": "flood", "detail": "Switch flood (unknown destination MAC).", "learned": learned}


ROLE_MAP: dict[str, ForwardingPlane] = {
    "host": HostRole(),
    "switch": SwitchRole(),
    "hub": HubRole(),
    "router": HostRole(),   # stub for now
    "computer": HostRole(),
    "server": HostRole(),
    "laptop": HostRole(),
    "end_host": HostRole(),
}


def _emit_engine(collected: List[SimEvent], ts: float, src: str, detail: str, dst: Optional[str] = None, **headers: Any) -> None:
    collected.append(SimEvent(
        timestamp=ts,
        event_type=EventType.SESSION_INFO,
        layer=LayerName.ENGINE,
        src_device=src,
        dst_device=dst,
        pdu=PDU(type="topology", headers={"detail": detail, **headers}),
    ))


def build_graph(devices: List[Dict[str, Any]], links: List[Dict[str, Any]]) -> dict[str, DeviceNode]:
    graph: dict[str, DeviceNode] = {}
    for d in devices:
        did = str(d.get("id", ""))
        if not did:
            continue
        graph[did] = DeviceNode(
            device_id=did,
            device_type=str(d.get("type", "host")),
            mac=str(d.get("mac", "00:00:00:00:00:00")).lower(),
            ports=[],
        )
    port_seq: dict[str, int] = defaultdict(int)
    for l in links:
        a = str(l.get("src", ""))
        b = str(l.get("dst", ""))
        m = str(l.get("medium", "wired"))
        if not a or not b or a == b or a not in graph or b not in graph:
            continue
        port_seq[a] += 1
        pa = f"{a}:p{port_seq[a]}"
        graph[a].ports.append(Port(port_id=pa, neighbor_id=b, medium=m))
        port_seq[b] += 1
        pb = f"{b}:p{port_seq[b]}"
        graph[b].ports.append(Port(port_id=pb, neighbor_id=a, medium=m))
    return graph


def domain_stats(graph: dict[str, DeviceNode]) -> dict[str, int]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    non_router = [n.device_id for n in graph.values() if n.device_type != "router"]
    for d in non_router:
        parent[d] = d
    for n in graph.values():
        for p in n.ports:
            if n.device_id in parent and p.neighbor_id in parent:
                union(n.device_id, p.neighbor_id)
    bd = len({find(n) for n in non_router}) if non_router else 0

    seen_links: set[tuple[str, str]] = set()
    hub_counted: set[str] = set()
    cd = 0
    for n in graph.values():
        for p in n.ports:
            a, b = sorted([n.device_id, p.neighbor_id])
            if (a, b) in seen_links:
                continue
            seen_links.add((a, b))
            ta = graph[a].device_type
            tb = graph[b].device_type
            if ta == "hub" or tb == "hub":
                hub = a if ta == "hub" else b
                if hub not in hub_counted and graph[hub].ports:
                    hub_counted.add(hub)
                    cd += 1
            else:
                cd += 1
    return {"broadcast_domains": bd, "collision_domains": cd}


def simulate_datalink_topology(
    *,
    req: Any,
    session_state: dict[str, Any],
) -> tuple[
    List[SimEvent],
    dict[str, int],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    devices = req.topology_devices or []
    links = req.topology_links or []
    graph = build_graph(devices, links)
    if not graph:
        return [], {"broadcast_domains": 0, "collision_domains": 0}, {}, [], {}

    fp = topology_fingerprint(devices, links)
    if session_state.get("fingerprint") != fp:
        session_state.clear()
        session_state["fingerprint"] = fp
        session_state["switch_tables"] = {}

    if bool(getattr(req, "reset_learning", False)):
        session_state["switch_tables"] = {}

    switch_tables: dict[str, dict[str, str]] = session_state.setdefault("switch_tables", {})
    for n in graph.values():
        if n.device_type == "switch":
            switch_tables.setdefault(n.device_id, {})

    src = req.src_device_id
    dst = req.dst_device_id
    if src not in graph or dst not in graph:
        return [], domain_stats(graph), {}, [], {}

    collected: List[SimEvent] = []
    learning_summary: list[dict[str, Any]] = []
    src_mac = graph[src].mac
    dst_mac = graph[dst].mac
    payload = (req.message or "Hello NetSim").encode()
    flow_kwargs = {"window": req.window_size} if req.flow_control in ("go_back_n", "selective_repeat") else {}

    pending: deque[tuple[str, Optional[str], int, str, str, bytes, str, str]] = deque([
        # node_id, ingress_port, hop, frame_src_mac, frame_dst_mac, payload, frame_kind, final_dst
        (src, None, 0, src_mac, dst_mac, payload, "data", dst),
    ])
    # Loop guard tracks edge traversals by frame context to avoid suppressing
    # valid forwarding across multi-switch topologies.
    traversed: set[tuple[str, str, str, int, str, str, str]] = set()
    delivered = False

    while pending:
        node_id, ingress_port, hop, frame_src_mac, frame_dst_mac, frame_payload, frame_kind, frame_final_dst = pending.popleft()
        node = graph[node_id]
        if hop > max(2 * len(graph), 8):
            _emit_engine(collected, float(hop), node_id, "Frame dropped due to forwarding loop protection.", dst=dst)
            continue
        if node_id == frame_final_dst:
            if frame_kind == "data":
                delivered = True
            _emit_engine(
                collected,
                float(hop),
                node_id,
                f"{frame_kind.upper()} destination received frame.",
                dst=frame_final_dst,
                via=ingress_port,
            )
            if frame_kind == "data":
                # Destination emits a reply as a new transmission from host NIC.
                # Do not carry ingress_port here; otherwise single-homed hosts may
                # be unable to route the reply back to the switch for learning.
                _emit_engine(
                    collected,
                    float(hop),
                    node_id,
                    "Destination sends broadcast ACK for learning.",
                    dst=src,
                    ack_broadcast=True,
                )
                pending.append((
                    node_id,
                    None,
                    hop + 1,
                    graph[node_id].mac,                      # ACK source MAC (destination host)
                    "ff:ff:ff:ff:ff:ff",                     # broadcast ACK
                    b"ACK",
                    "ack",
                    src,                                     # eventually target original source
                ))
            continue

        role = ROLE_MAP.get(node.device_type, HostRole())
        st = switch_tables.setdefault(node_id, {}) if node.device_type == "switch" else {}
        if node.device_type == "switch":
            st["__current_src_mac__"] = frame_src_mac
        outs, info = role.forward(node, ingress_port, frame_dst_mac, frame_final_dst, graph, st)
        if node.device_type == "switch":
            st.pop("__current_src_mac__", None)

        _emit_engine(
            collected,
            float(hop),
            node_id,
            str(info.get("detail", "forwarding decision")),
            dst=frame_final_dst,
            forwarding_mode=info.get("mode", "route"),
            ingress_port=ingress_port,
            egress_ports=[p.port_id for p in outs],
            table_size=len({k: v for k, v in st.items() if not k.startswith("__")}),
            learned=info.get("learned"),
            frame_kind=frame_kind,
            src_mac=frame_src_mac,
            dst_mac=frame_dst_mac,
        )
        if info.get("learned"):
            learning_summary.append({
                "switch_id": node_id,
                **info["learned"],
                "hop": hop,
                "frame_kind": frame_kind,
            })

        for out in outs:
            edge = (
                node_id,
                out.neighbor_id,
                frame_kind,
                hop,
                frame_src_mac,
                frame_dst_mac,
                frame_final_dst,
            )
            if edge in traversed:
                continue
            traversed.add(edge)

            hop_events: List[SimEvent] = []

            class CollectObs:
                def on_event(self, e):
                    hop_events.append(e)

            dll = DataLinkLayerFactory.create(
                device_id=node_id,
                mac_addr=node.mac,
                framing=req.framing,
                error=req.error_control,
                mac_proto=req.mac_protocol,
                flow=req.flow_control,
                framing_kwargs=req.framing_kwargs,
                flow_kwargs=flow_kwargs,
                mac_kwargs=req.mac_kwargs,
            )
            dll.attach_observer(CollectObs())
            pdu = LayerPDU(data=payload, meta={
                "src_device": node_id,
                "dst_device": frame_final_dst,
                "dst_mac": frame_dst_mac if out.neighbor_id == frame_final_dst else "ff:ff:ff:ff:ff:ff",
                "timestamp": float(hop),
                "channel_busy": False,
                "collision_prob": req.collision_prob if out.medium == "wired" else max(req.collision_prob * 0.5, 0.0),
                "link_error_rate": req.link_error_rate,
                "inject_error": req.inject_error,
            })
            pdu.data = frame_payload
            dll.send_down(pdu)
            collected.extend(hop_events)

            _emit_engine(
                collected,
                float(hop),
                node_id,
                f"Forwarding {frame_kind} on link.",
                dst=out.neighbor_id,
                medium=out.medium,
                link=f"{node_id}->{out.neighbor_id}",
                egress_port=out.port_id,
                frame_kind=frame_kind,
            )

            ingress_on_next = next((p.port_id for p in graph[out.neighbor_id].ports if p.neighbor_id == node_id), None)
            pending.append((
                out.neighbor_id,
                ingress_on_next,
                hop + 1,
                frame_src_mac,
                frame_dst_mac,
                frame_payload,
                frame_kind,
                frame_final_dst,
            ))

    if not delivered:
        collected.append(SimEvent(
            timestamp=0.0,
            event_type=EventType.FRAME_DROPPED,
            layer=LayerName.DATALINK,
            src_device=src,
            dst_device=dst,
            pdu=PDU(type="frame", headers={"reason": "Topology forwarding ended before destination delivery"}),
        ))

    snapshot: dict[str, list[dict[str, Any]]] = {}
    for sw_id, table in switch_tables.items():
        if sw_id not in graph or graph[sw_id].device_type != "switch":
            continue
        rows = []
        for mac, port in table.items():
            if mac.startswith("__"):
                continue
            rows.append({"mac": mac, "port": port})
        rows.sort(key=lambda x: (x["mac"], x["port"]))
        snapshot[sw_id] = rows

    switch_ports: dict[str, list[dict[str, Any]]] = {}
    for sw_id, node in graph.items():
        if node.device_type != "switch":
            continue
        switch_ports[sw_id] = [
            {"port": p.port_id, "neighbor": p.neighbor_id, "medium": p.medium}
            for p in node.ports
        ]

    learning_summary.sort(key=lambda x: (str(x.get("switch_id", "")), int(x.get("hop", 0)), str(x.get("mac", ""))))
    return collected, domain_stats(graph), snapshot, learning_summary, switch_ports

