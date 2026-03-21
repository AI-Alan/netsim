"""
layers/datalink/access_control.py
-----------------------------------
IMACProtocol (Strategy) + Pure Aloha, Slotted Aloha, CSMA, CSMA/CD, CSMA/CA.

All protocols simulate the *decision* of whether to transmit and return a
MACResult with educational detail strings, so the frontend can explain each step.

Pattern: Strategy — DataLinkLayer swaps MAC protocol at runtime.
"""
from __future__ import annotations
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MACResult:
    transmitted:      bool
    collision:        bool        = False
    backoff_slots:    int         = 0
    attempts:         int         = 1
    rts_cts_used:     bool        = False
    detail:           str         = ""
    steps:            list[str]   = field(default_factory=list)


class IMACProtocol(ABC):
    @abstractmethod
    def transmit(self, channel_busy: bool = False, collision_prob: float = 0.0) -> MACResult:
        """
        Simulate one transmission attempt.
        channel_busy:    True if the medium is sensed busy.
        collision_prob:  Probability a collision occurs even if channel is free.
        """

    @property
    @abstractmethod
    def name(self) -> str: ...


# ── Pure ALOHA ────────────────────────────────────────────────────────────────
class PureAloha(IMACProtocol):
    """
    Transmit immediately whenever data is ready.
    If collision, wait a random back-off and retry.
    Max throughput ≈ 18.4 % at G=0.5.
    """
    MAX_RETRIES = 10

    def __init__(self, max_backoff_slots: int = 8) -> None:
        self.max_backoff = max_backoff_slots

    @property
    def name(self) -> str: return "Pure ALOHA"

    def transmit(self, channel_busy: bool = False, collision_prob: float = 0.1) -> MACResult:
        steps: list[str] = []
        for attempt in range(1, self.MAX_RETRIES + 1):
            steps.append(f"Attempt {attempt}: transmit immediately (no sensing)")
            if random.random() < collision_prob:
                backoff = random.randint(1, self.max_backoff)
                steps.append(f"  ✗ Collision! Back-off {backoff} slots")
                collision_prob *= 0.8   # reduce for retry
            else:
                steps.append("  ✓ Frame sent successfully")
                return MACResult(transmitted=True, attempts=attempt, steps=steps,
                                 detail=f"Pure ALOHA: transmitted on attempt {attempt}")
        return MACResult(transmitted=False, attempts=self.MAX_RETRIES, steps=steps,
                         detail="Pure ALOHA: max retries exceeded")


# ── Slotted ALOHA ─────────────────────────────────────────────────────────────
class SlottedAloha(IMACProtocol):
    """
    Transmit only at the beginning of a slot.
    Max throughput ≈ 36.8 % at G=1.
    """
    MAX_RETRIES = 10

    def __init__(self, max_backoff_slots: int = 16) -> None:
        self.max_backoff = max_backoff_slots

    @property
    def name(self) -> str: return "Slotted ALOHA"

    def transmit(self, channel_busy: bool = False, collision_prob: float = 0.1) -> MACResult:
        steps: list[str] = []
        for attempt in range(1, self.MAX_RETRIES + 1):
            steps.append(f"Attempt {attempt}: wait for slot boundary")
            if random.random() < collision_prob:
                backoff = random.randint(1, self.max_backoff)
                steps.append(f"  ✗ Collision! Back-off {backoff} slots")
            else:
                steps.append("  ✓ Slot acquired, frame sent")
                return MACResult(transmitted=True, attempts=attempt, steps=steps,
                                 detail=f"Slotted ALOHA: success on attempt {attempt}")
        return MACResult(transmitted=False, steps=steps, detail="Slotted ALOHA: max retries")


# ── CSMA (1-persistent) ───────────────────────────────────────────────────────
class CSMA(IMACProtocol):
    """
    Carrier Sense Multiple Access — 1-persistent.
    Sense channel; if idle transmit; if busy wait until idle then transmit.
    No collision detection.
    """
    MAX_RETRIES = 10

    @property
    def name(self) -> str: return "CSMA"

    def transmit(self, channel_busy: bool = False, collision_prob: float = 0.05) -> MACResult:
        steps: list[str] = []
        wait = 0
        while channel_busy:
            wait += 1
            steps.append(f"Channel busy — waiting (wait={wait})")
            if wait > 5:
                channel_busy = False   # channel clears eventually
        steps.append("Channel idle — transmitting (1-persistent)")
        if random.random() < collision_prob:
            steps.append("✗ Collision detected (no CD — frame lost)")
            return MACResult(transmitted=False, collision=True, steps=steps,
                             detail="CSMA: collision, no CD, frame lost")
        steps.append("✓ Frame sent successfully")
        return MACResult(transmitted=True, steps=steps, detail="CSMA: success")


