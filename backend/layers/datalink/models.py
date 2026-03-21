"""
layers/datalink/models.py  —  Data Link layer value objects.
EthernetFrame: immutable carrier for frames crossing the wire.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EthernetFrame:
    """Ethernet II frame – value object (immutable)."""
    dst_mac:  str
    src_mac:  str
    ether_type: int       # 0x0800=IP, 0x0806=ARP
    payload:  bytes
    fcs:      int = 0     # computed on creation; 0 = not yet computed

    # Ethernet II structure constants
    PREAMBLE    = b"\xAA" * 7
    SFD         = b"\xAB"
    MIN_PAYLOAD = 46
    MAX_PAYLOAD = 1500

    def to_bytes(self) -> bytes:
        dst  = bytes(int(x, 16) for x in self.dst_mac.split(":"))
        src  = bytes(int(x, 16) for x in self.src_mac.split(":"))
        etype = self.ether_type.to_bytes(2, "big")
        pad  = max(0, self.MIN_PAYLOAD - len(self.payload))
        return dst + src + etype + self.payload + b"\x00" * pad

    def to_dict(self) -> dict:
        return {
            "dst_mac":    self.dst_mac,
            "src_mac":    self.src_mac,
            "ether_type": hex(self.ether_type),
            "payload_len": len(self.payload),
            "fcs":        self.fcs,
        }


@dataclass(frozen=True)
class ARPPacket:
    """ARP request/reply value object."""
    op: int           # 1=request, 2=reply
    sender_mac: str
    sender_ip:  str
    target_mac: str   # ff:ff:ff:ff:ff:ff for requests
    target_ip:  str
