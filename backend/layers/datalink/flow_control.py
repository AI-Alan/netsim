"""
layers/datalink/flow_control.py
---------------------------------
IFlowControl (Strategy) + Stop-and-Wait ARQ, Go-Back-N ARQ, Selective Repeat ARQ.

Each protocol simulates the ARQ exchange and returns a FlowResult with
a full step-log for the frontend to display educationally.

Pattern: Strategy — DataLinkLayer picks ARQ protocol at runtime.
OCP     — new ARQ added by implementing IFlowControl.
"""
from __future__ import annotations
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlowResult:
    frames_sent:      int
    frames_acked:     int
    retransmissions:  int
    efficiency:       float        # acked / sent
    steps:            list[str]    = field(default_factory=list)
    detail:           str          = ""


class IFlowControl(ABC):
    @abstractmethod
    def transfer(self, total_frames: int, error_rate: float = 0.0) -> FlowResult:
        """Simulate sending `total_frames` frames and return ARQ statistics."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def window_size(self) -> int: ...


# ── Stop-and-Wait ARQ ─────────────────────────────────────────────────────────
class StopAndWaitARQ(IFlowControl):
    """
    Window = 1. Sender transmits ONE frame, waits for ACK/NAK (or timeout).
    On NAK / timeout: retransmit that frame.
    Simple but inefficient for high-BDP links.
    """
    TIMEOUT_SLOTS = 3

    @property
    def name(self) -> str: return "Stop-and-Wait ARQ"

    @property
    def window_size(self) -> int: return 1

    def transfer(self, total_frames: int, error_rate: float = 0.0) -> FlowResult:
        steps: list[str] = []
        sent = retx = 0
        seq = 0
        for frame_no in range(total_frames):
            while True:
                sent += 1
                steps.append(f"Frame {frame_no} (seq={seq%2}): SENT → waiting ACK")
                if random.random() < error_rate:
                    steps.append(f"  ✗ Error / timeout — retransmitting frame {frame_no}")
                    retx += 1
                else:
                    steps.append(f"  ✓ ACK {seq%2} received")
                    seq += 1
                    break
        eff = total_frames / sent if sent else 1.0
        return FlowResult(frames_sent=sent, frames_acked=total_frames,
                          retransmissions=retx, efficiency=eff, steps=steps,
                          detail=f"SAW: {total_frames} frames, {retx} retx, η={eff:.2%}")


# ── Go-Back-N ARQ ─────────────────────────────────────────────────────────────
class GoBackNARQ(IFlowControl):
    """
    Sender can have up to N unacknowledged frames in flight.
    On error in frame k: retransmit k, k+1, …, k+N-1 (go back N).
    Window bits = ceil(log2(N+1)); sequence numbers wrap.
    """

    def __init__(self, window: int = 4) -> None:
        self._window = window

    @property
    def name(self) -> str: return f"Go-Back-N ARQ (W={self._window})"

    @property
    def window_size(self) -> int: return self._window

    def transfer(self, total_frames: int, error_rate: float = 0.0) -> FlowResult:
        steps: list[str] = []
        sent = retx = acked = 0
        base = 0
        next_seq = 0

        while base < total_frames:
            window_end = min(base + self._window, total_frames)
            batch = list(range(next_seq, window_end))
            if not batch:
                break

            steps.append(f"Window [{base}–{window_end-1}]: sending {len(batch)} frames")
            error_in = -1
            for seq in batch:
                sent += 1
                steps.append(f"  → Frame {seq} sent")
                if random.random() < error_rate and error_in < 0:
                    error_in = seq

            if error_in >= 0:
                go_back = window_end - error_in
                retx += go_back
                sent += go_back
                steps.append(f"  ✗ Error at frame {error_in} — go back {go_back} frames, retransmit")
                next_seq = error_in
            else:
                steps.append(f"  ✓ ACK {window_end-1} cumulative — window advances")
                acked += len(batch)
                base = window_end
                next_seq = window_end

        eff = acked / sent if sent else 1.0
        return FlowResult(frames_sent=sent, frames_acked=acked, retransmissions=retx,
                          efficiency=eff, steps=steps,
                          detail=f"GBN W={self._window}: {acked} acked, {retx} retx, η={eff:.2%}")


# ── Selective Repeat ARQ ──────────────────────────────────────────────────────
class SelectiveRepeatARQ(IFlowControl):
    """
    Sender retransmits ONLY the damaged / lost frame (not the whole window).
    Receiver buffers out-of-order frames.
    Window size ≤ 2^(seq_bits-1) for correct operation.
    Most efficient ARQ at high error rates.
    """

    def __init__(self, window: int = 4) -> None:
        self._window = window

    @property
    def name(self) -> str: return f"Selective Repeat ARQ (W={self._window})"

    @property
    def window_size(self) -> int: return self._window

    def transfer(self, total_frames: int, error_rate: float = 0.0) -> FlowResult:
        steps: list[str] = []
        sent = retx = 0
        receiver_buffer: set[int] = set()
        pending: list[int] = list(range(total_frames))
        acked: set[int] = set()

        base = 0
        while base < total_frames:
            window_end = min(base + self._window, total_frames)
            batch = [f for f in range(base, window_end) if f not in acked]
            if not batch:
                base += 1
                continue

            steps.append(f"Window [{base}–{window_end-1}]: transmitting {batch}")
            errored: list[int] = []
            for seq in batch:
                sent += 1
                if random.random() < error_rate:
                    errored.append(seq)
                    steps.append(f"  ✗ Frame {seq} lost/errored")
                else:
                    receiver_buffer.add(seq)
                    steps.append(f"  ✓ Frame {seq} received, buffered")

            # Receiver sends selective NAK/ACK
            for seq in receiver_buffer:
                if seq not in acked:
                    acked.add(seq)
                    steps.append(f"  ← ACK {seq}")

            for seq in errored:
                retx += 1
                sent += 1
                receiver_buffer.add(seq)
                acked.add(seq)
                steps.append(f"  ↺ Selective retransmit frame {seq} → ✓ ACK {seq}")

            # Advance base
            while base in acked:
                base += 1

        eff = len(acked) / sent if sent else 1.0
        return FlowResult(frames_sent=sent, frames_acked=len(acked), retransmissions=retx,
                          efficiency=eff, steps=steps,
                          detail=f"SR W={self._window}: {len(acked)} acked, {retx} retx, η={eff:.2%}")


# ── Registry ─────────────────────────────────────────────────────────────────
FLOW_REGISTRY: dict[str, type] = {
    "stop_and_wait":    StopAndWaitARQ,
    "go_back_n":        GoBackNARQ,
    "selective_repeat": SelectiveRepeatARQ,
}
