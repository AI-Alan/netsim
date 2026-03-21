"""
layers/base.py
--------------
Abstract Layer base + ILayerObserver + LayerPDU.
Patterns: Observer, Template Method, Dependency Inversion.
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional
from simulation.events import SimEvent

logger = logging.getLogger(__name__)


class ILayerObserver(ABC):
    @abstractmethod
    def on_event(self, event: SimEvent) -> None: ...


class IProtocol(ABC):
    pass


class LayerPDU:
    """Mutable carrier passed between layers. Each layer adds/strips headers."""
    def __init__(self, data: Any, meta: Optional[dict] = None) -> None:
        self.data = data
        self.meta: dict = meta or {}
        self.headers: List[dict] = []


class Layer(ABC):
    """
    Template Method base for all OSI layers.
    Concrete layers implement _do_send / _do_receive and call self.emit().
    """
    def __init__(self, layer_name: str) -> None:
        self.layer_name = layer_name
        self._observers: List[ILayerObserver] = []
        self._lower: Optional[Layer] = None
        self._upper: Optional[Layer] = None
        self.protocol: Optional[IProtocol] = None

    def set_lower(self, layer: Layer) -> None:  self._lower = layer
    def set_upper(self, layer: Layer) -> None:  self._upper = layer

    def attach_observer(self, obs: ILayerObserver) -> None:
        if obs not in self._observers:
            self._observers.append(obs)

    def detach_observer(self, obs: ILayerObserver) -> None:
        if obs in self._observers:
            self._observers.remove(obs)

    def emit(self, event: SimEvent) -> None:
        for obs in self._observers:
            try:
                obs.on_event(event)
            except Exception as exc:
                logger.error("Observer %s raised: %s", obs, exc)

    def send_down(self, pdu: LayerPDU) -> None:
        logger.debug("[%s] send_down", self.layer_name)
        self._do_send(pdu)

    def receive_up(self, pdu: LayerPDU) -> None:
        logger.debug("[%s] receive_up", self.layer_name)
        self._do_receive(pdu)

    @abstractmethod
    def _do_send(self, pdu: LayerPDU) -> None: ...

    @abstractmethod
    def _do_receive(self, pdu: LayerPDU) -> None: ...
