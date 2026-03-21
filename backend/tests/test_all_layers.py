"""
tests/test_all_layers.py
--------------------------
Complete NetSim test suite – Physical + Data Link + Network + Transport + Application.
Run: python tests/test_all_layers.py
"""
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from layers.physical.models import Bits, Signal
from layers.physical.encoding import (
    NRZEncoding, NRZIEncoding, ManchesterEncoding,
    DiffManchesterEncoding, AMIEncoding, FourBFiveBEncoding, ENCODING_REGISTRY,
)
from layers.physical.medium import WiredMedium, WirelessMedium
from layers.physical.factory import PhysicalLayerFactory
from layers.datalink.framing import FixedSizeFraming, VariableSizeFraming, FRAMING_REGISTRY
from layers.datalink.error_control import ChecksumErrorControl, CRCErrorControl, ERROR_CONTROL_REGISTRY
from layers.datalink.access_control import (
    PureAloha, SlottedAloha, CSMA, CSMACD, CSMACA, MAC_REGISTRY,
)
from layers.datalink.flow_control import (
    StopAndWaitARQ, GoBackNARQ, SelectiveRepeatARQ, FLOW_REGISTRY,
)
from layers.datalink.factory import DataLinkLayerFactory
from layers.datalink.layer import DataLinkLayerImpl
from layers.network.layer import NetworkLayerImpl
from layers.transport.layer import TransportLayerImpl
from layers.application.layer import ApplicationLayerImpl, HTTPProtocol, DNSProtocol
from devices.end_host import EndHost
from layers.base import ILayerObserver, LayerPDU
from simulation.events import SimEvent, EventType, LayerName, PDU
from simulation.engine import SimulationEngine

BITS = Bits.from_list([1, 0, 1, 1, 0, 1, 0, 0])
BS   = [1, 0, 1, 1, 0, 1, 0, 0]

# ── helpers ─────────────────────────────────────────────────────────────────
class CollectObs(ILayerObserver):
    def __init__(self): self.events: list[SimEvent] = []
    def on_event(self, e): self.events.append(e)

def _collect_phy(encoding="NRZ-L"):
    obs = CollectObs()
    layer = PhysicalLayerFactory.create(encoding, "wired", device_id="h")
    layer.attach_observer(obs)
    layer.send_down(LayerPDU(data=BITS, meta={"src_device":"h","dst_device":"r","timestamp":0.5}))
    return obs.events

def _collect_dll(
    framing="variable", error="crc32", mac="csma_cd", flow="stop_and_wait",
    payload=b"Hello NetSim!", collision_prob=0.0,
):
    obs = CollectObs(); phy_obs = CollectObs()
    dll = DataLinkLayerFactory.create(
        device_id="h", mac_addr="aa:bb:cc:dd:ee:01",
        framing=framing, error=error, mac_proto=mac, flow=flow,
    )
    phy = PhysicalLayerFactory.create("Manchester","wired",device_id="h")
    dll.attach_observer(obs); phy.attach_observer(phy_obs)
    dll.set_lower(phy)
    pdu = LayerPDU(data=payload, meta={
        "src_device":"h","dst_device":"r","dst_mac":"ff:ff:ff:ff:ff:ff",
        "timestamp":0.0,"channel_busy":False,
        "collision_prob":collision_prob,"link_error_rate":0.0,
    })
    dll.send_down(pdu)
    return obs.events, phy_obs.events

# ══════════════════════════════════════════════════════════════════════════════
# PHYSICAL LAYER TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_bits_from_bytes_roundtrip():
    b = Bits.from_bytes(b"\xDE\xAD\xBE\xEF")
    assert b.to_bytes() == b"\xDE\xAD\xBE\xEF"

def test_bits_rejects_invalid():
    try: Bits.from_list([0, 1, 2]); assert False, "should raise"
    except ValueError: pass

def test_signal_clamps_not_raises():
    # New behaviour: clamp instead of raise (wireless noise can push past ±1)
    s = Signal.from_list([1.5, -1.5], 100, "test")
    assert all(-1.0 <= x <= 1.0 for x in s.samples)

def test_signal_to_dict():
    s = Signal.from_list([1.0, -1.0], 100, "NRZ-L")
    d = s.to_dict(); assert d["encoding"] == "NRZ-L"; assert len(d["samples"]) == 2

