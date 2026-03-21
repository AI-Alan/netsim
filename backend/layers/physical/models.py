"""layers/physical/models.py — Bits and Signal value objects."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bits:
    data:   tuple
    length: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "length", len(self.data))
        for b in self.data:
            if b not in (0, 1):
                raise ValueError(f"Bits must be 0 or 1, got {b}")

    @classmethod
    def from_list(cls, lst: list) -> "Bits":
        return cls(data=tuple(lst))

    @classmethod
    def from_str(cls, s: str) -> "Bits":
        return cls(data=tuple(int(c) for c in s if c in "01"))

    @classmethod
    def from_bytes(cls, b: bytes) -> "Bits":
        bits = []
        for byte in b:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)
        return cls(data=tuple(bits))

    def to_str(self) -> str:
        return "".join(str(b) for b in self.data)

    def to_list(self) -> list:
        return list(self.data)

    def to_bytes(self) -> bytes:
        padded = list(self.data)
        while len(padded) % 8:
            padded.append(0)
        result = []
        for i in range(0, len(padded), 8):
            byte = 0
            for bit in padded[i:i+8]:
                byte = (byte << 1) | bit
            result.append(byte)
        return bytes(result)


@dataclass(frozen=True)
class Signal:
    samples:     tuple
    sample_rate: int
    encoding:    str

    def __post_init__(self):
        # Clamp samples silently – wireless medium Gaussian noise can push slightly past ±1
        clamped = tuple(max(-1.0, min(1.0, s)) for s in self.samples)
        object.__setattr__(self, "samples", clamped)

    @classmethod
    def from_list(cls, lst: list, sample_rate: int, encoding: str) -> "Signal":
        return cls(samples=tuple(lst), sample_rate=sample_rate, encoding=encoding)

    def to_dict(self) -> dict:
        return {"samples": list(self.samples), "sample_rate": self.sample_rate, "encoding": self.encoding}
