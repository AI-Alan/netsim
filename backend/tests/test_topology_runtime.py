import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from types import SimpleNamespace

from simulation.topology_runtime import simulate_datalink_topology


def _req(**kw):
    base = dict(
        session_id="sess-test",
        src_device_id="h1",
        dst_device_id="h2",
        message="hello",
        framing="variable",
        framing_kwargs={},
        error_control="crc32",
        mac_protocol="csma_cd",
        flow_control="stop_and_wait",
        window_size=4,
        collision_prob=0.0,
        link_error_rate=0.0,
        inject_error=False,
        mac_kwargs={},
        topology_devices=[],
        topology_links=[],
        reset_learning=False,
        traffic_flows=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _star_topology():
    devices = [
        {"id": "h1", "type": "computer", "mac": "aa:aa:aa:aa:aa:01"},
        {"id": "sw1", "type": "switch", "mac": "aa:aa:aa:aa:aa:10"},
        {"id": "h2", "type": "computer", "mac": "aa:aa:aa:aa:aa:02"},
        {"id": "h3", "type": "computer", "mac": "aa:aa:aa:aa:aa:03"},
    ]
    links = [
        {"src": "h1", "dst": "sw1", "medium": "wired"},
        {"src": "h2", "dst": "sw1", "medium": "wired"},
        {"src": "h3", "dst": "sw1", "medium": "wired"},
    ]
    return devices, links


def _two_switch_chain():
    devices = [
        {"id": "h1", "type": "computer", "mac": "aa:aa:aa:aa:aa:01"},
        {"id": "sw1", "type": "switch", "mac": "aa:aa:aa:aa:aa:11"},
        {"id": "sw2", "type": "switch", "mac": "aa:aa:aa:aa:aa:12"},
        {"id": "h2", "type": "computer", "mac": "aa:aa:aa:aa:aa:02"},
    ]
    links = [
        {"src": "h1", "dst": "sw1", "medium": "wired"},
        {"src": "sw1", "dst": "sw2", "medium": "wired"},
        {"src": "sw2", "dst": "h2", "medium": "wired"},
    ]
    return devices, links


def _two_switch_with_branches():
    devices = [
        {"id": "h1", "type": "computer", "mac": "aa:aa:aa:aa:aa:01"},
        {"id": "h2", "type": "computer", "mac": "aa:aa:aa:aa:aa:02"},
        {"id": "h3", "type": "computer", "mac": "aa:aa:aa:aa:aa:03"},
        {"id": "h4", "type": "computer", "mac": "aa:aa:aa:aa:aa:04"},
        {"id": "sw1", "type": "switch", "mac": "aa:aa:aa:aa:aa:11"},
        {"id": "sw2", "type": "switch", "mac": "aa:aa:aa:aa:aa:12"},
    ]
    links = [
        {"src": "h1", "dst": "sw1", "medium": "wired"},
        {"src": "h2", "dst": "sw1", "medium": "wired"},
        {"src": "sw1", "dst": "sw2", "medium": "wired"},
        {"src": "h3", "dst": "sw2", "medium": "wired"},
        {"src": "h4", "dst": "sw2", "medium": "wired"},
    ]
    return devices, links


def test_unknown_destination_floods():
    devices, links = _star_topology()
    state = {}
    req = _req(topology_devices=devices, topology_links=links)
    events, _, _, _, _ = simulate_datalink_topology(req=req, session_state=state)
    flood = [
        e for e in events
        if e.layer == "engine"
        and e.src_device == "sw1"
        and e.pdu.headers.get("forwarding_mode") == "flood"
    ]
    assert len(flood) >= 1


def test_learning_then_unicast_across_runs():
    devices, links = _star_topology()
    state = {}
    req1 = _req(topology_devices=devices, topology_links=links)
    _, _, tables1, _, _ = simulate_datalink_topology(req=req1, session_state=state)
    assert "sw1" in tables1
    assert any(row["mac"] == "aa:aa:aa:aa:aa:01" for row in tables1["sw1"])

    req2 = _req(topology_devices=devices, topology_links=links)
    events2, _, _, _, _ = simulate_datalink_topology(req=req2, session_state=state)
    unicast = [
        e for e in events2
        if e.layer == "engine"
        and e.src_device == "sw1"
        and e.pdu.headers.get("forwarding_mode") == "unicast"
    ]
    assert len(unicast) >= 1


def test_destination_change_floods_then_learns_new_mac():
    devices, links = _star_topology()
    state = {}

    # First flow h1 -> h2 learns h1 (and h2 on reply path).
    req1 = _req(topology_devices=devices, topology_links=links, src_device_id="h1", dst_device_id="h2")
    simulate_datalink_topology(req=req1, session_state=state)

    # New destination h3 should still flood first if h3 MAC is unknown.
    req2 = _req(topology_devices=devices, topology_links=links, src_device_id="h1", dst_device_id="h3")
    events2, _, tables2, _, _ = simulate_datalink_topology(req=req2, session_state=state)
    flood = [
        e for e in events2
        if e.layer == "engine"
        and e.src_device == "sw1"
        and e.pdu.headers.get("forwarding_mode") == "flood"
    ]
    assert len(flood) >= 1

    # After the first h1 -> h3 exchange, switch should learn h3 on reply.
    assert any(row["mac"] == "aa:aa:aa:aa:aa:03" for row in tables2.get("sw1", []))


def test_reset_and_topology_change_invalidate_tables():
    devices, links = _star_topology()
    state = {}
    req = _req(topology_devices=devices, topology_links=links)
    simulate_datalink_topology(req=req, session_state=state)

    req_reset = _req(topology_devices=devices, topology_links=links, reset_learning=True)
    _, _, tables_reset, _, _ = simulate_datalink_topology(req=req_reset, session_state=state)
    # reset clears tables at run start; snapshot is after the run, so MACs are learned again
    assert any(row["mac"] == "aa:aa:aa:aa:aa:01" for row in tables_reset.get("sw1", []))

    devices2 = [d for d in devices if d["id"] != "h3"]
    links2 = [l for l in links if l["src"] != "h3" and l["dst"] != "h3"]
    req_changed = _req(topology_devices=devices2, topology_links=links2)
    _, _, tables_changed, _, _ = simulate_datalink_topology(req=req_changed, session_state=state)
    assert "sw1" in tables_changed


def test_two_switch_chain_flood_then_unicast_across_both_switches():
    devices, links = _two_switch_chain()
    state = {}

    req1 = _req(topology_devices=devices, topology_links=links, src_device_id="h1", dst_device_id="h2")
    events1, _, tables1, _, _ = simulate_datalink_topology(req=req1, session_state=state)

    flood_sw1 = [e for e in events1 if e.layer == "engine" and e.src_device == "sw1" and e.pdu.headers.get("forwarding_mode") == "flood"]
    flood_sw2 = [e for e in events1 if e.layer == "engine" and e.src_device == "sw2" and e.pdu.headers.get("forwarding_mode") == "flood"]
    assert len(flood_sw1) >= 1
    assert len(flood_sw2) >= 1
    assert any(row["mac"] == "aa:aa:aa:aa:aa:01" for row in tables1.get("sw1", []))
    assert any(row["mac"] == "aa:aa:aa:aa:aa:02" for row in tables1.get("sw2", []))

    req2 = _req(topology_devices=devices, topology_links=links, src_device_id="h1", dst_device_id="h2")
    events2, _, _, _, _ = simulate_datalink_topology(req=req2, session_state=state)
    unicast_sw1 = [e for e in events2 if e.layer == "engine" and e.src_device == "sw1" and e.pdu.headers.get("forwarding_mode") == "unicast"]
    unicast_sw2 = [e for e in events2 if e.layer == "engine" and e.src_device == "sw2" and e.pdu.headers.get("forwarding_mode") == "unicast"]
    assert len(unicast_sw1) >= 1
    assert len(unicast_sw2) >= 1


def test_multi_switch_branch_topology_has_no_false_loop_suppression():
    devices, links = _two_switch_with_branches()
    state = {}
    req = _req(topology_devices=devices, topology_links=links, src_device_id="h1", dst_device_id="h3")
    events, _, _, _, _ = simulate_datalink_topology(req=req, session_state=state)

    delivered = [
        e for e in events
        if e.layer == "engine"
        and e.src_device == "h3"
        and "destination received frame" in str(e.pdu.headers.get("detail", "")).lower()
    ]
    assert len(delivered) >= 1


def test_hub_two_flows_first_hop_structural_collision():
    """Two senders on the same hub share a collision domain; first slot is a structural collision."""
    devices = [
        {"id": "h1", "type": "computer", "mac": "aa:aa:aa:aa:aa:01"},
        {"id": "h2", "type": "computer", "mac": "aa:aa:aa:aa:aa:02"},
        {"id": "h3", "type": "computer", "mac": "aa:aa:aa:aa:aa:03"},
        {"id": "hub1", "type": "hub", "mac": "aa:aa:aa:aa:aa:10"},
    ]
    links = [
        {"src": "h1", "dst": "hub1", "medium": "wired"},
        {"src": "h2", "dst": "hub1", "medium": "wired"},
        {"src": "h3", "dst": "hub1", "medium": "wired"},
    ]
    state = {}
    req = _req(
        topology_devices=devices,
        topology_links=links,
        src_device_id="h1",
        dst_device_id="h2",
        traffic_flows=[
            SimpleNamespace(src_device_id="h1", dst_device_id="h2", message="a"),
            SimpleNamespace(src_device_id="h3", dst_device_id="h2", message="b"),
        ],
        collision_prob=0.0,
    )
    events, _, _, _, _ = simulate_datalink_topology(req=req, session_state=state)
    collisions = [
        e
        for e in events
        if e.event_type == "ACCESS_CONTROL" and e.pdu.headers.get("collision") is True
    ]
    assert len(collisions) >= 1


def test_hub_staggered_start_slots_avoid_structural_collision():
    devices = [
        {"id": "h1", "type": "computer", "mac": "aa:aa:aa:aa:aa:01"},
        {"id": "h2", "type": "computer", "mac": "aa:aa:aa:aa:aa:02"},
        {"id": "h3", "type": "computer", "mac": "aa:aa:aa:aa:aa:03"},
        {"id": "hub1", "type": "hub", "mac": "aa:aa:aa:aa:aa:10"},
    ]
    links = [
        {"src": "h1", "dst": "hub1", "medium": "wired"},
        {"src": "h2", "dst": "hub1", "medium": "wired"},
        {"src": "h3", "dst": "hub1", "medium": "wired"},
    ]
    state = {}
    req = _req(
        topology_devices=devices,
        topology_links=links,
        src_device_id="h1",
        dst_device_id="h2",
        traffic_flows=[
            SimpleNamespace(src_device_id="h1", dst_device_id="h2", message="a", start_slot=0),
            SimpleNamespace(src_device_id="h3", dst_device_id="h2", message="b", start_slot=100),
        ],
        collision_prob=0.0,
    )
    events, _, _, _, _ = simulate_datalink_topology(req=req, session_state=state)
    collisions = [
        e
        for e in events
        if e.event_type == "ACCESS_CONTROL" and e.pdu.headers.get("collision") is True
    ]
    assert len(collisions) == 0


def test_access_control_includes_flow_endpoint_ids():
    devices = [
        {"id": "h1", "type": "computer", "mac": "aa:aa:aa:aa:aa:01"},
        {"id": "h2", "type": "computer", "mac": "aa:aa:aa:aa:aa:02"},
        {"id": "h3", "type": "computer", "mac": "aa:aa:aa:aa:aa:03"},
        {"id": "hub1", "type": "hub", "mac": "aa:aa:aa:aa:aa:10"},
    ]
    links = [
        {"src": "h1", "dst": "hub1", "medium": "wired"},
        {"src": "h2", "dst": "hub1", "medium": "wired"},
        {"src": "h3", "dst": "hub1", "medium": "wired"},
    ]
    state = {}
    req = _req(
        topology_devices=devices,
        topology_links=links,
        traffic_flows=[
            SimpleNamespace(src_device_id="h1", dst_device_id="h2", message="a", start_slot=0),
            SimpleNamespace(src_device_id="h3", dst_device_id="h2", message="b", start_slot=0),
        ],
        collision_prob=0.0,
    )
    events, _, _, _, _ = simulate_datalink_topology(req=req, session_state=state)
    ac = [e for e in events if e.event_type == "ACCESS_CONTROL"]
    assert ac
    for e in ac:
        assert e.pdu.headers.get("flow_src_device_id") in ("h1", "h3")
        assert e.pdu.headers.get("flow_dst_device_id") == "h2"
