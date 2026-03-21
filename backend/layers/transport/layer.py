"""layers/transport/layer.py — Transport Layer (TCP state machine, UDP)."""
from __future__ import annotations
import logging
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from layers.base import Layer, LayerPDU
from simulation.events import EventType, LayerName, PDU, SimEvent

logger = logging.getLogger(__name__)

class TCPState(str, Enum):
    CLOSED=("CLOSED"); LISTEN="LISTEN"; SYN_SENT="SYN_SENT"
    SYN_RECEIVED="SYN_RECEIVED"; ESTABLISHED="ESTABLISHED"
    FIN_WAIT_1="FIN_WAIT_1"; FIN_WAIT_2="FIN_WAIT_2"
    TIME_WAIT="TIME_WAIT"; CLOSE_WAIT="CLOSE_WAIT"; LAST_ACK="LAST_ACK"

@dataclass(frozen=True)
class TCPSegment:
    src_port:int; dst_port:int; seq:int; ack:int
    flags:str; window:int; payload:bytes
    def to_dict(self):
        return {"src_port":self.src_port,"dst_port":self.dst_port,
                "seq":self.seq,"ack":self.ack,"flags":self.flags,
                "window":self.window,"payload_len":len(self.payload)}

class TransportLayer(Layer):
    def __init__(self):
        super().__init__(layer_name="transport")
        self.device_id="unknown"; self._tcp_state=TCPState.CLOSED
        self._seq=0; self._ack=0

    def _emit_tcp_state(self,old,new,ts):
        self.emit(SimEvent(timestamp=ts,event_type=EventType.TCP_STATE,
            layer=LayerName.TRANSPORT,src_device=self.device_id,
            pdu=PDU(type="tcp_state",headers={"old_state":old.value,"new_state":new.value})))
        self._tcp_state=new

    def _do_send(self, pdu:LayerPDU):
        ts=pdu.meta.get("timestamp",0.0)
        payload=pdu.data if isinstance(pdu.data,bytes) else str(pdu.data).encode()
        proto=pdu.meta.get("transport_proto","tcp")
        if proto=="tcp":
            old=self._tcp_state
            self._emit_tcp_state(old,TCPState.SYN_SENT,ts)
            self._emit_tcp_state(TCPState.SYN_SENT,TCPState.ESTABLISHED,ts)
            seg=TCPSegment(src_port=pdu.meta.get("src_port",12345),
                dst_port=pdu.meta.get("dst_port",80),
                seq=self._seq,ack=self._ack,flags="SYN|ACK",window=65535,payload=payload)
            self.emit(SimEvent(timestamp=ts,event_type=EventType.SEGMENT_SENT,
                layer=LayerName.TRANSPORT,src_device=self.device_id,
                dst_device=pdu.meta.get("dst_device"),
                pdu=PDU(type="tcp_segment",headers=seg.to_dict())))
        else:
            self.emit(SimEvent(timestamp=ts,event_type=EventType.SEGMENT_SENT,
                layer=LayerName.TRANSPORT,src_device=self.device_id,
                pdu=PDU(type="udp_datagram",headers={"src_port":pdu.meta.get("src_port",12345),
                    "dst_port":pdu.meta.get("dst_port",53),"len":len(payload)})))
        pdu.data=payload
        if self._lower: self._lower.send_down(pdu)

    def _do_receive(self, pdu:LayerPDU):
        ts=pdu.meta.get("timestamp",0.0)
        self.emit(SimEvent(timestamp=ts,event_type=EventType.SEGMENT_RECEIVED,
            layer=LayerName.TRANSPORT,src_device=self.device_id,
            pdu=PDU(type="segment",headers={"state":self._tcp_state.value})))
        if self._upper: self._upper.receive_up(pdu)

    @abstractmethod
    def _validate_config(self): ...

class TransportLayerImpl(TransportLayer):
    def __init__(self,device_id="unknown"):
        super().__init__(); self.device_id=device_id; self._validate_config()
    def _validate_config(self): pass
