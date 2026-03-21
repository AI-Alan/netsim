"""
layers/datalink/layer.py
-------------------------
DataLinkLayer — Template Method base + DataLinkLayerImpl.

Orchestrates (in order):
  send_down: MAC access → frame → error-control → emit FRAME_SENT
  receive_up: error-verify → deframe → emit FRAME_RECEIVED / FRAME_DROPPED

Composed strategies: IFraming, IErrorControl, IMACProtocol, IFlowControl.
Pattern: Template Method (skeleton) + Strategy (pluggable protocols) + Observer.
"""
from __future__ import annotations
import logging
from abc import abstractmethod
from typing import Optional

_HEX_PREVIEW_N = 64

from layers.base import Layer, LayerPDU
from layers.datalink.models import EthernetFrame, ARPPacket
from layers.datalink.framing import IFraming, FixedSizeFraming
from layers.datalink.error_control import IErrorControl, CRCErrorControl
from layers.datalink.access_control import IMACProtocol, CSMACD
from layers.datalink.flow_control import IFlowControl, StopAndWaitARQ
from simulation.events import EventType, LayerName, PDU, SimEvent

logger = logging.getLogger(__name__)


def _hex_preview(data: bytes, n: int = _HEX_PREVIEW_N) -> str:
    return data[:n].hex()


