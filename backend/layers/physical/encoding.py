"""
layers/physical/encoding.py
----------------------------
IEncodingStrategy interface + all concrete encoding implementations.
Strategy pattern: swap encoding at runtime without changing PhysicalLayer.

Encodings:
  NRZEncoding           -- NRZ-L
  NRZIEncoding          -- NRZ-I
  ManchesterEncoding    -- IEEE 802.3 Manchester
  DiffManchesterEncoding -- Differential Manchester
  AMIEncoding           -- Alternate Mark Inversion
  FourBFiveBEncoding    -- 4B5B + NRZ-I
"""
from __future__ import annotations
import math
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple
from layers.physical.models import Bits, Signal


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------
class IEncodingStrategy(ABC):
    samples_per_bit: int = 100

    @abstractmethod
    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal: ...

    @abstractmethod
    def decode(self, signal: Signal) -> Bits: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _expand(levels: List[float], spb: int) -> List[float]:
    out: List[float] = []
    for lvl in levels:
        out.extend([lvl] * spb)
    return out

def _avg(samples: List[float]) -> float:
    return sum(samples) / len(samples) if samples else 0.0


# ---------------------------------------------------------------------------
# NRZ-L
# ---------------------------------------------------------------------------
class NRZEncoding(IEncodingStrategy):
    def __init__(self, samples_per_bit: int = 100) -> None:
        self.samples_per_bit = samples_per_bit

    @property
    def name(self) -> str: return "NRZ-L"

    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal:
        levels = [1.0 if b else -1.0 for b in bits.data]
        return Signal.from_list(_expand(levels, self.samples_per_bit),
                                clock_rate * self.samples_per_bit, self.name)

    def decode(self, signal: Signal) -> Bits:
        spb = self.samples_per_bit
        n = len(signal.samples) // spb
        return Bits.from_list([
            1 if _avg(list(signal.samples[i*spb:(i+1)*spb])) > 0 else 0
            for i in range(n)
        ])


# ---------------------------------------------------------------------------
# NRZ-I
# ---------------------------------------------------------------------------
class NRZIEncoding(IEncodingStrategy):
    def __init__(self, samples_per_bit: int = 100, initial_level: float = 1.0) -> None:
        self.samples_per_bit = samples_per_bit
        self._initial = initial_level

    @property
    def name(self) -> str: return "NRZ-I"

    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal:
        level = self._initial
        levels: List[float] = []
        for b in bits.data:
            if b: level = -level
            levels.append(level)
        return Signal.from_list(_expand(levels, self.samples_per_bit),
                                clock_rate * self.samples_per_bit, self.name)

    def decode(self, signal: Signal) -> Bits:
        spb = self.samples_per_bit
        n = len(signal.samples) // spb
        avgs = [_avg(list(signal.samples[i*spb:(i+1)*spb])) for i in range(n)]
        recovered: List[int] = []
        prev = self._initial
        for a in avgs:
            sp = math.copysign(1.0, a)  if a  != 0 else 1.0
            pp = math.copysign(1.0, prev) if prev != 0 else 1.0
            recovered.append(1 if sp != pp else 0)
            prev = a if a != 0 else prev
        return Bits.from_list(recovered)


# ---------------------------------------------------------------------------
# Manchester (IEEE 802.3)
# ---------------------------------------------------------------------------
class ManchesterEncoding(IEncodingStrategy):
    def __init__(self, samples_per_bit: int = 100) -> None:
        self.samples_per_bit = samples_per_bit

    @property
    def name(self) -> str: return "Manchester"

    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal:
        half = self.samples_per_bit // 2
        samples: List[float] = []
        for b in bits.data:
            if b:
                samples.extend([1.0]*half + [-1.0]*(self.samples_per_bit - half))
            else:
                samples.extend([-1.0]*half + [1.0]*(self.samples_per_bit - half))
        return Signal.from_list(samples, clock_rate * self.samples_per_bit, self.name)

    def decode(self, signal: Signal) -> Bits:
        spb = self.samples_per_bit
        half = spb // 2
        n = len(signal.samples) // spb
        result: List[int] = []
        for i in range(n):
            f = _avg(list(signal.samples[i*spb:i*spb+half]))
            s = _avg(list(signal.samples[i*spb+half:(i+1)*spb]))
            result.append(1 if f > 0 and s < 0 else 0)
        return Bits.from_list(result)


