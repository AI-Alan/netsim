"""
layers/physical/factory.py
---------------------------
PhysicalLayerFactory — Factory Method pattern.
Single creation point; add new strategies to ENCODING_REGISTRY / MEDIUM_REGISTRY only.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from layers.physical.encoding import ENCODING_REGISTRY, IEncodingStrategy
from layers.physical.medium import MEDIUM_REGISTRY, ITransmissionMedium
from layers.physical.layer import PhysicalLayerImpl

logger = logging.getLogger(__name__)


class PhysicalLayerFactory:

    @staticmethod
    def create(
        encoding_type: str,
        medium_type: str,
        device_id: str = "unknown",
        clock_rate: int = 1000,
        samples_per_bit: int = 100,
        encoding_kwargs: Optional[Dict[str, Any]] = None,
        medium_kwargs: Optional[Dict[str, Any]] = None,
    ) -> PhysicalLayerImpl:
        encoding_kwargs = encoding_kwargs or {}
        medium_kwargs   = medium_kwargs   or {}

        enc_cls = ENCODING_REGISTRY.get(encoding_type)
        if enc_cls is None:
            raise ValueError(f"Unknown encoding {encoding_type!r}. Available: {list(ENCODING_REGISTRY)}")
        encoder: IEncodingStrategy = enc_cls(samples_per_bit=samples_per_bit, **encoding_kwargs)

        med_cls = MEDIUM_REGISTRY.get(medium_type.lower())
        if med_cls is None:
            raise ValueError(f"Unknown medium {medium_type!r}. Available: {list(MEDIUM_REGISTRY)}")
        medium: ITransmissionMedium = med_cls(**medium_kwargs)

        layer = PhysicalLayerImpl(encoder=encoder, medium=medium,
                                  device_id=device_id, clock_rate=clock_rate)
        logger.info("PhysicalLayerFactory: %s enc=%s medium=%s", device_id, encoding_type, medium_type)
        return layer

    @staticmethod
    def available_encodings() -> List[str]:
        return list(ENCODING_REGISTRY.keys())

    @staticmethod
    def available_media() -> List[str]:
        return list(MEDIUM_REGISTRY.keys())