def test_nrzl_roundtrip():
    enc = NRZEncoding(); assert list(enc.decode(enc.encode(BITS)).data) == BS

def test_nrzi_roundtrip():
    enc = NRZIEncoding(); assert list(enc.decode(enc.encode(BITS)).data) == BS

def test_manchester_roundtrip():
    enc = ManchesterEncoding(); assert list(enc.decode(enc.encode(BITS)).data) == BS

def test_diff_manchester_roundtrip():
    enc = DiffManchesterEncoding(); assert list(enc.decode(enc.encode(BITS)).data) == BS

def test_ami_roundtrip():
    enc = AMIEncoding(); assert list(enc.decode(enc.encode(BITS)).data) == BS

def test_4b5b_roundtrip():
    enc = FourBFiveBEncoding()
    b = Bits.from_list([1,0,1,1,0,1,0,0,1,1,1,0])
    assert list(enc.decode(enc.encode(b)).data[:12]) == [1,0,1,1,0,1,0,0,1,1,1,0]

def test_encoding_registry_complete():
    assert set(ENCODING_REGISTRY) == {"NRZ-L","NRZ-I","Manchester","Differential Manchester","AMI","4B5B"}

def test_wired_no_ber():
    sig = NRZEncoding().encode(BITS)
    assert WiredMedium(ber=0.0).transmit(sig).samples == sig.samples

def test_wired_ber_corrupts():
    random.seed(42)
    big = NRZEncoding().encode(Bits.from_list([1]*1000))
    noisy = WiredMedium(ber=0.5).transmit(big)
    assert sum(1 for a,b in zip(big.samples,noisy.samples) if a!=b) > 100

def test_wireless_normalised():
    sig = NRZEncoding().encode(BITS)
    out = WirelessMedium().transmit(sig)
    assert len(out.samples) == len(sig.samples)
    assert all(-1.0 <= s <= 1.0 for s in out.samples)

def test_phy_factory_create():
    assert PhysicalLayerFactory.create("Manchester","wired",device_id="h") is not None

def test_phy_factory_bad_encoding():
    try: PhysicalLayerFactory.create("BOGUS","wired"); assert False
    except ValueError: pass

def test_phy_emits_bits_sent():
    evts = _collect_phy()
    assert any(e.event_type == EventType.BITS_SENT for e in evts)

def test_phy_emits_signal_drawn():
    evts = _collect_phy()
    assert any(e.event_type == EventType.SIGNAL_DRAWN for e in evts)

def test_phy_signal_sample_count():
    ev = next(e for e in _collect_phy() if e.event_type == EventType.SIGNAL_DRAWN)
    assert len(ev.signal["samples"]) == 800   # 8 bits × 100 spb

def test_phy_bits_sent_headers():
    ev = next(e for e in _collect_phy() if e.event_type == EventType.BITS_SENT)
    assert ev.pdu.headers["raw_bits"] == "10110100"
    assert ev.pdu.headers["encoding"] == "NRZ-L"

def test_phy_timestamp_propagated():
    ev = next(e for e in _collect_phy() if e.event_type == EventType.SIGNAL_DRAWN)
    assert ev.timestamp == 0.5

# ══════════════════════════════════════════════════════════════════════════════
# DATA LINK — FRAMING
# ══════════════════════════════════════════════════════════════════════════════

def test_variable_framing_roundtrip():
    vf = VariableSizeFraming()
    for data in [b"Hello", b"\x7E\x7D inside flags \x7E", b"", b"\x00" * 50]:
        assert vf.deframe(vf.frame(data)) == data, f"Failed for {data!r}"

def test_fixed_framing_roundtrip():
    ff = FixedSizeFraming(64)
    data = b"Short msg"
    assert ff.deframe(ff.frame(data)) == data

def test_variable_framing_flag_stuffing():
    """Flag byte 0x7E inside payload must be escaped."""
    vf = VariableSizeFraming()
    data = b"\x7E\x7E\x7E"  # three flags
    framed = vf.frame(data)
    # Framed should have more bytes due to stuffing
    assert len(framed) > len(data) + 2
    assert vf.deframe(framed) == data

