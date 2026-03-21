"""
layers/network/models.py  —  Network layer value objects.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class IPPacket:
    src_ip:   str
    dst_ip:   str
    ttl:      int
    protocol: int        # 6=TCP, 17=UDP, 1=ICMP
    payload:  bytes
    version:  int = 4
    dscp:     int = 0

    def to_dict(self) -> dict:
        return {
            "src_ip": self.src_ip, "dst_ip": self.dst_ip,
            "ttl": self.ttl, "protocol": self.protocol,
            "version": self.version, "payload_len": len(self.payload),
        }


@dataclass
class RoutingEntry:
    network:    str
    mask:       str
    next_hop:   str
    metric:     int
    interface:  str


@dataclass
class RoutingTable:
    entries: list[RoutingEntry] = field(default_factory=list)

    def lookup(self, dst_ip: str) -> Optional[RoutingEntry]:
        best: Optional[RoutingEntry] = None
        for e in self.entries:
            if self._matches(dst_ip, e.network, e.mask):
                if best is None or e.metric < best.metric:
                    best = e
        return best

    @staticmethod
    def _matches(ip: str, network: str, mask: str) -> bool:
        try:
            def to_int(a: str) -> int:
                p = [int(x) for x in a.split(".")]
                return (p[0]<<24)|(p[1]<<16)|(p[2]<<8)|p[3]
            m = to_int(mask)
            return (to_int(ip) & m) == (to_int(network) & m)
        except Exception:
            return False
