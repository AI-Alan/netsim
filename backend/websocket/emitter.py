"""
websocket/emitter.py
---------------------
WebSocketEmitter — ILayerObserver → broadcasts SimEvents to all WS clients.
ConnectionManager — tracks active WebSocket connections.
"""
from __future__ import annotations
import asyncio, logging
from typing import List, Optional
from layers.base import ILayerObserver
from simulation.events import SimEvent, sim_event_to_json

logger = logging.getLogger(__name__)

try:
    from fastapi import WebSocket
    _FASTAPI = True
except ImportError:
    WebSocket = object  # type: ignore
    _FASTAPI = False


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS connected — total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, message: str) -> None:
        dead: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


class WebSocketEmitter(ILayerObserver):
    """Attaches to all device layers; serialises SimEvents to JSON and broadcasts."""
    def __init__(self, manager: ConnectionManager,
                 loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._manager = manager
        self._loop = loop

    def on_event(self, event: SimEvent) -> None:
        try:
            payload = sim_event_to_json(event)
        except Exception:
            import json
            try:
                payload = json.dumps(event.model_dump(), default=str)
            except Exception:
                payload = json.dumps({"event_type": str(event.event_type)}, default=str)

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._manager.broadcast(payload), self._loop
            )
        else:
            logger.debug("WS emitter [no loop]: %s", event.event_type)