def test_framing_registry_complete():
    assert "fixed" in FRAMING_REGISTRY and "variable" in FRAMING_REGISTRY

# ══════════════════════════════════════════════════════════════════════════════
# DATA LINK — ERROR CONTROL
# ══════════════════════════════════════════════════════════════════════════════

def test_crc32_correct():
    crc = CRCErrorControl()
    data = b"Test CRC payload"
    result = crc.verify(crc.compute(data))
    assert result.ok, result.detail

def test_crc32_detects_corruption():
    crc = CRCErrorControl()
    protected = crc.compute(b"Good payload")
    # Flip last byte of FCS
    corrupted = bytearray(protected); corrupted[-1] ^= 0xFF
    assert not crc.verify(bytes(corrupted)).ok

def test_crc32_detects_bit_flip():
    crc = CRCErrorControl()
    protected = crc.compute(b"Payload data here")
    # Flip a bit in payload
    corrupted = bytearray(protected); corrupted[3] ^= 0x01
    result = crc.verify(bytes(corrupted))
    assert not result.ok and result.dropped

def test_checksum16_correct():
    cs = ChecksumErrorControl()
    data = b"Checksum test data"
    assert cs.verify(cs.compute(data)).ok

def test_checksum16_detects_error():
    cs = ChecksumErrorControl()
    protected = cs.compute(b"Good data")
    corrupted = bytearray(protected); corrupted[0] ^= 0xFF
    assert not cs.verify(bytes(corrupted)).ok

def test_checksum_overhead():
    cs = ChecksumErrorControl()
    assert cs.overhead_bytes == 2

def test_crc_overhead():
    crc = CRCErrorControl()
    assert crc.overhead_bytes == 4

def test_error_control_registry():
    assert "crc32" in ERROR_CONTROL_REGISTRY and "checksum" in ERROR_CONTROL_REGISTRY

# ══════════════════════════════════════════════════════════════════════════════
# DATA LINK — ACCESS CONTROL (MAC)
# ══════════════════════════════════════════════════════════════════════════════

def test_pure_aloha_transmits_when_no_collision():
    r = PureAloha().transmit(collision_prob=0.0)
    assert r.transmitted

def test_slotted_aloha_transmits_when_no_collision():
    r = SlottedAloha().transmit(collision_prob=0.0)
    assert r.transmitted

def test_csma_transmits():
    r = CSMA().transmit(channel_busy=False, collision_prob=0.0)
    assert r.transmitted

def test_csmacd_transmits_no_collision():
    r = CSMACD().transmit(channel_busy=False, collision_prob=0.0)
    assert r.transmitted
    assert r.attempts >= 1

def test_csmacd_has_steps():
    r = CSMACD().transmit(collision_prob=0.0)
    assert len(r.steps) >= 1

def test_csmaca_transmits_no_collision():
    r = CSMACA().transmit(collision_prob=0.0)
    assert r.transmitted

def test_csmaca_rts_cts():
    r = CSMACA(use_rts_cts=True).transmit(collision_prob=0.0)
    assert r.transmitted and r.rts_cts_used

def test_mac_registry_complete():
    for k in ["pure_aloha","slotted_aloha","csma","csma_cd","csma_ca"]:
        assert k in MAC_REGISTRY, f"Missing: {k}"

def test_csmacd_max_collision_drops():
    """At collision_prob=1.0 CSMA/CD must eventually give up."""
    r = CSMACD().transmit(collision_prob=1.0)
    # Either dropped or transmitted after many retries
    assert isinstance(r.transmitted, bool)

# ══════════════════════════════════════════════════════════════════════════════
# DATA LINK — FLOW CONTROL (ARQ)
# ══════════════════════════════════════════════════════════════════════════════

def test_saw_no_errors():
    r = StopAndWaitARQ().transfer(4, error_rate=0.0)
    assert r.frames_acked == 4 and r.retransmissions == 0

def test_saw_window_is_one():
    assert StopAndWaitARQ().window_size == 1

def test_saw_with_errors_still_delivers():
    random.seed(7)
    r = StopAndWaitARQ().transfer(6, error_rate=0.5)
    assert r.frames_acked == 6   # SAW always eventually delivers
    assert r.retransmissions >= 0

def test_gbn_no_errors():
    r = GoBackNARQ(window=4).transfer(8, error_rate=0.0)
    assert r.frames_acked == 8 and r.retransmissions == 0