# ---------------------------------------------------------------------------
# Differential Manchester
# ---------------------------------------------------------------------------
class DiffManchesterEncoding(IEncodingStrategy):
    def __init__(self, samples_per_bit: int = 100) -> None:
        self.samples_per_bit = samples_per_bit

    @property
    def name(self) -> str: return "Differential Manchester"

    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal:
        half = self.samples_per_bit // 2
        level = 1.0
        samples: List[float] = []
        for b in bits.data:
            if not b: level = -level          # transition at start for 0
            samples.extend([level] * half)
            level = -level                     # always mid-bit transition
            samples.extend([level] * (self.samples_per_bit - half))
        return Signal.from_list(samples, clock_rate * self.samples_per_bit, self.name)

    def decode(self, signal: Signal) -> Bits:
        spb = self.samples_per_bit
        half = spb // 2
        n = len(signal.samples) // spb
        result: List[int] = []
        prev_end = 1.0
        for i in range(n):
            af = _avg(list(signal.samples[i*spb:i*spb+half]))
            as_ = _avg(list(signal.samples[i*spb+half:(i+1)*spb]))
            sf = math.copysign(1.0, af)   if af   != 0 else 1.0
            sp = math.copysign(1.0, prev_end) if prev_end != 0 else 1.0
            result.append(0 if sf != sp else 1)
            prev_end = as_ if as_ != 0 else prev_end
        return Bits.from_list(result)


# ---------------------------------------------------------------------------
# AMI
# ---------------------------------------------------------------------------
class AMIEncoding(IEncodingStrategy):
    THRESHOLD = 0.1

    def __init__(self, samples_per_bit: int = 100) -> None:
        self.samples_per_bit = samples_per_bit

    @property
    def name(self) -> str: return "AMI"

    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal:
        mark = 1.0
        levels: List[float] = []
        for b in bits.data:
            if b:
                levels.append(mark); mark = -mark
            else:
                levels.append(0.0)
        return Signal.from_list(_expand(levels, self.samples_per_bit),
                                clock_rate * self.samples_per_bit, self.name)

    def decode(self, signal: Signal) -> Bits:
        spb = self.samples_per_bit
        n = len(signal.samples) // spb
        return Bits.from_list([
            1 if sum(abs(s) for s in signal.samples[i*spb:(i+1)*spb]) / spb > self.THRESHOLD else 0
            for i in range(n)
        ])


# ---------------------------------------------------------------------------
# 4B5B
# ---------------------------------------------------------------------------
_4B5B: Dict[Tuple, Tuple] = {
    (0,0,0,0):(1,1,1,1,0),(0,0,0,1):(0,1,0,0,1),(0,0,1,0):(1,0,1,0,0),
    (0,0,1,1):(1,0,1,0,1),(0,1,0,0):(0,1,0,1,0),(0,1,0,1):(0,1,0,1,1),
    (0,1,1,0):(0,1,1,1,0),(0,1,1,1):(0,1,1,1,1),(1,0,0,0):(1,0,0,1,0),
    (1,0,0,1):(1,0,0,1,1),(1,0,1,0):(1,0,1,1,0),(1,0,1,1):(1,0,1,1,1),
    (1,1,0,0):(1,1,0,1,0),(1,1,0,1):(1,1,0,1,1),(1,1,1,0):(1,1,1,0,0),
    (1,1,1,1):(1,1,1,0,1),
}
_5B4B: Dict[Tuple, Tuple] = {v: k for k, v in _4B5B.items()}


class FourBFiveBEncoding(IEncodingStrategy):
    def __init__(self, samples_per_bit: int = 100) -> None:
        self.samples_per_bit = samples_per_bit
        self._nrzi = NRZIEncoding(samples_per_bit)

    @property
    def name(self) -> str: return "4B5B"

    def encode(self, bits: Bits, clock_rate: int = 1000) -> Signal:
        data = list(bits.data)
        while len(data) % 4: data.append(0)
        encoded: List[int] = []
        for i in range(0, len(data), 4):
            code = _4B5B.get(tuple(data[i:i+4]))
            if code is None: raise ValueError(f"No 4B5B code for {data[i:i+4]}")
            encoded.extend(code)
        return self._nrzi.encode(Bits.from_list(encoded), clock_rate)

    def decode(self, signal: Signal) -> Bits:
        five_bits = list(self._nrzi.decode(signal).data)
        while len(five_bits) % 5: five_bits.append(0)
        result: List[int] = []
        for i in range(0, len(five_bits), 5):
            nibble = _5B4B.get(tuple(five_bits[i:i+5]), (0,0,0,0))
            result.extend(nibble)
        return Bits.from_list(result)


# ---------------------------------------------------------------------------
# Registry — PhysicalLayerFactory looks up by name string
# ---------------------------------------------------------------------------
ENCODING_REGISTRY: Dict[str, type] = {
    "NRZ-L":                   NRZEncoding,
    "NRZ-I":                   NRZIEncoding,
    "Manchester":              ManchesterEncoding,
    "Differential Manchester": DiffManchesterEncoding,
    "AMI":                     AMIEncoding,
    "4B5B":                    FourBFiveBEncoding,
}
