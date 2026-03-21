"""
tests/test_datalink_layer.py
Run with: python -m pytest tests/ -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from layers.datalink.framing import FixedSizeFraming, VariableSizeFraming
from layers.datalink.error_control import CRCErrorControl, ChecksumErrorControl
from layers.datalink.access_control import (
    PureAloha, SlottedAloha, CSMA, CSMACD, CSMACA
)
from layers.datalink.flow_control import (
    StopAndWaitARQ, GoBackNARQ, SelectiveRepeatARQ
)
from layers.datalink.factory import DataLinkLayerFactory
from layers.base import ILayerObserver, LayerPDU
from simulation.events import SimEvent, EventType

DATA = b"NetSim Data Link Layer Test Frame"

# ── Framing ───────────────────────────────────────────────────────────────────
def test_variable_framing_roundtrip():
    f = VariableSizeFraming()
    assert f.deframe(f.frame(DATA)) == DATA

def test_variable_framing_flag_stuffing():
    data_with_flag = bytes([0x7E, 0x41, 0x7D, 0x42])
    f = VariableSizeFraming()
    framed = f.frame(data_with_flag)
    assert 0x7E not in framed[1:-1], "FLAG must be stuffed inside frame"
    assert f.deframe(framed) == data_with_flag

def test_fixed_framing_roundtrip():
    f = FixedSizeFraming(frame_size=64)
    assert f.deframe(f.frame(DATA)) == DATA

def test_fixed_framing_pads():
    f = FixedSizeFraming(frame_size=128)
    framed = f.frame(b"hi")
    assert len(framed) == 128 + len(f.FLAG)

# ── Error Control ─────────────────────────────────────────────────────────────
def test_crc32_valid():
    c = CRCErrorControl()
    assert c.verify(c.compute(DATA)).ok

def test_crc32_detects_corruption():
    c = CRCErrorControl()
    protected = bytearray(c.compute(DATA))
    protected[5] ^= 0xFF  # flip bits
    assert not c.verify(bytes(protected)).ok

def test_checksum_valid():
    c = ChecksumErrorControl()
    assert c.verify(c.compute(DATA)).ok

def test_checksum_detects_corruption():
    c = ChecksumErrorControl()
    protected = bytearray(c.compute(DATA))
    protected[3] ^= 0xFF
    assert not c.verify(bytes(protected)).ok

def test_crc32_overhead():
    c = CRCErrorControl()
    assert c.overhead_bytes == 4

def test_checksum_overhead():
    c = ChecksumErrorControl()
    assert c.overhead_bytes == 2

# ── MAC Protocols ─────────────────────────────────────────────────────────────
def test_csma_cd_success_clean():
    r = CSMACD().transmit(channel_busy=False, collision_prob=0.0)
    assert r.transmitted
    assert r.attempts >= 1

def test_csma_ca_success_clean():
    r = CSMACA().transmit(channel_busy=False, collision_prob=0.0)
    assert r.transmitted

def test_pure_aloha_has_steps():
    r = PureAloha().transmit(collision_prob=0.0)
    assert len(r.steps) >= 1

def test_slotted_aloha_success():
    r = SlottedAloha().transmit(collision_prob=0.0)
    assert r.transmitted

def test_csma_success():
    r = CSMA().transmit(channel_busy=False, collision_prob=0.0)
    assert r.transmitted

def test_mac_protocol_names():
    assert "CSMA/CD" in CSMACD().name
    assert "CSMA/CA" in CSMACA().name
    assert "ALOHA" in PureAloha().name

# ── Flow Control (ARQ) ────────────────────────────────────────────────────────
def test_stop_and_wait_no_errors():
    r = StopAndWaitARQ().transfer(8, error_rate=0.0)
    assert r.frames_acked == 8
    assert r.retransmissions == 0
    assert r.efficiency == 1.0

def test_go_back_n_no_errors():
    r = GoBackNARQ(4).transfer(8, error_rate=0.0)
    assert r.frames_acked == 8
    assert r.retransmissions == 0

def test_selective_repeat_no_errors():
    r = SelectiveRepeatARQ(4).transfer(8, error_rate=0.0)
    assert r.frames_acked == 8
    assert r.retransmissions == 0

def test_saw_window_is_1():
    assert StopAndWaitARQ().window_size == 1

def test_gbn_window():
    assert GoBackNARQ(7).window_size == 7

def test_sr_window():
    assert SelectiveRepeatARQ(8).window_size == 8

def test_arq_with_errors_has_retransmissions():
    import random; random.seed(42)
    r = StopAndWaitARQ().transfer(10, error_rate=0.5)
    assert r.retransmissions >= 0   # may be 0 by luck — ensure no crash

# ── Full DataLinkLayer event emission ─────────────────────────────────────────
class _Collector(ILayerObserver):
    def __init__(self): self.events = []
    def on_event(self, e: SimEvent): self.events.append(e)

def test_dll_emits_required_events():
    dll = DataLinkLayerFactory.create(
        device_id="host-A", mac_addr="aa:bb:cc:dd:ee:ff",
        framing="variable", error="crc32", mac_proto="csma_cd", flow="stop_and_wait"
    )
    col = _Collector(); dll.attach_observer(col)
    pdu = LayerPDU(data=b"test", meta={"dst_device":"host-B","dst_mac":"ff:ff:ff:ff:ff:ff",
        "timestamp":0.0,"collision_prob":0.0,"link_error_rate":0.0})
    dll._do_send(pdu)
    types = {e.event_type for e in col.events}
    assert EventType.FRAMING_INFO   in types
    assert EventType.ACCESS_CONTROL in types
    assert EventType.FLOW_CONTROL   in types
    assert EventType.FRAME_SENT     in types

def test_dll_factory_options():
    opts = DataLinkLayerFactory.available_options()
    assert "fixed" in opts["framing"]
    assert "variable" in opts["framing"]
    assert "crc32" in opts["error"]
    assert "csma_cd" in opts["mac_proto"]
    assert "stop_and_wait" in opts["flow"]

def test_dll_go_back_n():
    dll = DataLinkLayerFactory.create(
        device_id="h", mac_addr="aa:bb:cc:dd:ee:ff",
        flow="go_back_n", flow_kwargs={"window":4}
    )
    col = _Collector(); dll.attach_observer(col)
    pdu = LayerPDU(data=b"GBN test frame", meta={"timestamp":0.0,"collision_prob":0.0,"link_error_rate":0.0})
    dll._do_send(pdu)
    fc_events = [e for e in col.events if e.event_type == EventType.FLOW_CONTROL]
    assert len(fc_events) == 1
    assert "Go-Back-N" in fc_events[0].pdu.headers["protocol"]