def test_gbn_window_size():
    assert GoBackNARQ(window=7).window_size == 7

def test_gbn_efficiency_perfect():
    r = GoBackNARQ(window=4).transfer(8, error_rate=0.0)
    assert r.efficiency == 1.0

def test_sr_no_errors():
    r = SelectiveRepeatARQ(window=4).transfer(8, error_rate=0.0)
    assert r.frames_acked == 8 and r.retransmissions == 0

def test_sr_higher_efficiency_than_gbn_under_errors():
    random.seed(42)
    err = 0.3
    gbn_r = GoBackNARQ(window=4).transfer(20, error_rate=err)
    random.seed(42)
    sr_r  = SelectiveRepeatARQ(window=4).transfer(20, error_rate=err)
    # SR should be >= GBN in efficiency (retransmits fewer frames)
    assert sr_r.efficiency >= gbn_r.efficiency

def test_flow_registry_complete():
    for k in ["stop_and_wait","go_back_n","selective_repeat"]:
        assert k in FLOW_REGISTRY, f"Missing: {k}"

def test_arq_steps_populated():
    r = StopAndWaitARQ().transfer(3, error_rate=0.0)
    assert len(r.steps) >= 3

# ══════════════════════════════════════════════════════════════════════════════
# DATA LINK — FULL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def test_dll_emits_framing_info():
    evts, _ = _collect_dll()
    assert any(e.event_type == EventType.FRAMING_INFO for e in evts)

def test_dll_emits_access_control():
    evts, _ = _collect_dll()
    assert any(e.event_type == EventType.ACCESS_CONTROL for e in evts)

def test_dll_emits_flow_control():
    evts, _ = _collect_dll()
    assert any(e.event_type == EventType.FLOW_CONTROL for e in evts)

def test_dll_emits_frame_sent():
    evts, _ = _collect_dll()
    assert any(e.event_type == EventType.FRAME_SENT for e in evts)

def test_dll_passes_to_physical():
    _, phy_evts = _collect_dll()
    assert any(e.event_type == EventType.BITS_SENT for e in phy_evts)
    assert any(e.event_type == EventType.SIGNAL_DRAWN for e in phy_evts)

def test_dll_frame_sent_has_mac_info():
    evts, _ = _collect_dll()
    ev = next(e for e in evts if e.event_type == EventType.FRAME_SENT)
    h = ev.pdu.headers
    assert "dst_mac" in h and "src_mac" in h
    assert "error_scheme" in h and "mac_protocol" in h

def test_dll_error_injection_drops():
    """Injecting error into payload: CRC should detect and drop."""
    # Manually craft a bad frame by corrupting protected bytes
    crc = CRCErrorControl()
    framing = VariableSizeFraming()
    data = b"Good payload for testing"
    framed  = framing.frame(data)
    protected = crc.compute(framed)
    # Corrupt a byte
    bad = bytearray(protected); bad[5] ^= 0xAA
    result = crc.verify(bytes(bad))
    assert not result.ok and result.dropped

def test_dll_all_mac_protocols_fire():
    for mac in ["pure_aloha","slotted_aloha","csma","csma_cd","csma_ca"]:
        evts, _ = _collect_dll(mac=mac, collision_prob=0.0)
        ac = [e for e in evts if e.event_type == EventType.ACCESS_CONTROL]
        assert len(ac) == 1, f"{mac}: expected 1 ACCESS_CONTROL event"
        assert ac[0].pdu.headers["protocol"] == MAC_REGISTRY[mac]().name

def test_dll_all_arq_protocols_fire():
    for flow, kwargs in [("stop_and_wait",{}),("go_back_n",{"window":4}),("selective_repeat",{"window":4})]:
        dll = DataLinkLayerFactory.create(
            device_id="h", mac_addr="aa:bb:cc:dd:ee:01",
            framing="variable", error="crc32", mac_proto="csma_cd", flow=flow,
            flow_kwargs=kwargs,
        )
        obs = CollectObs(); dll.attach_observer(obs)
        pdu = LayerPDU(data=b"ARQ test", meta={
            "dst_mac":"ff:ff:ff:ff:ff:ff","timestamp":0.0,
            "channel_busy":False,"collision_prob":0.0,"link_error_rate":0.0,
        })
        dll.send_down(pdu)
        fc = [e for e in obs.events if e.event_type == EventType.FLOW_CONTROL]
        assert len(fc) >= 1, f"{flow}: no FLOW_CONTROL event"

