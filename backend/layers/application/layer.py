"""
layers/application/layer.py
------------------------------
Application Layer (TCP/IP model) — absorbs OSI Session + Presentation duties.
Simulates HTTP, DNS, DHCP, ICMP. Also emits SESSION_INFO and APP_ENCODING events
so the frontend can show session lifecycle and encoding/encryption details.
"""
from __future__ import annotations
import base64, logging
from abc import abstractmethod
from typing import Optional
from layers.base import Layer, LayerPDU
from simulation.events import EventType, LayerName, PDU, SimEvent

logger = logging.getLogger(__name__)

class ApplicationLayer(Layer):
    def __init__(self):
        super().__init__(layer_name="application")
        self.device_id="unknown"
        self._app_proto="http"
        self._session_id:Optional[str]=None
        self._encoding_scheme="base64"
        self._encrypt=False

    def _do_send(self, pdu:LayerPDU):
        ts=pdu.meta.get("timestamp",0.0)
        payload=str(pdu.data) if not isinstance(pdu.data,str) else pdu.data

        # 1. Session open (folded-in session layer duty)
        self._session_id=pdu.meta.get("session_id","sess-001")
        self.emit(SimEvent(timestamp=ts,event_type=EventType.SESSION_INFO,
            layer=LayerName.APPLICATION,src_device=self.device_id,
            pdu=PDU(type="session",headers={"action":"open","session_id":self._session_id}),
            meta={"note":"Session+Presentation merged into Application (TCP/IP model)"}))

        # 2. Presentation: encode/encrypt (folded-in presentation layer duty)
        encoded=base64.b64encode(payload.encode()).decode() if self._encoding_scheme=="base64" else payload
        if self._encrypt:
            encoded="".join(chr(ord(c)^0x5A) for c in encoded)
        self.emit(SimEvent(timestamp=ts,event_type=EventType.APP_ENCODING,
            layer=LayerName.APPLICATION,src_device=self.device_id,
            pdu=PDU(type="encoding",headers={
                "scheme":self._encoding_scheme,"encrypted":self._encrypt,
                "original_len":len(payload),"encoded_len":len(encoded)}),
            meta={"note":"Presentation duty: encoding/encryption"}))

        # 3. Application protocol
        proto=pdu.meta.get("app_proto",self._app_proto)
        if proto=="http":
            method=pdu.meta.get("http_method","GET")
            url=pdu.meta.get("url","/")
            hdrs={"method":method,"url":url,"host":pdu.meta.get("dst_ip","server"),
                  "content_length":len(encoded),"user_agent":"NetSim/1.0"}
            self.emit(SimEvent(timestamp=ts,event_type=EventType.APP_REQUEST,
                layer=LayerName.APPLICATION,src_device=self.device_id,
                dst_device=pdu.meta.get("dst_device"),
                pdu=PDU(type="http_request",headers=hdrs,payload=encoded[:64])))
        elif proto=="dns":
            self.emit(SimEvent(timestamp=ts,event_type=EventType.APP_REQUEST,
                layer=LayerName.APPLICATION,src_device=self.device_id,
                pdu=PDU(type="dns_query",headers={"query":payload,"type":"A","recursive":True})))
        elif proto=="icmp":
            self.emit(SimEvent(timestamp=ts,event_type=EventType.APP_REQUEST,
                layer=LayerName.APPLICATION,src_device=self.device_id,
                pdu=PDU(type="icmp",headers={"type":8,"code":0,"detail":"Echo Request (ping)"})))

        pdu.data=encoded.encode()
        if self._lower: self._lower.send_down(pdu)

    def _do_receive(self, pdu:LayerPDU):
        ts=pdu.meta.get("timestamp",0.0)
        self.emit(SimEvent(timestamp=ts,event_type=EventType.APP_RESPONSE,
            layer=LayerName.APPLICATION,src_device=self.device_id,
            pdu=PDU(type="http_response",headers={"status_code":200,"status":"OK"})))
        # Session close
        self.emit(SimEvent(timestamp=ts,event_type=EventType.SESSION_INFO,
            layer=LayerName.APPLICATION,src_device=self.device_id,
            pdu=PDU(type="session",headers={"action":"close","session_id":self._session_id})))

    @abstractmethod
    def _validate_config(self): ...

class ApplicationLayerImpl(ApplicationLayer):
    def __init__(self,device_id="unknown",app_proto="http",encoding="base64",encrypt=False):
        super().__init__()
        self.device_id=device_id; self._app_proto=app_proto
        self._encoding_scheme=encoding; self._encrypt=encrypt
        self._validate_config()
    def _validate_config(self): pass
