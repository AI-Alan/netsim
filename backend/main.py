"""
main.py — NetSim FastAPI application (Phase 1+2: Physical + Data Link)
"""
from __future__ import annotations
import asyncio, logging, sys, os
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from layers.base import LayerPDU
from layers.physical.factory import PhysicalLayerFactory
from layers.physical.models import Bits
from layers.datalink.factory import DataLinkLayerFactory
from simulation.events import SimEvent, EventType, LayerName, PDU, sim_event_to_dict, sim_event_to_json
from simulation.topology_runtime import simulate_datalink_topology
from websocket.emitter import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NetSim", version="2.0.0",
              description="TCP/IP Network Simulator — Physical + Data Link layers")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

sessions: Dict[str, Dict[str, Any]] = {}
ws_manager = ConnectionManager()


# ── Request schemas ────────────────────────────────────────────────────────────
class PhysicalSimReq(BaseModel):
    session_id:      str
    src_device_id:   str
    dst_device_id:   str
    bit_string:      str
    encoding:        str = "NRZ-L"
    medium:          str = "wired"
    clock_rate:      int = 1000
    samples_per_bit: int = 100
    medium_kwargs:   Dict[str, Any] = {}

class DataLinkSimReq(BaseModel):
    session_id:     str
    src_device_id:  str
    dst_device_id:  str
    message:        str = "Hello NetSim"
    encoding:       str = "Manchester"
    medium:         str = "wired"
    clock_rate:     int = 1000
    samples_per_bit:int = 100
    framing:        str = "variable"
    framing_kwargs: Dict[str, Any] = {}
    error_control:  str = "crc32"
    mac_protocol:   str = "csma_cd"
    flow_control:   str = "stop_and_wait"
    window_size:    int = 4
    collision_prob: float = 0.02
    link_error_rate:float = 0.0
    inject_error:   bool = False
    medium_kwargs:  Dict[str, Any] = {}
    mac_kwargs:     Dict[str, Any] = {}
    topology_devices: List[Dict[str, Any]] = []
    topology_links: List[Dict[str, Any]] = []
    reset_learning: bool = False

class DeviceConfigReq(BaseModel):
    device_id:   str; device_type: str = "end_host"
    mac: str; ip: Optional[str] = None
    layer_config: Dict[str, Any] = {}

class TopologyReq(BaseModel):
    session_id: str
    devices: List[DeviceConfigReq]
    links: List[Dict[str, str]]


# ── REST endpoints ─────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "NetSim", "phase": "1+2 Physical+DataLink"}

@app.get("/api/encodings")
def list_encodings():
    return {"encodings": PhysicalLayerFactory.available_encodings()}

@app.get("/api/media")
def list_media():
    return {"media": PhysicalLayerFactory.available_media()}

@app.get("/api/datalink/options")
def list_datalink_options():
    return DataLinkLayerFactory.available_options()

@app.post("/api/simulate/physical")
async def simulate_physical(req: PhysicalSimReq):
    collected: List[SimEvent] = []

    class CollectObs:
        def on_event(self, e): collected.append(e)

    class WSBroadcastObs:
        def on_event(self, e):
            asyncio.create_task(ws_manager.broadcast(sim_event_to_json(e)))

    phy = PhysicalLayerFactory.create(
        encoding_type=req.encoding, medium_type=req.medium,
        device_id=req.src_device_id, clock_rate=req.clock_rate,
        samples_per_bit=req.samples_per_bit, medium_kwargs=req.medium_kwargs,
    )
    phy.attach_observer(CollectObs())
    if ws_manager.connection_count > 0:
        phy.attach_observer(WSBroadcastObs())

    bits = Bits.from_list([int(c) for c in req.bit_string if c in "01"])
    pdu  = LayerPDU(data=bits, meta={
        "src_device": req.src_device_id, "dst_device": req.dst_device_id, "timestamp": 0.0,
    })
    phy.send_down(pdu)
    return {"status":"ok","events_emitted":len(collected),"events":[sim_event_to_dict(e) for e in collected]}

@app.post("/api/simulate/datalink")
async def simulate_datalink(req: DataLinkSimReq):
    if req.topology_devices and req.topology_links:
        sess = sessions.setdefault(req.session_id, {})
        topo_events, domain_stats, switch_tables, learning_summary, switch_ports = simulate_datalink_topology(
            req=req,
            session_state=sess,
        )
        if ws_manager.connection_count > 0:
            for e in topo_events:
                asyncio.create_task(ws_manager.broadcast(sim_event_to_json(e)))
        return {
            "status": "ok",
            "events_emitted": len(topo_events),
            "events": [sim_event_to_dict(e) for e in topo_events],
            "domain_stats": domain_stats,
            "switch_tables": switch_tables,
            "learning_summary": learning_summary,
            "switch_ports": switch_ports,
            "topology_mode": True,
        }

    collected: List[SimEvent] = []

    class CollectObs:
        def on_event(self, e): collected.append(e)

    class WSBroadcastObs:
        def on_event(self, e):
            asyncio.create_task(ws_manager.broadcast(sim_event_to_json(e)))

    # Build physical + datalink stack
    phy = PhysicalLayerFactory.create(
        encoding_type=req.encoding, medium_type=req.medium,
        device_id=req.src_device_id, clock_rate=req.clock_rate,
        samples_per_bit=req.samples_per_bit, medium_kwargs=req.medium_kwargs,
    )
    flow_kwargs = {"window": req.window_size} if req.flow_control in ("go_back_n","selective_repeat") else {}
    dll = DataLinkLayerFactory.create(
        device_id=req.src_device_id, mac_addr="aa:bb:cc:dd:ee:ff",
        framing=req.framing, error=req.error_control,
        mac_proto=req.mac_protocol, flow=req.flow_control,
        framing_kwargs=req.framing_kwargs,
        flow_kwargs=flow_kwargs, mac_kwargs=req.mac_kwargs,
    )
    # Wire: dll → phy
    dll.set_lower(phy); phy.set_upper(dll)

    for layer in [phy, dll]:
        layer.attach_observer(CollectObs())
        if ws_manager.connection_count > 0:
            layer.attach_observer(WSBroadcastObs())

    pdu = LayerPDU(data=req.message.encode(), meta={
        "src_device": req.src_device_id, "dst_device": req.dst_device_id,
        "dst_mac": "ff:ff:ff:ff:ff:ff", "timestamp": 0.0,
        "channel_busy": False, "collision_prob": req.collision_prob,
        "link_error_rate": req.link_error_rate,
        "inject_error": req.inject_error,
    })
    dll.send_down(pdu)
    return {
        "status": "ok",
        "events_emitted": len(collected),
        "events": [sim_event_to_dict(e) for e in collected],
        "domain_stats": {"broadcast_domains": 1, "collision_domains": 1},
        "switch_tables": {},
        "learning_summary": [],
        "switch_ports": {},
        "topology_mode": False,
    }


# ── WebSocket ──────────────────────────────────────────────────────────────────
@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    await ws_manager.connect(websocket)
    logger.info("WS opened session=%s total=%d", session_id, ws_manager.connection_count)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
