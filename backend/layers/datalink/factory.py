"""layers/datalink/factory.py — Factory Method for DataLinkLayer."""
from __future__ import annotations
from layers.datalink.layer import DataLinkLayerImpl
from layers.datalink.framing import FRAMING_REGISTRY
from layers.datalink.error_control import ERROR_CONTROL_REGISTRY
from layers.datalink.access_control import MAC_REGISTRY
from layers.datalink.flow_control import FLOW_REGISTRY


class DataLinkLayerFactory:
    @staticmethod
    def create(
        device_id:   str  = "unknown",
        mac_addr:    str  = "00:00:00:00:00:00",
        framing:     str  = "variable",
        error:       str  = "crc32",
        mac_proto:   str  = "csma_cd",
        flow:        str  = "stop_and_wait",
        framing_kwargs: dict | None = None,
        flow_kwargs:    dict | None = None,
        mac_kwargs:     dict | None = None,
    ) -> DataLinkLayerImpl:
        framing_cls = FRAMING_REGISTRY.get(framing, FRAMING_REGISTRY["variable"])
        error_cls   = ERROR_CONTROL_REGISTRY.get(error, ERROR_CONTROL_REGISTRY["crc32"])
        mac_cls     = MAC_REGISTRY.get(mac_proto, MAC_REGISTRY["csma_cd"])
        flow_cls    = FLOW_REGISTRY.get(flow, FLOW_REGISTRY["stop_and_wait"])

        return DataLinkLayerImpl(
            device_id=device_id,
            mac_addr=mac_addr,
            framing=framing_cls(**(framing_kwargs or {})),
            error=error_cls(),
            mac=mac_cls(**(mac_kwargs or {})),
            flow=flow_cls(**(flow_kwargs or {})),
        )

    @staticmethod
    def available_options() -> dict:
        return {
            "framing":    list(FRAMING_REGISTRY.keys()),
            "error":      list(ERROR_CONTROL_REGISTRY.keys()),
            "mac_proto":  list(MAC_REGISTRY.keys()),
            "flow":       list(FLOW_REGISTRY.keys()),
        }
