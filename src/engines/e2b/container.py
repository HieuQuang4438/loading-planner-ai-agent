"""The blocks already placed in one container and the exact checks a new block must pass against
them: constraints 7 and 8, by per-block formulas.

A **block** is `nx * ny * nz` identical items of one line, one orientation: a grid of columns
`px = a + delta` and `py = b + delta` apart, `nz` items high, no gap in z. Every rule mirrors the
independent checker (`src.checker`) without importing it, with its "rests on" relation and its
tolerances: item `u` rests on item `i` when `i`'s top is within `TOUCH` of `u`'s base, `u` is off
the floor, and their footprints overlap by more than `TOUCH` along both x and y.

Inside a block only the bottom layer can rest on other blocks (an upper item sits on the item below
it and is `delta` away from every neighbour column). Between blocks, the "rests on" relation is
separable per axis: bottom item (i, j) of a new block touches top item (i', j') of a block below iff
`Rx[i, i'] and Ry[j, j']`. So:

- **Constraint 7.** Support of bottom item (i, j) = sum over blocks below of `SX[i] * SY[j]`, with
  `SX` the x-overlap length of item i with the touching columns (only overlaps above `TOUCH`
  count, as in the checker) and `SY` likewise; each must reach `alpha` of the base. Upper layers are
  supported 100% by the item below.
- **Constraint 8, load.** The item at the bottom of a column carries `(nz - 1) * m` of its own block
  plus the mass above the column's top item. `extra` (a grid, one entry per top item) bounds that
  last part: the sum, over the blocks resting on this one, of `Rx^T (nz m + extra) Ry`. Summing
  over touched columns can count a shared column twice (never fewer), so the check is safe, not tight.
- **Constraint 8, tiers.** The chain through a column is `down_b + up_t + nz - 2`, with `down_b`
  the longest chain from a bottom item down and `up_t` from a top item up, each a maximum over the
  block's columns (a bound, never below the truth). Placing a block raises `up_t` and `extra` for
  every block below it, directly or transitively.

Blocks go in at non-decreasing z (the lowest space is always taken first), so a new block never
lies under an existing one and only the blocks below it change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

TOUCH = 1e-6  # the checker's tolerance for "rests on" (src.checker.EPS), mirrored exactly
EPS = 1e-9  # engine tolerance: tighter than the checker's, so never looser
INF = float("inf")


@dataclass
class Shape:
    """What a candidate block is made of: one line, one orientation, `nx * ny * nz` items."""

    nx: int
    ny: int
    nz: int
    a: float
    b: float
    c: float
    px: float
    py: float
    mass: float
    tiers: int
    load: float  # inf: unlimited


@dataclass
class Block:
    idx: int
    x0: float
    y0: float
    z0: float
    shape: Shape
    x1: float  # real far faces
    y1: float
    top: float
    down_b: int
    up_t: int = 1
    extra: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    above_links: list[tuple[int, np.ndarray, np.ndarray]] = field(default_factory=list)
    below_idx: list[int] = field(default_factory=list)


@dataclass
class Plan:
    """Everything `Container.commit` needs for one feasible placement."""

    x0: float
    y0: float
    z0: float
    shape: Shape
    links: list[tuple[int, np.ndarray, np.ndarray]]
    down_b: int
    up_new: dict[int, int]
    extra_new: dict[int, np.ndarray]


def axis_overlaps(
    start: float, n: int, size: float, pitch: float, e_start: float, e_n: int, e_size: float, e_pitch: float
) -> np.ndarray:
    """Overlap length, per pair of columns, between the new block's `n` items along one axis and
    another block's `e_n` items."""
    lo = start + np.arange(n) * pitch
    e_lo = e_start + np.arange(e_n) * e_pitch
    return np.minimum((lo + size)[:, None], (e_lo + e_size)[None, :]) - np.maximum(lo[:, None], e_lo[None, :])


