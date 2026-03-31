"""
layers/datalink/framing.py
---------------------------
IFraming (Strategy) + FixedSizeFraming + VariableSizeFraming (bit-oriented).

Fixed-size: every frame = N bytes, padded / truncated.
Variable-size (bit-oriented): flag bytes (0x7E) delimit frames;
    byte stuffing: 0x7E inside payload → 0x7D 0x5E,
                   0x7D inside payload → 0x7D 0x5D.

Pattern: Strategy – DataLinkLayer picks framing at runtime.
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)


class IFraming(ABC):
    @abstractmethod
    def frame(self, data: bytes) -> bytes:
        """Wrap raw data in a frame (adds delimiters / padding)."""

    @abstractmethod
    def deframe(self, raw: bytes) -> bytes:
        """Strip frame delimiters / padding, return payload."""

    @property
    @abstractmethod
    def name(self) -> str: ...


# ── Fixed-size framing ───────────────────────────────────────────────────────
class FixedSizeFraming(IFraming):
    """
    All frames are exactly `frame_size` bytes.
    Shorter payloads are zero-padded; longer are split (only first frame here).
    """
    FLAG = b"\xFF\xFE"   # 2-byte fixed-frame header marker

    def __init__(self, frame_size: int = 128) -> None:
        self.frame_size = frame_size

    @property
    def name(self) -> str:
        return f"Fixed({self.frame_size}B)"

    def frame(self, data: bytes) -> bytes:
        if len(data) > self.frame_size:
            logger.warning(
                "FixedSizeFraming: payload (%d B) exceeds frame_size (%d B) — truncating",
                len(data), self.frame_size,
            )
        padded = (data + b"\x00" * self.frame_size)[: self.frame_size]
        return self.FLAG + padded

    def deframe(self, raw: bytes) -> bytes:
        flag_len = len(self.FLAG)
        if raw[:flag_len] == self.FLAG:
            payload = raw[flag_len : flag_len + self.frame_size]
        else:
            payload = raw[: self.frame_size]
        return payload.rstrip(b"\x00")


# ── Variable-size framing (bit-oriented, HDLC-style) ─────────────────────────
class VariableSizeFraming(IFraming):
    """
    HDLC / PPP-style flag-delimited frames.
    FLAG = 0x7E (start and end delimiter).
    Byte stuffing keeps FLAG bytes from appearing inside the payload.
    """
    FLAG         = 0x7E
    ESCAPE       = 0x7D
    ESCAPE_FLAG  = 0x5E   # 0x7E XOR 0x20
    ESCAPE_ESC   = 0x5D   # 0x7D XOR 0x20

    @property
    def name(self) -> str:
        return "Variable(bit-oriented)"

    def frame(self, data: bytes) -> bytes:
        stuffed = bytearray()
        for byte in data:
            if byte == self.FLAG:
                stuffed += bytes([self.ESCAPE, self.ESCAPE_FLAG])
            elif byte == self.ESCAPE:
                stuffed += bytes([self.ESCAPE, self.ESCAPE_ESC])
            else:
                stuffed.append(byte)
        return bytes([self.FLAG]) + bytes(stuffed) + bytes([self.FLAG])

    def deframe(self, raw: bytes) -> bytes:
        # strip leading/trailing FLAG
        inner = raw
        if inner and inner[0] == self.FLAG:
            inner = inner[1:]
        if inner and inner[-1] == self.FLAG:
            inner = inner[:-1]
        result = bytearray()
        i = 0
        while i < len(inner):
            b = inner[i]
            if b == self.ESCAPE and i + 1 < len(inner):
                nxt = inner[i + 1]
                result.append(nxt ^ 0x20)
                i += 2
            else:
                result.append(b)
                i += 1
        return bytes(result)


# ── Registry ─────────────────────────────────────────────────────────────────
FRAMING_REGISTRY: dict[str, type] = {
    "fixed":    FixedSizeFraming,
    "variable": VariableSizeFraming,
}
