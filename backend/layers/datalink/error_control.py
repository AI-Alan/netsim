"""
layers/datalink/error_control.py
----------------------------------
IErrorControl (Strategy) + ChecksumErrorControl + CRCErrorControl.

Pattern: Strategy — DataLinkLayer selects error scheme at runtime.
OCP     — new schemes added by implementing IErrorControl, no core change.
"""
from __future__ import annotations
import struct
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ErrorResult:
    ok:        bool
    corrected: bool = False
    dropped:   bool = False
    detail:    str  = ""


class IErrorControl(ABC):
    @abstractmethod
    def compute(self, data: bytes) -> bytes:
        """Return data with appended check-bits."""

    @abstractmethod
    def verify(self, data: bytes) -> ErrorResult:
        """Verify; return ErrorResult describing outcome."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def overhead_bytes(self) -> int: ...


# ── Internet Checksum (16-bit ones-complement) ────────────────────────────────
class ChecksumErrorControl(IErrorControl):
    """
    RFC-1071 Internet checksum — detects single and many burst errors.
    16-bit overhead per frame. Used in IP, TCP, UDP headers.
    """

    @property
    def name(self) -> str: return "Checksum-16"

    @property
    def overhead_bytes(self) -> int: return 2

    def _checksum(self, data: bytes) -> int:
        if len(data) % 2:
            data += b"\x00"
        total = 0
        for i in range(0, len(data), 2):
            word = (data[i] << 8) + data[i + 1]
            total += word
        total = (total >> 16) + (total & 0xFFFF)
        total += total >> 16
        return (~total) & 0xFFFF

    def compute(self, data: bytes) -> bytes:
        cs = self._checksum(data)
        return data + struct.pack(">H", cs)

    def verify(self, data: bytes) -> ErrorResult:
        if len(data) < 2:
            return ErrorResult(ok=False, dropped=True, detail="Too short")
        payload = data[:-2]
        received_cs = struct.unpack(">H", data[-2:])[0]
        expected_cs = self._checksum(payload)
        if received_cs == expected_cs:
            return ErrorResult(ok=True, detail="Checksum OK")
        return ErrorResult(
            ok=False, dropped=True,
            detail=f"Checksum mismatch: got {received_cs:#06x} expected {expected_cs:#06x}",
        )


# ── CRC-32 ────────────────────────────────────────────────────────────────────
class CRCErrorControl(IErrorControl):
    """
    CRC-32 (IEEE 802.3 polynomial 0xEDB88320).
    Detects all single-bit, double-bit, and burst errors ≤ 32 bits.
    4-byte overhead appended as FCS (Frame Check Sequence).
    """

    @property
    def name(self) -> str: return "CRC-32"

    @property
    def overhead_bytes(self) -> int: return 4

    def _crc(self, data: bytes) -> int:
        return zlib.crc32(data) & 0xFFFFFFFF

    def compute(self, data: bytes) -> bytes:
        fcs = self._crc(data)
        return data + struct.pack("<I", fcs)

    def verify(self, data: bytes) -> ErrorResult:
        if len(data) < 4:
            return ErrorResult(ok=False, dropped=True, detail="Frame too short for CRC")
        payload  = data[:-4]
        recv_fcs = struct.unpack("<I", data[-4:])[0]
        calc_fcs = self._crc(payload)
        if recv_fcs == calc_fcs:
            return ErrorResult(ok=True, detail="CRC-32 OK")
        return ErrorResult(
            ok=False, dropped=True,
            detail=f"CRC mismatch: recv={recv_fcs:#010x} calc={calc_fcs:#010x}",
        )


# ── Registry ─────────────────────────────────────────────────────────────────
ERROR_CONTROL_REGISTRY: dict[str, type] = {
    "checksum": ChecksumErrorControl,
    "crc32":    CRCErrorControl,
    "none":     type("NoErrorControl", (IErrorControl,), {   # pass-through
        "compute": lambda self, d: d,
        "verify":  lambda self, d: ErrorResult(ok=True, detail="No error control"),
        "name":    property(lambda self: "None"),
        "overhead_bytes": property(lambda self: 0),
    }),
}