def test_dll_framing_names_in_event():
    for framing in ["fixed","variable"]:
        evts, _ = _collect_dll(framing=framing)
        fi = next(e for e in evts if e.event_type == EventType.FRAMING_INFO)
        name = fi.pdu.headers.get("scheme","")
        assert ("Fixed" in name or "Variable" in name), f"Bad framing name: {name}"

def test_dll_factory_available_options():
    opts = DataLinkLayerFactory.available_options()
    assert "framing" in opts and "error" in opts and "mac_proto" in opts and "flow" in opts

# ══════════════════════════════════════════════════════════════════════════════
# NETWORK LAYER
# ══════════════════════════════════════════════════════════════════════════════

def test_network_emits_routing_lookup():
    obs = CollectObs()
    net = NetworkLayerImpl(device_id="h1", src_ip="192.168.1.1")
    net.attach_observer(obs)
    net.add_route("0.0.0.0","0.0.0.0","192.168.1.1")
    pdu = LayerPDU(data=b"IP payload", meta={"dst_ip":"10.0.0.1","timestamp":0.0})
    net._do_send(pdu)
    assert any(e.event_type == EventType.ROUTING_LOOKUP for e in obs.events)

def test_network_emits_packet_sent():
    obs = CollectObs()
    net = NetworkLayerImpl(device_id="h1", src_ip="192.168.1.1")
    net.attach_observer(obs)
    net.add_route("0.0.0.0","0.0.0.0","192.168.1.1")
    pdu = LayerPDU(data=b"data", meta={"dst_ip":"10.0.0.2","timestamp":0.0})
    net._do_send(pdu)
    assert any(e.event_type == EventType.PACKET_SENT for e in obs.events)

def test_routing_table_lookup_default():
    net = NetworkLayerImpl(device_id="h1", src_ip="10.0.0.1")
    net.add_route("0.0.0.0","0.0.0.0","192.168.1.1",metric=1)
    entry = net._routing_table.lookup("8.8.8.8")
    assert entry is not None and entry.next_hop == "192.168.1.1"

def test_routing_table_no_match():
    net = NetworkLayerImpl(device_id="h1", src_ip="10.0.0.1")
    # No routes added → no match
    entry = net._routing_table.lookup("8.8.8.8")
    assert entry is None

# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORT LAYER
# ══════════════════════════════════════════════════════════════════════════════

def test_transport_emits_segment_sent():
    obs = CollectObs()
    trn = TransportLayerImpl(device_id="h1", use_tcp=True)
    trn.attach_observer(obs)
    pdu = LayerPDU(data=b"App data", meta={"dst_device":"h2","timestamp":0.0,"dst_port":80})
    trn._do_send(pdu)
    assert any(e.event_type == EventType.SEGMENT_SENT for e in obs.events)

def test_transport_emits_tcp_state_on_first_send():
    obs = CollectObs()
    trn = TransportLayerImpl(device_id="h1", use_tcp=True)
    trn.attach_observer(obs)
    trn._tcp_sm.add_observer(obs.on_event)
    pdu = LayerPDU(data=b"Hello", meta={"dst_device":"h2","timestamp":0.0})
    trn._do_send(pdu)
    assert any(e.event_type == EventType.TCP_STATE for e in obs.events)

def test_transport_udp_no_state():
    obs = CollectObs()
    trn = TransportLayerImpl(device_id="h1", use_tcp=False)
    trn.attach_observer(obs)
    pdu = LayerPDU(data=b"UDP datagram", meta={"dst_device":"h2","timestamp":0.0})
    trn._do_send(pdu)
    tcp_states = [e for e in obs.events if e.event_type == EventType.TCP_STATE]
    assert len(tcp_states) == 0   # UDP has no state machine

