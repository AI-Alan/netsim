"""
devices/factory.py — DeviceFactory (Factory Method).
Add new device types to DEVICE_REGISTRY only — never modify factory core.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from devices.end_host import EndHost
from devices.base import NetworkDevice

logger = logging.getLogger(__name__)

DEVICE_REGISTRY: Dict[str, type] = {
    "end_host": EndHost,
    "computer": EndHost,
    "server":   EndHost,
    "laptop":   EndHost,
    "router":   EndHost,   # Phase 3: replace with Router class
    "switch":   EndHost,   # Phase 2: replace with Switch class
    "hub":      EndHost,
}

class DeviceFactory:
    @staticmethod
    def create(device_type: str, device_id: str, mac: str,
               ip: Optional[str] = None,
               layer_config: Optional[Dict[str, Any]] = None) -> NetworkDevice:
        cls = DEVICE_REGISTRY.get(device_type.lower(), EndHost)
        device = cls(device_id=device_id, mac=mac, ip=ip)
        device.configure_layers(layer_config or {})
        logger.info("DeviceFactory: %s id=%s", device_type, device_id)
        return device

    @staticmethod
    def available_types() -> List[str]:
        return list(DEVICE_REGISTRY.keys())
