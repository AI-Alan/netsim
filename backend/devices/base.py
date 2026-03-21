"""devices/base.py — NetworkDevice abstract base (TCP/IP layer ordering)."""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional
from layers.base import ILayerObserver, Layer, LayerPDU

logger = logging.getLogger(__name__)

class NetworkDevice(ABC):
    def __init__(self, device_id: str, mac: str, ip: Optional[str] = None) -> None:
        self.device_id = device_id; self.mac = mac; self.ip = ip
        self.layers: Dict[str, Layer] = {}

    def send(self, data, dst_ip=None, meta=None):
        pdu = LayerPDU(data=data, meta=meta or {})
        if dst_ip: pdu.meta["dst_ip"] = dst_ip
        pdu.meta.setdefault("src_device", self.device_id)
        top = self._get_top_layer()
        if top: top.send_down(pdu)

    def receive(self, raw_bits):
        pdu = LayerPDU(data=raw_bits, meta={"dst_device": self.device_id})
        bottom = self.layers.get("physical")
        if bottom: bottom.receive_up(pdu)

    def attach_observer(self, obs: ILayerObserver):
        for layer in self.layers.values(): layer.attach_observer(obs)

    def _get_top_layer(self):
        # TCP/IP order: application → transport → network → datalink → physical
        for name in ("application","transport","network","datalink","physical"):
            if name in self.layers: return self.layers[name]
        return None

    def _wire_layers(self):
        # TCP/IP 4-layer ordering (no separate session/presentation)
        order = ["physical","datalink","network","transport","application"]
        present = [n for n in order if n in self.layers]
        for i, name in enumerate(present):
            layer = self.layers[name]
            if i > 0: layer.set_lower(self.layers[present[i-1]])
            if i < len(present)-1: layer.set_upper(self.layers[present[i+1]])

    @abstractmethod
    def configure_layers(self, config: dict) -> None: ...

    def __repr__(self): return f"{self.__class__.__name__}(id={self.device_id})"
