"""Surplus removal and solution assembly for E5.

The integer master covers each line `>= qty`; the chosen containers may hold more items of a line
than the lot has. A surplus item is removed only if **nothing rests on it**: every constraint then
still holds for what is left (no item loses support, loads and tier counts below it only drop, gaps
only widen, the container only gets lighter). Among such items of the line, the highest one goes
first (top down). A container left empty is dropped.

If every remaining surplus item of a line has something resting on it, the containers holding that
line are re-laid by the packing core without the surplus items (fallback, `repack`); a container is
only replaced when the core places every item it must keep. If that fails too, trimming fails and
the caller drops this master solution; this never relaxes a rule.
"""
from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass

from src.engines.e5.pool import AnyColumn, Slot
from src.model import ContainerType, Instance, Params, Placement, Solution, UsedContainer, item_id

EPS = 1e-6  # matches src.checker.EPS


@dataclass
class Loaded:
    """One chosen container: its type and the layout still in it."""

    type: ContainerType
    slots: list[Slot]
    source: str = ""  # which pool column the layout came from (diagnostics only)


class TrimFailed(RuntimeError):
    """Some surplus item could not be removed without touching an item above it. `line`, `surplus`, `left`:
    the line that failed, its surplus in the cover handed to `trim`, how much of it could not be removed
    (E5 re-solves the master with that line's cover capped; `None`/0 when a line is short)."""

    def __init__(self, message: str, line: str | None = None, surplus: int = 0, left: int = 0) -> None:
        super().__init__(message)
        self.line, self.surplus, self.left = line, surplus, left


def expand(columns: list[AnyColumn], counts: dict[int, int]) -> list[Loaded]:
    return [Loaded(columns[p].type, list(columns[p].layout), columns[p].source) for p, n in sorted(counts.items()) for _ in range(n)]


Repack = Callable[[ContainerType, list[str]], "list[Slot] | None"]


@dataclass
class TrimResult:
    boxes: list[Loaded]
    removed: int  # surplus items taken off the top
    repacked: int  # containers re-laid by the core (fallback)


def trim(instance: Instance, boxes: list[Loaded], repack: Repack | None = None) -> TrimResult:
    """Removes surplus items top down, then (if some remain and `repack` is given) re-lays whole
    containers without them.

    Top down: per container, which items rest on which is computed once; a removal only frees the
    items it rested on. Free-topped items of each line with surplus wait in a heap by height (highest
    first; ties: first container, then first in its layout). Lines are swept until none has surplus or
    a sweep removes nothing (removing a surplus item of one line can free an item of an earlier one).

    Fallback: for a line still in surplus, the containers holding it, most such items first, are
    asked to `repack` (the core, on an empty container of the same type) their items minus the
    surplus ones; a container is replaced only when the core places every item asked for."""
    dims = {line.id: line for line in instance.items}
    have: dict[str, int] = {line.id: 0 for line in instance.items}
    for box in boxes:
        for s in box.slots:
            have[s[0]] += 1
    short = [line.id for line in instance.items if have[line.id] < line.qty]
    if short:
        raise TrimFailed(f"line {short[0]} short by {dims[short[0]].qty - have[short[0]]}")
    surplus = {line.id: have[line.id] - line.qty for line in instance.items}
    if not any(surplus.values()):
        return TrimResult(boxes, 0, 0)

    below: list[list[list[int]]] = []  # per box, per slot: slots it rests on
    above_count: list[list[int]] = []
    heaps: dict[str, list[tuple[float, int, int]]] = {line: [] for line, n in surplus.items() if n}
    for b, box in enumerate(boxes):
        rests = _resting(box.slots, dims)
        below.append(rests)
        count = [0] * len(box.slots)
        for lower in rests:
            for i in lower:
                count[i] += 1
        above_count.append(count)
        for j, s in enumerate(box.slots):
            if count[j] == 0 and s[0] in heaps:
                heapq.heappush(heaps[s[0]], (-s[3], b, j))
    removed_slots: set[tuple[int, int]] = set()
    removed = 0
    progress = True
    while progress and any(surplus.values()):
        progress = False
        for line in instance.items:
            heap = heaps.get(line.id)
            while surplus[line.id] > 0 and heap:
                _, b, j = heapq.heappop(heap)
                removed_slots.add((b, j))
                surplus[line.id] -= 1
                removed += 1
                progress = True
                for i in below[b][j]:
                    above_count[b][i] -= 1
                    other = boxes[b].slots[i]
                    if above_count[b][i] == 0 and other[0] in heaps and surplus[other[0]] > 0:
                        heapq.heappush(heaps[other[0]], (-other[3], b, i))
    out = []
    for b, box in enumerate(boxes):
        slots = [s for j, s in enumerate(box.slots) if (b, j) not in removed_slots]
        if slots:
            out.append(Loaded(box.type, slots, box.source))

    repacked = 0
    for line in instance.items:
        if surplus[line.id] == 0:
            continue
        if repack is None:
            raise TrimFailed(f"no free-topped item of line {line.id}", line.id, have[line.id] - line.qty,
                             surplus[line.id])
        order = sorted(range(len(out)), key=lambda b: -sum(1 for s in out[b].slots if s[0] == line.id))
        for b in order:
            n = sum(1 for s in out[b].slots if s[0] == line.id)
            if n == 0 or surplus[line.id] == 0:
                break
            k = min(n, surplus[line.id])
            keep = [s[0] for s in out[b].slots]
            for _ in range(k):
                keep.remove(line.id)
            slots = repack(out[b].type, keep) if keep else []
            if slots is None:
                continue
            out[b] = Loaded(out[b].type, slots, out[b].source)
            surplus[line.id] -= k
            removed += k
            repacked += 1
        if surplus[line.id] > 0:
            raise TrimFailed(f"line {line.id}: {surplus[line.id]} surplus item(s) neither free-topped nor repackable",
                             line.id, have[line.id] - line.qty, surplus[line.id])
    return TrimResult([b for b in out if b.slots], removed, repacked)


def _resting(slots: list[Slot], dims: dict) -> list[list[int]]:
    """For each slot, the slots it rests on: their top within EPS of its base, footprints
    overlapping (the checker's "rests on", same tolerance)."""
    ext = [(x, y, z, *dims[line].dims(o)) for line, x, y, z, o in slots]
    out: list[list[int]] = []
    for j, (x, y, z, l, w, _) in enumerate(ext):
        lower = []
        if z > EPS:
            for i, (ox, oy, oz, ol, ow, oh) in enumerate(ext):
                if i != j and abs(oz + oh - z) <= EPS and min(x + l, ox + ol) - max(x, ox) > EPS                         and min(y + w, oy + ow) - max(y, oy) > EPS:
                    lower.append(i)
        out.append(lower)
    return out


def to_solution(instance: Instance, params: Params, boxes: list[Loaded]) -> Solution:
    """Numbers each line's items 1..n across the containers, in container order."""
    next_n: dict[str, int] = {line.id: 0 for line in instance.items}
    containers, placements = [], []
    for k, box in enumerate(boxes, start=1):
        containers.append(UsedContainer(k=k, type=box.type.id))
        for line, x, y, z, o in box.slots:
            next_n[line] += 1
            placements.append(Placement(item_id(line, next_n[line]), k, x, y, z, o))
    return Solution(instance=instance.name, params=params, containers=containers, placements=placements)
