"""
tests/test_physical_layer.py
Run with: python -m pytest tests/ -v     (after: pip install pytest)
     or:  python tests/test_physical_layer.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from layers.physical.models import Bits, Signal
from layers.physical.encoding import (NRZEncoding, NRZIEncoding, ManchesterEncoding,
    DiffManchesterEncoding, AMIEncoding, FourBFiveBEncoding, ENCODING_REGISTRY)
from layers.physical.medium import WiredMedium, WirelessMedium, MEDIUM_REGISTRY
from layers.physical.factory import PhysicalLayerFactory
from layers.base import ILayerObserver, LayerPDU
from simulation.events import SimEvent, EventType, LayerName, PDU
from simulation.engine import SimulationEngine

BITS = Bits.from_list([1,0,1,1,0,1,0,0])
BS   = [1,0,1,1,0,1,0,0]

# ── Value Objects ───────────────────────────────────────────────────────────
def test_bits_bytes_round_trip():
    b = Bits.from_bytes(b"\xDE\xAD\xBE\xEF")
    assert b.to_bytes() == b"\xDE\xAD\xBE\xEF"

def test_bits_rejects_invalid():
    try: Bits.from_list([0,1,2]); assert False
    except ValueError: pass

def test_signal_rejects_out_of_range():
    try: Signal.from_list([1.5], 100, "t"); assert False
    except ValueError: pass

def test_signal_to_dict():
    s = Signal.from_list([1.0,-1.0,0.0], 100, "NRZ-L")
    assert s.to_dict()["encoding"] == "NRZ-L"

# ── Encoding round-trips ────────────────────────────────────────────────────
def _rt(cls):
    enc = cls(); sig = enc.encode(BITS, 100)
    assert all(-1.0 <= s <= 1.0 for s in sig.samples), f"{cls.__name__} out-of-range"
    assert list(enc.decode(sig).data) == BS, f"{cls.__name__} decode mismatch"

def test_nrzl():  _rt(NRZEncoding)
def test_nrzi():  _rt(NRZIEncoding)
def test_man():   _rt(ManchesterEncoding)
def test_diff():  _rt(DiffManchesterEncoding)
def test_ami():   _rt(AMIEncoding)

def test_4b5b():
    enc4 = FourBFiveBEncoding()
    b4   = Bits.from_list([1,0,1,1,0,1,0,0,1,1,1,0])
    r    = list(enc4.decode(enc4.encode(b4, 100)).data[:12])
    assert r == [1,0,1,1,0,1,0,0,1,1,1,0]

def test_encoding_registry_complete():
    assert set(ENCODING_REGISTRY) == {"NRZ-L","NRZ-I","Manchester","Differential Manchester","AMI","4B5B"}

# ── Medium ──────────────────────────────────────────────────────────────────
def test_wired_no_ber():
    sig = NRZEncoding().encode(BITS)
    assert WiredMedium(ber=0.0).transmit(sig).samples == sig.samples

def test_wired_ber():
    import random; random.seed(99)
    big   = NRZEncoding().encode(Bits.from_list([1]*1000))
    noisy = WiredMedium(ber=0.5).transmit(big)
    diffs = sum(1 for a,b in zip(big.samples, noisy.samples) if a != b)
    assert diffs > 100

def test_wireless_normalised():
    sig = NRZEncoding().encode(BITS)
    out = WirelessMedium().transmit(sig)
    assert len(out.samples) == len(sig.samples)
    assert all(-1.0 <= s <= 1.0 for s in out.samples)

# ── Factory ─────────────────────────────────────────────────────────────────
def test_factory_create():
    assert PhysicalLayerFactory.create("Manchester","wired",device_id="h") is not None

def test_factory_bad_encoding():
    try: PhysicalLayerFactory.create("BOGUS","wired"); assert False
    except ValueError: pass

def test_factory_bad_medium():
    try: PhysicalLayerFactory.create("NRZ-L","BOGUS"); assert False
    except ValueError: pass

# ── Observer + Events ────────────────────────────────────────────────────────
def _collect():
    events = []
    class Obs(ILayerObserver):
        def on_event(self, e): events.append(e)
    layer = PhysicalLayerFactory.create("NRZ-L","wired",device_id="h")
    layer.attach_observer(Obs())
    layer.send_down(LayerPDU(data=BITS, meta={"src_device":"h","dst_device":"r","timestamp":0.5}))
    return events

def test_emits_bits_sent():
    assert any(e.event_type == EventType.BITS_SENT for e in _collect())

def test_emits_signal_drawn():
    assert any(e.event_type == EventType.SIGNAL_DRAWN for e in _collect())

def test_signal_drawn_sample_count():
    ev = next(e for e in _collect() if e.event_type == EventType.SIGNAL_DRAWN)
    assert len(ev.signal["samples"]) == 800   # 8 bits × 100 spb

def test_bits_sent_headers():
    ev = next(e for e in _collect() if e.event_type == EventType.BITS_SENT)
    assert ev.pdu.headers["raw_bits"] == "10110100"
    assert ev.pdu.headers["encoding"] == "NRZ-L"

def test_timestamp_propagated():
    ev = next(e for e in _collect() if e.event_type == EventType.SIGNAL_DRAWN)
    assert ev.timestamp == 0.5

# ── SimulationEngine ─────────────────────────────────────────────────────────
def _make_event(t):
    return SimEvent(timestamp=t, event_type=EventType.BITS_SENT,
                    layer=LayerName.PHYSICAL, src_device="h", pdu=PDU(type="bits"))

def test_engine_order():
    evts = []
    eng  = SimulationEngine(emit_callback=lambda e: evts.append(e))
    for t in [0.3, 0.1, 0.2]:
        eng.schedule(_make_event(t))
    eng.run()
    assert [e.timestamp for e in evts] == [0.1, 0.2, 0.3]

def test_engine_step():
    eng = SimulationEngine()
    eng.schedule(_make_event(1.0))
    ev  = eng.step()
    assert ev is not None and ev.timestamp == 1.0
    assert eng.step() is None

def test_engine_rewind():
    eng = SimulationEngine()
    for t in [1.0, 2.0, 3.0]:
        eng.schedule(_make_event(t))
    eng.run()
    assert len(eng.rewind(2.0)) == 2

if __name__ == "__main__":
    import sys
    tests = {k: v for k, v in globals().items() if k.startswith("test_")}
    passed = 0; failed = 0
    for name, fn in tests.items():
        try:
            fn(); passed += 1; print(f"PASS  {name}")
        except Exception as exc:
            failed += 1; print(f"FAIL  {name}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
