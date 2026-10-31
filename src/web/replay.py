"""Order in which the web page replays one container's placements.

The page replays the engine's own placement order when every piece rests only on pieces listed
before it. Some engines break that (E2's core can fill a gap under an already placed overhanging
piece, and the checker then counts that piece as supported by the new one), and some do not list
placements in placing order at all. Then the order is rebuilt: z, then x, then y ascending. A rebuilt
order always has supporters first, because a supporter's top touches the supported piece's base, so
its z is strictly smaller.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.model import Instance, Solution, line_of

EPS = 1e-6  # same tolerance as src.checker: touching tops and positive shared base area

ENGINE_ORDER = "engine"
REBUILT_ORDER = "rebuilt"


@dataclass(frozen=True)
class Box:
    """A placed piece as an axis-aligned box: minimum corner and extents along x, y, z."""

    item: str
    x: float
    y: float
    z: float
    l: float
    w: float
    h: float


@dataclass(frozen=True)
class ReplayOrder:
    k: int
    indices: tuple[int, ...]  # positions in `solution.placements`, in replay order
    source: str  # ENGINE_ORDER or REBUILT_ORDER


def boxes_of(instance: Instance, solution: Solution) -> list[Box]:
    """One box per placement, in placement order; a placement of an unknown item or orientation is an error."""
    boxes = []
    for p in solution.placements:
        line = instance.line(line_of(p.item))
        if line is None:
            raise ValueError(f"{p.item}: not an item of the instance")
        l, w, h = line.dims(p.o)
        boxes.append(Box(p.item, p.x, p.y, p.z, l, w, h))
    return boxes


def _overlap(start_a: float, size_a: float, start_b: float, size_b: float) -> float:
    return min(start_a + size_a, start_b + size_b) - max(start_a, start_b)


def supporters(boxes: list[Box], members: list[int]) -> dict[int, list[int]]:
    """For each member above the floor, the members it rests on (same relation as the checker's)."""
    result: dict[int, list[int]] = {}
    for j in members:
        upper = boxes[j]
        if upper.z <= EPS:
            continue
        result[j] = [
            i for i in members
            if abs(boxes[i].z + boxes[i].h - upper.z) <= EPS
            and _overlap(upper.x, upper.l, boxes[i].x, boxes[i].l) > EPS
            and _overlap(upper.y, upper.w, boxes[i].y, boxes[i].w) > EPS
        ]
    return result


def supporters_first(boxes: list[Box], order: list[int], rests_on: dict[int, list[int]]) -> bool:
    """Whether every piece comes after all the pieces it rests on."""
    position = {index: n for n, index in enumerate(order)}
    return all(position[i] < position[j] for j, below in rests_on.items() for i in below)


def replay_orders(instance: Instance, solution: Solution) -> dict[int, ReplayOrder]:
    """Replay order per open container: the engine's when valid, otherwise rebuilt."""
    boxes = boxes_of(instance, solution)
    by_container: dict[int, list[int]] = {used.k: [] for used in solution.containers}
    for index, p in enumerate(solution.placements):
        by_container.setdefault(p.k, []).append(index)
    orders: dict[int, ReplayOrder] = {}
    for k, members in by_container.items():
        rests_on = supporters(boxes, members)
        if supporters_first(boxes, members, rests_on):
            orders[k] = ReplayOrder(k, tuple(members), ENGINE_ORDER)
        else:
            rebuilt = sorted(members, key=lambda i: (boxes[i].z, boxes[i].x, boxes[i].y))
            orders[k] = ReplayOrder(k, tuple(rebuilt), REBUILT_ORDER)
    return orders