# ── CSMA/CD (wired Ethernet) ──────────────────────────────────────────────────
class CSMACD(IMACProtocol):
    """
    CSMA with Collision Detection.
    IEEE 802.3 Ethernet — binary exponential backoff.
    After collision: wait 2^k slots (k = attempt count, capped at 10).
    """
    MAX_ATTEMPTS = 16

    @property
    def name(self) -> str: return "CSMA/CD"

    def transmit(self, channel_busy: bool = False, collision_prob: float = 0.05) -> MACResult:
        steps: list[str] = []
        for k in range(self.MAX_ATTEMPTS):
            # 1. Carrier sense
            if channel_busy:
                steps.append("Channel busy — deferring (CSMA sense)")
                # simulate channel clearing
                channel_busy = random.random() < 0.3

            # 2. Transmit
            steps.append(f"Attempt {k+1}: channel idle — begin transmission")
            if collision_prob >= 1.0 or random.random() < max(collision_prob / (k + 1), 0.005):
                # 3. Collision detected
                backoff = random.randint(0, min(2**k - 1, 1023))
                steps.append(f"  ✗ COLLISION! Jam signal sent. BEB backoff = {backoff} slots")
                continue
            else:
                steps.append("  ✓ No collision — frame transmitted successfully")
                return MACResult(
                    transmitted=True, attempts=k + 1,
                    backoff_slots=0, steps=steps,
                    detail=f"CSMA/CD: success on attempt {k+1}",
                )
        return MACResult(
            transmitted=False, attempts=self.MAX_ATTEMPTS,
            steps=steps, detail="CSMA/CD: 16 collisions — frame dropped",
        )


# ── CSMA/CA (wireless 802.11) ─────────────────────────────────────────────────
class CSMACA(IMACProtocol):
    """
    CSMA with Collision Avoidance (IEEE 802.11 DCF).
    Uses random back-off before transmitting + optional RTS/CTS handshake.
    After each busy period, waits DIFS + random back-off slots.
    """
    DIFS_SLOTS    = 2
    SIFS_SLOTS    = 1
    CW_MIN        = 16
    CW_MAX        = 1024
    MAX_RETRIES   = 7

    def __init__(self, use_rts_cts: bool = False) -> None:
        self.use_rts_cts = use_rts_cts

    @property
    def name(self) -> str:
        return "CSMA/CA (RTS/CTS)" if self.use_rts_cts else "CSMA/CA"

    def transmit(self, channel_busy: bool = False, collision_prob: float = 0.05) -> MACResult:
        steps: list[str] = []
        cw = self.CW_MIN
        for attempt in range(self.MAX_RETRIES):
            # 1. Wait DIFS
            steps.append(f"Wait DIFS ({self.DIFS_SLOTS} slots) — sensing channel")
            if channel_busy:
                steps.append("  Channel busy — freezing back-off counter")
                channel_busy = False
                continue

            # 2. Random back-off
            bo = random.randint(0, cw - 1)
            steps.append(f"  Channel idle — random back-off = {bo} slots (CW={cw})")

            # 3. Optional RTS/CTS
            if self.use_rts_cts:
                steps.append("  Sending RTS (Request To Send)…")
                if random.random() < 0.05:
                    steps.append("  No CTS received — retry")
                    cw = min(cw * 2, self.CW_MAX)
                    continue
                steps.append(f"  CTS received — waiting SIFS ({self.SIFS_SLOTS} slot)")

            # 4. Transmit
            steps.append(f"Attempt {attempt+1}: transmitting frame")
            if random.random() < max(collision_prob / (attempt + 1), 0.01):
                steps.append(f"  ✗ Collision (inferred — no ACK). CW doubled → {min(cw*2,self.CW_MAX)}")
                cw = min(cw * 2, self.CW_MAX)
            else:
                steps.append("  ✓ Frame sent — waiting ACK (SIFS)")
                steps.append("  ✓ ACK received — transmission complete")
                return MACResult(
                    transmitted=True, attempts=attempt + 1,
                    rts_cts_used=self.use_rts_cts, steps=steps,
                    detail=f"CSMA/CA: success on attempt {attempt+1}",
                )
        return MACResult(
            transmitted=False, attempts=self.MAX_RETRIES, steps=steps,
            detail="CSMA/CA: max retries exceeded",
        )


# ── Registry ─────────────────────────────────────────────────────────────────
MAC_REGISTRY: dict[str, type] = {
    "pure_aloha":    PureAloha,
    "slotted_aloha": SlottedAloha,
    "csma":          CSMA,
    "csma_cd":       CSMACD,
    "csma_ca":       CSMACA,
}
