"""devices/end_host.py — EndHost with all TCP/IP layers wired."""
from __future__ import annotations
from typing import Optional
from devices.base import NetworkDevice
from layers.physical.factory import PhysicalLayerFactory
from layers.datalink.factory import DataLinkLayerFactory
from layers.network.layer import NetworkLayerImpl
from layers.transport.layer import TransportLayerImpl
from layers.application.layer import ApplicationLayerImpl

class EndHost(NetworkDevice):
    def configure_layers(self, config: dict) -> None:
        phy_cfg = config.get("physical", {})
        dll_cfg = config.get("datalink", {})
        net_cfg = config.get("network", {})

        # Physical
        phy = PhysicalLayerFactory.create(
            encoding_type   = phy_cfg.get("encoding", "NRZ-L"),
            medium_type     = phy_cfg.get("medium", "wired"),
            device_id       = self.device_id,
            clock_rate      = phy_cfg.get("clock_rate", 1000),
            samples_per_bit = phy_cfg.get("samples_per_bit", 100),
            medium_kwargs   = phy_cfg.get("medium_kwargs", {}),
        )
        self.layers["physical"] = phy

        # Data Link
        dll = DataLinkLayerFactory.create(
            device_id  = self.device_id,
            mac_addr   = self.mac,
            framing    = dll_cfg.get("framing", "variable"),
            error      = dll_cfg.get("error", "crc32"),
            mac_proto  = dll_cfg.get("mac_proto", "csma_cd"),
            flow       = dll_cfg.get("flow", "stop_and_wait"),
            flow_kwargs= dll_cfg.get("flow_kwargs", {}),
            mac_kwargs = dll_cfg.get("mac_kwargs", {}),
        )
        self.layers["datalink"] = dll

        # Network
        net = NetworkLayerImpl(device_id=self.device_id, device_ip=self.ip or "0.0.0.0")
        if self.ip:
            net.add_route("0.0.0.0", "0.0.0.0", next_hop=net_cfg.get("gateway"))
        self.layers["network"] = net

        # Transport
        self.layers["transport"] = TransportLayerImpl(device_id=self.device_id)

        # Application (TCP/IP — absorbs session + presentation)
        app_cfg = config.get("application", {})
        self.layers["application"] = ApplicationLayerImpl(
            device_id  = self.device_id,
            app_proto  = app_cfg.get("proto", "http"),
            encoding   = app_cfg.get("encoding", "base64"),
            encrypt    = app_cfg.get("encrypt", False),
        )

        self._wire_layers()