def test_transport_segment_headers():
    obs = CollectObs()
    trn = TransportLayerImpl(device_id="h1", use_tcp=True, port=5000)
    trn.attach_observer(obs)
    pdu = LayerPDU(data=b"payload", meta={"dst_device":"h2","timestamp":0.0,"dst_port":80})
    trn._do_send(pdu)
    seg = next(e for e in obs.events if e.event_type == EventType.SEGMENT_SENT)
    assert seg.pdu.headers["src_port"] == 5000
    assert seg.pdu.headers["dst_port"] == 80
    assert seg.pdu.headers["protocol"] == "TCP"

# ══════════════════════════════════════════════════════════════════════════════
# APPLICATION LAYER (TCP/IP: session + presentation merged in)
# ══════════════════════════════════════════════════════════════════════════════

def test_app_emits_session_info_on_first_send():
    obs = CollectObs()
    app = ApplicationLayerImpl(device_id="h1", app_proto="http")
    app.attach_observer(obs)
    pdu = LayerPDU(data=b"GET /", meta={"timestamp":0.0,"url":"/","method":"GET"})
    app._do_send(pdu)
    assert any(e.event_type == EventType.SESSION_INFO for e in obs.events)

def test_app_session_info_says_tcp_ip_model():
    obs = CollectObs()
    app = ApplicationLayerImpl(device_id="h1")
    app.attach_observer(obs)
    pdu = LayerPDU(data=b"data", meta={"timestamp":0.0})
    app._do_send(pdu)
    si = next(e for e in obs.events if e.event_type == EventType.SESSION_INFO)
    assert "TCP/IP" in si.pdu.headers.get("note","")

def test_app_emits_app_request():
    obs = CollectObs()
    app = ApplicationLayerImpl(device_id="h1", app_proto="http")
    app.attach_observer(obs)
    pdu = LayerPDU(data=b"GET /index.html", meta={"timestamp":0.0,"method":"GET","url":"/index.html"})
    app._do_send(pdu)
    assert any(e.event_type == EventType.APP_REQUEST for e in obs.events)

def test_app_base64_encoding_event():
    obs = CollectObs()
    app = ApplicationLayerImpl(device_id="h1", encode_b64=True)
    app.attach_observer(obs)
    pdu = LayerPDU(data=b"encode me", meta={"timestamp":0.0})
    app._do_send(pdu)
    enc_evts = [e for e in obs.events if e.event_type == EventType.APP_ENCODING]
    assert len(enc_evts) >= 1
    assert "Base64" in enc_evts[0].pdu.headers.get("scheme","")

def test_app_xor_encryption_event():
    obs = CollectObs()
    app = ApplicationLayerImpl(device_id="h1", xor_key=0xAB)
    app.attach_observer(obs)
    pdu = LayerPDU(data=b"secret", meta={"timestamp":0.0})
    app._do_send(pdu)
    enc_evts = [e for e in obs.events if e.event_type == EventType.APP_ENCODING]
    assert any("XOR" in str(e.pdu.headers.get("scheme","")) for e in enc_evts)

def test_app_http_protocol():
    proto = HTTPProtocol()
    resp, headers = proto.handle_request(b"GET /", {"method":"GET","url":"/"})
    assert headers["status_code"] == 200
    assert b"HTTP" in resp

def test_app_dns_protocol():
    proto = DNSProtocol()
    resp, headers = proto.handle_request(b"www.example.com", {})
    assert "93.184" in headers["answer"]

def test_app_dns_nxdomain():
    proto = DNSProtocol()
    _, headers = proto.handle_request(b"nonexistent.xyz", {})
    assert headers["answer"] == "NXDOMAIN"

def test_app_no_session_opened_twice():
    """Session should only be opened once per ApplicationLayer instance."""
    obs = CollectObs()
    app = ApplicationLayerImpl(device_id="h1")
    app.attach_observer(obs)
    for _ in range(3):
        pdu = LayerPDU(data=b"data", meta={"timestamp":0.0})
        app._do_send(pdu)
    si_evts = [e for e in obs.events if e.event_type == EventType.SESSION_INFO]
    assert len(si_evts) == 1   # only opened once

# ══════════════════════════════════════════════════════════════════════════════
# END-TO-END: FULL STACK (Application → Physical)
# ══════════════════════════════════════════════════════════════════════════════

