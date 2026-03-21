"""
simulation/events.py  —  TCP/IP model (session+presentation → application)
"""
from __future__ import annotations
import uuid
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    BITS_SENT        = "BITS_SENT"
    SIGNAL_DRAWN     = "SIGNAL_DRAWN"
    BITS_RECEIVED    = "BITS_RECEIVED"
    FRAME_SENT       = "FRAME_SENT"
    FRAME_RECEIVED   = "FRAME_RECEIVED"
    FRAME_DROPPED    = "FRAME_DROPPED"
    ARP_REQUEST      = "ARP_REQUEST"
    ARP_REPLY        = "ARP_REPLY"
    FRAMING_INFO     = "FRAMING_INFO"
    ERROR_DETECTED   = "ERROR_DETECTED"
    ACCESS_CONTROL   = "ACCESS_CONTROL"
    FLOW_CONTROL     = "FLOW_CONTROL"
    ACK_SENT         = "ACK_SENT"
    NAK_SENT         = "NAK_SENT"
    WINDOW_UPDATE    = "WINDOW_UPDATE"
    PACKET_SENT      = "PACKET_SENT"
    PACKET_RECEIVED  = "PACKET_RECEIVED"
    ROUTING_LOOKUP   = "ROUTING_LOOKUP"
    TTL_EXPIRED      = "TTL_EXPIRED"
    SEGMENT_SENT     = "SEGMENT_SENT"
    SEGMENT_RECEIVED = "SEGMENT_RECEIVED"
    TCP_STATE        = "TCP_STATE"
    APP_REQUEST      = "APP_REQUEST"
    APP_RESPONSE     = "APP_RESPONSE"
    APP_ENCODING     = "APP_ENCODING"
    SESSION_INFO     = "SESSION_INFO"
    SIM_PAUSED       = "SIM_PAUSED"
    SIM_RESUMED      = "SIM_RESUMED"
    SIM_STEPPED      = "SIM_STEPPED"
    SIM_RESET        = "SIM_RESET"


class LayerName(str, Enum):
    PHYSICAL    = "physical"
    DATALINK    = "datalink"
    NETWORK     = "network"
    TRANSPORT   = "transport"
    APPLICATION = "application"
    ENGINE      = "engine"


class PDU(BaseModel):
    type: str
    headers: dict = Field(default_factory=dict)
    payload: str = ""


class SimEvent(BaseModel):
    event_id:   str   = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:  float = 0.0
    event_type: EventType
    layer:      LayerName
    src_device: str
    dst_device: Optional[str] = None
    pdu:        PDU   = Field(default_factory=lambda: PDU(type="empty"))
    signal:     Optional[dict] = None
    meta:       dict  = Field(default_factory=dict)

    class Config:
        use_enum_values = True


def sim_event_to_dict(event: SimEvent) -> dict[str, Any]:
    """Pydantic v2: model_dump(); v1: dict()."""
    md = getattr(event, "model_dump", None)
    if callable(md):
        return md()
    return event.dict()


def sim_event_to_json(event: SimEvent) -> str:
    """Pydantic v2: model_dump_json(); v1: json()."""
    mdj = getattr(event, "model_dump_json", None)
    if callable(mdj):
        return mdj()
    return event.json()