class DataLinkLayer(Layer):
    """Abstract Template Method for Data Link processing."""

    def __init__(self) -> None:
        super().__init__(layer_name="datalink")
        self._framing: IFraming             = FixedSizeFraming()
        self._error:   IErrorControl        = CRCErrorControl()
        self._mac:     IMACProtocol         = CSMACD()
        self._flow:    IFlowControl         = StopAndWaitARQ()
        self.device_id: str                 = "unknown"
        self.mac_addr:  str                 = "00:00:00:00:00:00"
        self._arp_table: dict[str, str]     = {}   # ip → mac
        self._mac_table: dict[str, str]     = {}   # mac → port/device (switch)

    # ── Template Method: send ─────────────────────────────────────────────
    def _do_send(self, pdu: LayerPDU) -> None:
        payload   = self._to_bytes(pdu)
        dst_mac   = pdu.meta.get("dst_mac", "ff:ff:ff:ff:ff:ff")
        ts        = pdu.meta.get("timestamp", 0.0)

        # 1. Framing info event
        framed_raw = self._framing.frame(payload)
        self.emit(SimEvent(
            timestamp=ts, event_type=EventType.FRAMING_INFO,
            layer=LayerName.DATALINK, src_device=self.device_id,
            pdu=PDU(type="framing", headers={
                "scheme":       self._framing.name,
                "raw_bytes":    len(payload),
                "framed_bytes": len(framed_raw),
                "payload_hex_preview": _hex_preview(payload),
                "framed_hex_preview": _hex_preview(framed_raw),
            }),
            meta={"detail": f"Framing: {self._framing.name}"},
        ))

        # 2. MAC access control
        mac_result = self._mac.transmit(
            channel_busy=pdu.meta.get("channel_busy", False),
            collision_prob=pdu.meta.get("collision_prob", 0.02),
        )
        self.emit(SimEvent(
            timestamp=ts, event_type=EventType.ACCESS_CONTROL,
            layer=LayerName.DATALINK, src_device=self.device_id,
            pdu=PDU(type="mac", headers={
                "protocol":      self._mac.name,
                "transmitted":   mac_result.transmitted,
                "attempts":      mac_result.attempts,
                "collision":     mac_result.collision,
                "rts_cts_used":  mac_result.rts_cts_used,
                "steps":         mac_result.steps,
            }),
            meta={"detail": mac_result.detail},
        ))

        if not mac_result.transmitted:
            self.emit(SimEvent(
                timestamp=ts, event_type=EventType.FRAME_DROPPED,
                layer=LayerName.DATALINK, src_device=self.device_id,
                pdu=PDU(type="frame", headers={"reason": "MAC access failed"}),
            ))
            return

        # 3. Error control: append check bits
        protected = self._error.compute(framed_raw)

        if pdu.meta.get("inject_error") and len(protected) > 0:
            buf = bytearray(protected)
            oh = int(self._error.overhead_bytes or 0)
            pay_len = max(0, len(buf) - oh)
            idx = (pay_len // 2) if pay_len else 0
            idx = min(idx, len(buf) - 1)
            buf[idx] ^= 0xAA
            protected = bytes(buf)
            vr = self._error.verify(protected)
            detail = vr.detail
            if vr.ok and self._error.name == "None":
                detail = "Payload corrupted — no error control; corruption is undetectable"
            self.emit(SimEvent(
                timestamp=ts, event_type=EventType.ERROR_DETECTED,
                layer=LayerName.DATALINK, src_device=self.device_id,
                pdu=PDU(type="error", headers={
                    "scheme":       self._error.name,
                    "detail":       detail,
                    "dropped":      vr.dropped,
                    "injected":     True,
                }),
                meta={"detail": "Educational: intentional bit flip after FCS/checksum"},
            ))
            if vr.dropped:
                self.emit(SimEvent(
                    timestamp=ts, event_type=EventType.FRAME_DROPPED,
                    layer=LayerName.DATALINK, src_device=self.device_id,
                    pdu=PDU(type="frame", headers={"reason": vr.detail}),
                ))
                return

        # 4. Build Ethernet frame
        frame = EthernetFrame(
            dst_mac=dst_mac, src_mac=self.mac_addr,
            ether_type=0x0800, payload=protected,
        )
        pdu.meta["ethernet_frame"] = frame

        # 5. Flow control: ARQ simulation (1 logical frame here)
        flow_result = self._flow.transfer(total_frames=1,
                                          error_rate=pdu.meta.get("link_error_rate", 0.0))
        self.emit(SimEvent(
            timestamp=ts, event_type=EventType.FLOW_CONTROL,
            layer=LayerName.DATALINK, src_device=self.device_id,
            pdu=PDU(type="arq", headers={
                "protocol":       self._flow.name,
                "window_size":    self._flow.window_size,
                "frames_sent":    flow_result.frames_sent,
                "retransmissions":flow_result.retransmissions,
                "efficiency":     round(flow_result.efficiency, 4),
                "steps":          flow_result.steps,
            }),
            meta={"detail": flow_result.detail},
        ))

        # 6. FRAME_SENT
        wire_bytes = frame.to_bytes()
        self.emit(SimEvent(
            timestamp=ts, event_type=EventType.FRAME_SENT,
            layer=LayerName.DATALINK, src_device=self.device_id,
            dst_device=pdu.meta.get("dst_device"),
            pdu=PDU(type="frame", headers={
                **frame.to_dict(),
                "error_scheme":   self._error.name,
                "framing_scheme": self._framing.name,
                "mac_protocol":   self._mac.name,
                "arq_protocol":   self._flow.name,
                "protected_len":  len(protected),
                "protected_hex_preview": _hex_preview(protected),
                "on_wire_hex_preview": _hex_preview(wire_bytes),
            }),
        ))

        # 7. Pass down
        pdu.data = wire_bytes
        if self._lower:
            self._lower.send_down(pdu)

    # ── Template Method: receive ──────────────────────────────────────────
    def _do_receive(self, pdu: LayerPDU) -> None:
        raw = self._to_bytes(pdu)
        ts  = pdu.meta.get("timestamp", 0.0)

        # 1. Error check
        result = self._error.verify(raw)
        if not result.ok:
            self.emit(SimEvent(
                timestamp=ts, event_type=EventType.ERROR_DETECTED,
                layer=LayerName.DATALINK, src_device=self.device_id,
                pdu=PDU(type="error", headers={
                    "scheme":  self._error.name,
                    "detail":  result.detail,
                    "dropped": result.dropped,
                }),
            ))
            if result.dropped:
                self.emit(SimEvent(
                    timestamp=ts, event_type=EventType.FRAME_DROPPED,
                    layer=LayerName.DATALINK, src_device=self.device_id,
                    pdu=PDU(type="frame", headers={"reason": result.detail}),
                ))
                return

        # 2. Deframe
        payload_checked = raw[: -self._error.overhead_bytes] if self._error.overhead_bytes else raw
        payload = self._framing.deframe(payload_checked)

        # 3. FRAME_RECEIVED
        txt_preview = payload.decode("utf-8", errors="replace")[:200]
        self.emit(SimEvent(
            timestamp=ts, event_type=EventType.FRAME_RECEIVED,
            layer=LayerName.DATALINK, src_device=self.device_id,
            pdu=PDU(type="frame", headers={
                "error_check": result.detail,
                "payload_len": len(payload),
                "payload_hex_preview": _hex_preview(payload),
                "payload_text_preview": txt_preview,
            }),
        ))

        pdu.data = payload
        if self._upper:
            self._upper.receive_up(pdu)

    # ── Helpers ───────────────────────────────────────────────────────────
    def _to_bytes(self, pdu: LayerPDU) -> bytes:
        d = pdu.data
        if isinstance(d, bytes): return d
        if isinstance(d, str):   return d.encode()
        if isinstance(d, (list, tuple)): return bytes(d)
        return str(d).encode()

    @abstractmethod
    def _validate_config(self) -> None: ...


class DataLinkLayerImpl(DataLinkLayer):
    def __init__(
        self,
        device_id:  str                 = "unknown",
        mac_addr:   str                 = "00:00:00:00:00:00",
        framing:    Optional[IFraming]  = None,
        error:      Optional[IErrorControl] = None,
        mac:        Optional[IMACProtocol]  = None,
        flow:       Optional[IFlowControl]  = None,
    ) -> None:
        super().__init__()
        self.device_id = device_id
        self.mac_addr  = mac_addr
        if framing: self._framing = framing
        if error:   self._error   = error
        if mac:     self._mac     = mac
        if flow:    self._flow    = flow
        self._validate_config()

    def _validate_config(self) -> None:
        pass   # all have defaults

    def set_framing(self, f: IFraming) -> None:          self._framing = f
    def set_error_control(self, e: IErrorControl) -> None: self._error = e
    def set_mac_protocol(self, m: IMACProtocol) -> None:  self._mac   = m
    def set_flow_control(self, f: IFlowControl) -> None:  self._flow  = f