class Container:
    def __init__(self, delta: float, alpha: float) -> None:
        self.delta = delta
        self.alpha = alpha
        self.blocks: list[Block] = []
        self.mass = 0.0
        self._cap = 64
        self._box = np.empty((self._cap, 5))  # real bbox x0, x1, y0, y1 and top, per block

    # --- lookup ----------------------------------------------------------------------------------

    def near(self, z: float, x0: float, x1: float, y0: float, y1: float) -> list[int]:
        """Blocks whose top is at height `z` (within TOUCH) and whose real footprint overlaps the
        rectangle by more than TOUCH along both axes."""
        n = len(self.blocks)
        if not n:
            return []
        b = self._box[:n]
        ok = (
            (np.abs(b[:, 4] - z) <= TOUCH)
            & (np.minimum(b[:, 1], x1) - np.maximum(b[:, 0], x0) > TOUCH)
            & (np.minimum(b[:, 3], y1) - np.maximum(b[:, 2], y0) > TOUCH)
        )
        return [int(i) for i in np.flatnonzero(ok)]

    # --- one candidate ---------------------------------------------------------------------------

    def try_place(self, shape: Shape, x0: float, y0: float, z0: float, near: list[int]) -> Plan | None:
        """The plan for putting `shape` with its min corner at (x0, y0, z0), or `None` if constraint 7
        or 8 breaks for the new block or any block below it. Space membership (constraints 4, 5) is the
        caller's business."""
        s = shape
        links: list[tuple[int, np.ndarray, np.ndarray]] = []
        if z0 > TOUCH:
            support = np.zeros((s.nx, s.ny))
            for i in near:
                e = self.blocks[i]
                es = e.shape
                ox = axis_overlaps(x0, s.nx, s.a, s.px, e.x0, es.nx, es.a, es.px)
                rx = ox > TOUCH
                if not rx.any():
                    continue
                oy = axis_overlaps(y0, s.ny, s.b, s.py, e.y0, es.ny, es.b, es.py)
                ry = oy > TOUCH
                if not ry.any():
                    continue
                support += np.outer((ox * rx).sum(axis=1), (oy * ry).sum(axis=1))
                links.append((i, rx.astype(float), ry.astype(float)))
            if not links or (support < self.alpha * s.a * s.b - 1e-12).any():
                return None
        return self._stack(s, x0, y0, z0, links)

    def _stack(
        self, s: Shape, x0: float, y0: float, z0: float, links: list[tuple[int, np.ndarray, np.ndarray]]
    ) -> Plan | None:
        blocks = self.blocks
        down_b = 1 + max((blocks[i].shape.nz - 1 + blocks[i].down_b for i, _, _ in links), default=0)
        if down_b + s.nz - 1 > s.tiers:
            return None
        plan = Plan(x0, y0, z0, s, links, down_b, {}, {})
        if not links:
            return plan
        direct = {i: (rx, ry) for i, rx, ry in links}
        closure = set(direct)
        todo = list(direct)
        while todo:
            for j in blocks[todo.pop()].below_idx:
                if j not in closure:
                    closure.add(j)
                    todo.append(j)
        weight_n = s.nz * s.mass
        for i in sorted(closure, key=lambda j: -blocks[j].z0):
            e = blocks[i]
            es = e.shape
            up = e.up_t
            grid = np.zeros((es.nx, es.ny))
            for a_idx, rx, ry in e.above_links:
                a = blocks[a_idx]
                if a_idx in plan.up_new:
                    up = max(up, a.shape.nz + plan.up_new[a_idx])
                    extra = plan.extra_new[a_idx]
                else:
                    extra = a.extra
                grid += rx.T @ (a.shape.nz * a.shape.mass + extra) @ ry
            if i in direct:
                rx, ry = direct[i]
                up = max(up, s.nz + 1)
                grid += weight_n * np.outer(rx.sum(axis=0), ry.sum(axis=0))
            if e.down_b + up + es.nz - 2 > es.tiers:
                return None
            if es.load != INF and es.load - (es.nz - 1) * es.mass - grid.max() < -EPS:
                return None
            plan.up_new[i] = up
            plan.extra_new[i] = grid
        return plan

    # --- commit ----------------------------------------------------------------------------------

    def commit(self, plan: Plan) -> Block:
        s = plan.shape
        k = len(self.blocks)
        block = Block(
            idx=k, x0=plan.x0, y0=plan.y0, z0=plan.z0, shape=s,
            x1=plan.x0 + s.nx * s.px - self.delta, y1=plan.y0 + s.ny * s.py - self.delta,
            top=plan.z0 + s.nz * s.c, down_b=plan.down_b, extra=np.zeros((s.nx, s.ny)),
            below_idx=[i for i, _, _ in plan.links],
        )
        for i, rx, ry in plan.links:
            self.blocks[i].above_links.append((k, rx, ry))
        for i, up in plan.up_new.items():
            self.blocks[i].up_t = up
            self.blocks[i].extra = plan.extra_new[i]
        if k == self._cap:
            self._cap *= 2
            grown = np.empty((self._cap, 5))
            grown[:k] = self._box[:k]
            self._box = grown
        self._box[k] = (block.x0, block.x1, block.y0, block.y1, block.top)
        self.blocks.append(block)
        self.mass += s.nx * s.ny * s.nz * s.mass
        return block