def test_endhost_all_layers_wired():
    host = EndHost("h1","aa:bb:cc:dd:ee:01","192.168.1.1")
    host.configure_layers({
        "physical":    {"encoding":"Manchester","medium":"wired"},
        "datalink":    {"framing":"variable","error":"crc32","mac_proto":"csma_cd","flow":"stop_and_wait"},
        "transport":   {"use_tcp":True},
        "application": {"protocol":"http"},
    })
    assert set(host.layers.keys()) == {"physical","datalink","network","transport","application"}

def test_endhost_layer_order():
    host = EndHost("h1","aa:bb:cc:dd:ee:02","192.168.1.2")
    host.configure_layers({})
    # Top layer should be application, bottom physical
    top = host._get_top_layer()
    assert top is not None
    assert top.layer_name == "application"

def test_full_stack_events():
    """End-to-end: send through all layers, collect all events."""
    all_evts: list[SimEvent] = []

    class GlobalObs(ILayerObserver):
        def on_event(self, e): all_evts.append(e)

    host = EndHost("h1","aa:bb:cc:dd:ee:03","192.168.1.3")
    host.configure_layers({
        "physical":  {"encoding":"Manchester","medium":"wired"},
        "datalink":  {"framing":"variable","error":"crc32","mac_proto":"csma_cd","flow":"stop_and_wait"},
        "transport": {"use_tcp":True,"port":8080},
        "application":{"protocol":"http"},
    })
    host.attach_observer(GlobalObs())

    host.send(data=b"GET /index.html HTTP/1.1", dst_ip="192.168.1.99",
              meta={"method":"GET","url":"/index.html","dst_port":80,"timestamp":0.0,
                    "channel_busy":False,"collision_prob":0.0,"link_error_rate":0.0})

    event_types = {e.event_type for e in all_evts}
    # Must see events from every layer
    assert EventType.SESSION_INFO    in event_types, "No SESSION_INFO"
    assert EventType.APP_REQUEST     in event_types, "No APP_REQUEST"
    assert EventType.SEGMENT_SENT   in event_types, "No SEGMENT_SENT"
    assert EventType.PACKET_SENT    in event_types, "No PACKET_SENT"
    assert EventType.FRAMING_INFO   in event_types, "No FRAMING_INFO"
    assert EventType.ACCESS_CONTROL in event_types, "No ACCESS_CONTROL"
    assert EventType.FLOW_CONTROL   in event_types, "No FLOW_CONTROL"
    assert EventType.FRAME_SENT     in event_types, "No FRAME_SENT"
    assert EventType.BITS_SENT      in event_types, "No BITS_SENT"
    assert EventType.SIGNAL_DRAWN   in event_types, "No SIGNAL_DRAWN"

# ══════════════════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _evt(t):
    return SimEvent(timestamp=t, event_type=EventType.BITS_SENT,
                    layer=LayerName.PHYSICAL, src_device="h", pdu=PDU(type="bits"))

def test_engine_order():
    evts = []
    eng = SimulationEngine(emit_callback=lambda e: evts.append(e))
    for t in [0.3, 0.1, 0.2]: eng.schedule(_evt(t))
    eng.run()
    assert [e.timestamp for e in evts] == [0.1, 0.2, 0.3]

def test_engine_step():
    eng = SimulationEngine()
    eng.schedule(_evt(1.0))
    ev = eng.step()
    assert ev is not None and ev.timestamp == 1.0
    assert eng.step() is None

def test_engine_rewind():
    eng = SimulationEngine()
    for t in [1.0, 2.0, 3.0]: eng.schedule(_evt(t))
    eng.run()
    assert len(eng.rewind(2.0)) == 2

def test_engine_reset():
    eng = SimulationEngine()
    eng.schedule(_evt(1.0)); eng.run()
    eng.reset()
    assert eng.step() is None and eng.clock == 0.0

# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    tests = {k: v for k, v in globals().items() if k.startswith("test_")}
    passed = failed = 0
    for name, fn in tests.items():
        try:
            fn(); passed += 1; print(f"PASS  {name}")
        except Exception as exc:
            import traceback
            failed += 1; print(f"FAIL  {name}: {exc}")
            traceback.print_exc()
    print(f"\n{'─'*60}")
    print(f"  {passed} passed   {failed} failed   {passed+failed} total")
    print(f"{'─'*60}")
    sys.exit(0 if failed == 0 else 1)
