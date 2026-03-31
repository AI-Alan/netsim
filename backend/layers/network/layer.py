"""layers/network/layer.py — Network Layer (IP forwarding, routing)."""
from __future__ import annotations
import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from layers.base import Layer, LayerPDU
from simulation.events import EventType, LayerName, PDU, SimEvent

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class IPPacket:
    src_ip: str; dst_ip: str; ttl: int; protocol: int; payload: bytes
    def to_dict(self):
        return {"src_ip":self.src_ip,"dst_ip":self.dst_ip,"ttl":self.ttl,
                "protocol":self.protocol,"payload_len":len(self.payload)}

@dataclass
class RoutingEntry:
    network: str; mask: str; next_hop: Optional[str]; metric: int = 1; interface: str = "eth0"

def _ip_to_int(ip: str) -> int:
    parts = ip.strip().split(".")
    result = 0
    for p in parts:
        result = (result << 8) | (int(p) & 0xFF)
    return result

def _mask_to_int(mask: str) -> int:
    if "/" in mask:
        bits = int(mask.lstrip("/"))
        return (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
    return _ip_to_int(mask)

@dataclass
class RoutingTable:
    entries: list = field(default_factory=list)
    def lookup(self, dst_ip):
        try:
            dst_int = _ip_to_int(dst_ip)
        except (ValueError, AttributeError):
            return None
        best: Optional[RoutingEntry] = None
        best_prefix_len = -1
        for e in self.entries:
            try:
                net_int = _ip_to_int(e.network)
                mask_int = _mask_to_int(e.mask)
                if (dst_int & mask_int) == (net_int & mask_int):
                    prefix_len = bin(mask_int).count("1")
                    if prefix_len > best_prefix_len:
                        best_prefix_len = prefix_len
                        best = e
            except (ValueError, AttributeError):
                continue
        return best

class NetworkLayer(Layer):
    def __init__(self):
        super().__init__(layer_name="network")
        self.device_id = "unknown"; self.device_ip = "0.0.0.0"
        self._routing_table = RoutingTable()

    def _do_send(self, pdu: LayerPDU):
        dst_ip = pdu.meta.get("dst_ip","255.255.255.255")
        ts = pdu.meta.get("timestamp",0.0)
        payload = pdu.data if isinstance(pdu.data,bytes) else str(pdu.data).encode()
        entry = self._routing_table.lookup(dst_ip)
        next_hop = entry.next_hop if entry else dst_ip
        self.emit(SimEvent(timestamp=ts,event_type=EventType.ROUTING_LOOKUP,
            layer=LayerName.NETWORK,src_device=self.device_id,
            pdu=PDU(type="routing",headers={"dst_ip":dst_ip,"next_hop":next_hop,
                "metric":entry.metric if entry else 0,"table_entries":len(self._routing_table.entries)})))
        self.emit(SimEvent(timestamp=ts,event_type=EventType.PACKET_SENT,
            layer=LayerName.NETWORK,src_device=self.device_id,
            dst_device=pdu.meta.get("dst_device"),
            pdu=PDU(type="ip_packet",headers=IPPacket(src_ip=self.device_ip,dst_ip=dst_ip,
                ttl=64,protocol=6,payload=payload).to_dict())))
        pdu.data=payload; pdu.meta["dst_mac"]=pdu.meta.get("dst_mac","ff:ff:ff:ff:ff:ff")
        if self._lower: self._lower.send_down(pdu)

    def _do_receive(self, pdu: LayerPDU):
        ts = pdu.meta.get("timestamp",0.0)
        self.emit(SimEvent(timestamp=ts,event_type=EventType.PACKET_RECEIVED,
            layer=LayerName.NETWORK,src_device=self.device_id,
            pdu=PDU(type="ip_packet",headers={"dst_ip":self.device_ip})))
        if self._upper: self._upper.receive_up(pdu)

    def add_route(self,network,mask,next_hop=None,metric=1):
        self._routing_table.entries.append(RoutingEntry(network=network,mask=mask,next_hop=next_hop,metric=metric))

    @abstractmethod
    def _validate_config(self): ...

class NetworkLayerImpl(NetworkLayer):
    def __init__(self,device_id="unknown",device_ip="0.0.0.0"):
        super().__init__(); self.device_id=device_id; self.device_ip=device_ip; self._validate_config()
    def _validate_config(self): pass
