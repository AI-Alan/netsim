"""
layers/physical/medium.py
--------------------------
ITransmissionMedium (Strategy) + WiredMedium + WirelessMedium.
"""
from __future__ import annotations
import math, random
from abc import ABC, abstractmethod
from typing import Dict, List
from layers.physical.models import Signal


class ITransmissionMedium(ABC):
    @abstractmethod
    def transmit(self, signal: Signal) -> Signal: ...
    @abstractmethod
    def get_bandwidth(self) -> float: ...
    @abstractmethod
    def get_delay(self) -> float: ...
    @property
    @abstractmethod
    def name(self) -> str: ...


class WiredMedium(ITransmissionMedium):
    SPEED_OF_LIGHT = 3e8

    def __init__(self, length_m: float = 10.0, speed_factor: float = 0.66,
                 bandwidth_hz: float = 100e6, ber: float = 0.0) -> None:
        self._length = length_m
        self._speed  = speed_factor * self.SPEED_OF_LIGHT
        self._bandwidth = bandwidth_hz
        self._ber = ber

    @property
    def name(self) -> str: return "Wired"
    def get_bandwidth(self) -> float: return self._bandwidth
    def get_delay(self) -> float: return self._length / self._speed

    def transmit(self, signal: Signal) -> Signal:
        if self._ber == 0.0:
            return signal
        corrupted = list(signal.samples)
        for i, s in enumerate(corrupted):
            if random.random() < self._ber:
                corrupted[i] = -s
        return Signal.from_list(corrupted, signal.sample_rate, signal.encoding)


class WirelessMedium(ITransmissionMedium):
    SPEED_OF_LIGHT = 3e8

    def __init__(self, distance_m: float = 10.0, frequency_hz: float = 2.4e9,
                 tx_power_dbm: float = 20.0, noise_figure_db: float = 10.0) -> None:
        self._distance = distance_m
        self._frequency = frequency_hz
        self._tx_power_dbm = tx_power_dbm
        self._noise_figure_db = noise_figure_db

    @property
    def name(self) -> str: return "Wireless"
    def get_bandwidth(self) -> float: return 20e6
    def get_delay(self) -> float: return self._distance / self.SPEED_OF_LIGHT

    def _path_loss_db(self) -> float:
        if self._distance == 0: return 0.0
        wavelength = self.SPEED_OF_LIGHT / self._frequency
        return 20 * math.log10(4 * math.pi * self._distance / wavelength)

    def transmit(self, signal: Signal) -> Signal:
        rx_dbm   = self._tx_power_dbm - self._path_loss_db()
        noise_dbm = -100.0 + self._noise_figure_db
        snr       = max(10 ** ((rx_dbm - noise_dbm) / 10.0), 1e-3)
        sig_power = sum(s*s for s in signal.samples) / max(len(signal.samples), 1)
        noise_std = math.sqrt(sig_power / snr) if sig_power > 0 else 0.1
        corrupted = [max(-1.0, min(1.0, s + random.gauss(0, noise_std))) for s in signal.samples]
        return Signal.from_list(corrupted, signal.sample_rate, signal.encoding)


MEDIUM_REGISTRY: Dict[str, type] = {
    "wired":    WiredMedium,
    "wireless": WirelessMedium,
}
