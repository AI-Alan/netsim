"""
Hub first-hop multi-station contention (structural collision when k>=2 transmit same slot).
Educational slot scheduler with BEB-style backoff — not full PHY timing.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, List

from simulation.events import EventType, LayerName, PDU, SimEvent


@dataclass
class FlowSeed:
    flow_index: int
    src: str
    dst: str
    payload: bytes
    start_slot: int = 0


def contend_hub_first_hop(
    flows: List[FlowSeed],
    *,
    mac_protocol: str,
    collision_prob: float,
    rng: random.Random,
    emit_access: Callable[..., None],
) -> List[FlowSeed]:
    """
    Slot simulation: flows sharing a hub CD contend until each has one successful first-hop slot.
    Returns flows in the order they cleared the medium (for sequential pending enqueue).
    """
    if len(flows) <= 1:
        return list(flows)

    remaining = list(flows)
    cleared: List[FlowSeed] = []
    next_slot: dict[int, int] = {f.flow_index: max(0, f.start_slot) for f in remaining}
    attempt_no: dict[int, int] = {f.flow_index: 0 for f in remaining}
    max_iters = 20000
    it = 0

    while remaining and it < max_iters:
        it += 1
        t = min(next_slot[f.flow_index] for f in remaining)
        at_t = [f for f in remaining if next_slot[f.flow_index] == t]
        if len(at_t) == 1:
            w = at_t[0]
            attempt_no[w.flow_index] += 1
            emit_access(
                w.src,
                w.dst,
                w.flow_index,
                mac_protocol,
                True,
                attempt_no[w.flow_index],
                [
                    f"Slot {t}: first hop on shared hub — sole transmitter",
                    "  ✓ Frame cleared for forwarding",
                ],
                f"{mac_protocol}: first-hop success (flow {w.flow_index})",
            )
            remaining.remove(w)
            cleared.append(w)
            continue
        for f in at_t:
            attempt_no[f.flow_index] += 1
            k = max(0, attempt_no[f.flow_index] - 1)
            backoff = rng.randint(0, min(2 ** min(k, 10) - 1, 1023)) if k > 0 else rng.randint(0, 1)
            next_slot[f.flow_index] = t + 1 + backoff
            steps = [
                f"Slot {t}: {len(at_t)} stations contend — structural collision",
                f"  ✗ COLLISION — BEB backoff = {backoff} slots",
            ]
            if collision_prob > 0 and rng.random() < collision_prob:
                steps.append(f"  (random channel failure p={collision_prob:.3f})")
            emit_access(
                f.src,
                f.dst,
                f.flow_index,
                mac_protocol,
                False,
                attempt_no[f.flow_index],
                steps,
                f"{mac_protocol}: first-hop collision (flow {f.flow_index})",
            )

    for f in remaining:
        emit_access(
            f.src,
            f.dst,
            f.flow_index,
            mac_protocol,
            True,
            attempt_no[f.flow_index] + 1,
            [
                "Contention limit — forcing first-hop success (demo)",
                "  ✓ Frame proceeds",
            ],
            f"{mac_protocol}: first-hop forced success (flow {f.flow_index})",
        )
        cleared.append(f)

    return cleared
