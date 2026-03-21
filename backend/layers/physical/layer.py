"""
layers/physical/layer.py
-------------------------
PhysicalLayer (abstract Template Method) + PhysicalLayerImpl (concrete).

Design Patterns:
  - Template Method: fixed send/receive skeleton; subclasses override hooks
  - Strategy: encoder and medium are injected
  - Observer: emits BITS_SENT, SIGNAL_DRAWN, BITS_RECEIVED SimEvents
"""
from __future__ import annotations
import logging
from abc import abstractmethod
from typing import Optional
from layers.base import Layer, LayerPDU
from layers.physical.encoding import IEncodingStrategy
from layers.physical.medium import ITransmissionMedium
from layers.physical.models import Bits, Signal
from simulation.events import EventType, LayerName, PDU, SimEvent

logger = logging.getLogger(__name__)


class PhysicalLayer(Layer):
    """Abstract Template Method base."""

    def __init__(self) -> None:
        super().__init__(layer_name="physical")
        self._encoder:  Optional[IEncodingStrategy]   = None
        self._medium:   Optional[ITransmissionMedium] = None
        self.device_id: str = "unknown"
        self.clock_rate: int = 1000

    # ── Template Method skeleton ────────────────────────────────────────
    def _do_send(self, pdu: LayerPDU) -> None:
        bits = self._to_bits(pdu)
        bits = self._pre_encode(bits)
        self.emit(self._bits_sent_event(bits, pdu))
        signal = self._encoder.encode(bits, self.clock_rate)
        transmitted = self._medium.transmit(signal)
        self.emit(self._signal_drawn_event(transmitted, pdu))
        pdu.meta["transmitted_signal"] = transmitted

    def _do_receive(self, pdu: LayerPDU) -> None:
        signal = self._to_signal(pdu)
        bits = self._encoder.decode(signal)
        bits = self._post_decode(bits)
        self.emit(self._bits_received_event(bits, pdu))
        pdu.data = bits
        if self._upper:
            self._upper.receive_up(pdu)

    # ── Hooks (OCP: override without modifying) ─────────────────────────
    def _pre_encode(self, bits: Bits) -> Bits:   return bits
    def _post_decode(self, bits: Bits) -> Bits:  return bits

    # ── Helpers ──────────────────────────────────────────────────────────
    def _to_bits(self, pdu: LayerPDU) -> Bits:
        d = pdu.data
        if isinstance(d, Bits):   return d
        if isinstance(d, (list, tuple)): return Bits.from_list(list(d))
        if isinstance(d, bytes):  return Bits.from_bytes(d)
        if isinstance(d, str):    return Bits.from_str(d)
        raise TypeError(f"Cannot convert {type(d)} to Bits")

    def _to_signal(self, pdu: LayerPDU) -> Signal:
        d = pdu.data
        if isinstance(d, Signal): return d
        if "transmitted_signal" in pdu.meta: return pdu.meta["transmitted_signal"]
        raise TypeError(f"Expected Signal, got {type(d)}")

    def _ts(self, pdu: LayerPDU) -> float:
        return pdu.meta.get("timestamp", 0.0)

    def _bits_sent_event(self, bits: Bits, pdu: LayerPDU) -> SimEvent:
        return SimEvent(
            timestamp=self._ts(pdu), event_type=EventType.BITS_SENT,
            layer=LayerName.PHYSICAL, src_device=self.device_id,
            dst_device=pdu.meta.get("dst_device"),
            pdu=PDU(type="bits", headers={
                "raw_bits": bits.to_str(),
                "encoding": self._encoder.name,
                "clock_rate": self.clock_rate,
            }),
        )

    def _signal_drawn_event(self, signal: Signal, pdu: LayerPDU) -> SimEvent:
        return SimEvent(
            timestamp=self._ts(pdu), event_type=EventType.SIGNAL_DRAWN,
            layer=LayerName.PHYSICAL, src_device=self.device_id,
            dst_device=pdu.meta.get("dst_device"),
            pdu=PDU(type="signal", headers={
                "encoding": signal.encoding,
                "sample_rate": signal.sample_rate,
            }),
            signal=signal.to_dict(),
        )

    def _bits_received_event(self, bits: Bits, pdu: LayerPDU) -> SimEvent:
        return SimEvent(
            timestamp=self._ts(pdu), event_type=EventType.BITS_RECEIVED,
            layer=LayerName.PHYSICAL, src_device=self.device_id,
            pdu=PDU(type="bits", headers={
                "raw_bits": bits.to_str(),
                "error_detected": pdu.meta.get("error_detected", False),
            }),
        )

    @abstractmethod
    def _validate_config(self) -> None: ...


class PhysicalLayerImpl(PhysicalLayer):
    """Fully wired, ready-to-use physical layer."""

    def __init__(self, encoder: IEncodingStrategy, medium: ITransmissionMedium,
                 device_id: str = "unknown", clock_rate: int = 1000) -> None:
        super().__init__()
        self._encoder   = encoder
        self._medium    = medium
        self.device_id  = device_id
        self.clock_rate = clock_rate
        self._validate_config()

    def _validate_config(self) -> None:
        assert self._encoder is not None, "Need IEncodingStrategy"
        assert self._medium  is not None, "Need ITransmissionMedium"

    def set_encoder(self, encoder: IEncodingStrategy) -> None:
        self._encoder = encoder

    def set_medium(self, medium: ITransmissionMedium) -> None:
        self._medium = medium
