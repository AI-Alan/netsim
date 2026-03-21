"""
simulation/engine.py
---------------------
SimulationEngine — priority-queue discrete-time simulation core.
Patterns: Observer (emit via callback), State machine (SimState).
"""
from __future__ import annotations
import heapq, logging
from enum import Enum
from typing import Callable, List, Optional
from simulation.events import SimEvent

logger = logging.getLogger(__name__)


class SimState(str, Enum):
    RUNNING  = "RUNNING"
    PAUSED   = "PAUSED"
    STEPPING = "STEPPING"
    STOPPED  = "STOPPED"


class _Entry:
    __slots__ = ("timestamp", "seq", "event")
    def __init__(self, event: SimEvent, seq: int) -> None:
        self.timestamp = event.timestamp
        self.seq = seq
        self.event = event
    def __lt__(self, other: "_Entry") -> bool:
        return (self.timestamp, self.seq) < (other.timestamp, other.seq)


class SimulationEngine:
    def __init__(self, emit_callback: Optional[Callable[[SimEvent], None]] = None) -> None:
        self._queue: List[_Entry] = []
        self._seq = 0
        self._log: List[SimEvent] = []
        self.clock: float = 0.0
        self.state: SimState = SimState.STOPPED
        self._emit: Callable = emit_callback or (lambda e: None)

    def schedule(self, event: SimEvent) -> None:
        heapq.heappush(self._queue, _Entry(event, self._seq))
        self._seq += 1

    def run(self) -> None:
        self.state = SimState.RUNNING
        while self._queue and self.state == SimState.RUNNING:
            self._next()
        self.state = SimState.STOPPED

    def pause(self) -> None:   self.state = SimState.PAUSED
    def resume(self) -> None:
        if self.state == SimState.PAUSED: self.state = SimState.RUNNING

    def step(self) -> Optional[SimEvent]:
        self.state = SimState.STEPPING
        if not self._queue:
            self.state = SimState.STOPPED; return None
        return self._next()

    def rewind(self, to_time: float) -> List[SimEvent]:
        return [e for e in self._log if e.timestamp <= to_time]

    def reset(self) -> None:
        self._queue.clear(); self._log.clear()
        self._seq = 0; self.clock = 0.0; self.state = SimState.STOPPED

    def _next(self) -> SimEvent:
        entry = heapq.heappop(self._queue)
        self.clock = entry.timestamp
        self._log.append(entry.event)
        self._emit(entry.event)
        return entry.event
