"""The boxes already placed in one container, and the exact checks a new box must pass against them
: collision with the `delta` gap (constraint 5),
support (constraint 7) and stacking (constraint 8).

Every rule mirrors the independent checker (`src.checker`) without importing it:

- **Rests on.** Box `u` rests on box `i` when `i`'s top is within `TOUCH` of `u`'s bottom, `u` is
  off the floor, and their footprints overlap by more than `TOUCH` along both x and y -- the
  checker's own relation and tolerance, so the load and tier sums below run over exactly the pairs
  the checker will find.
- **Support.** Off the floor, the overlap area with the boxes it rests on is at least `alpha` of the
  base.
- **Load.** Each box carries the full mass of every box reachable upward through "rests on" (trên* constraint 8), at most its `load`.
- **Tiers.** down(j) + up(j) - 1 <= tiers_j, with down/up the longest chains of boxes through `j`.

Placing box `k` can only change these figures for boxes comparable with `k`: the ones below it (the
downward closure D, which gain `k` and everything above `k` in their load, and may gain height
above) and the ones above it (the upward closure U, non-empty only when `k` fills a gap under a box
already there, which may gain depth below). Every other box keeps its closures and chain lengths.

Collision, support and resting use the real footprint; the `delta` gap (constraint 5) is checked
between boxes whose z ranges overlap, the same test as the checker's, with a tighter tolerance.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.engines.base import Piece

EPS = 1e-9  # geometric tolerance of the engine: tighter than the checker's, so never looser
TOUCH = 1e-6  # the checker's tolerance for "rests on" (src.checker.EPS), mirrored exactly
INF = float("inf")


@dataclass(frozen=True)
class Stacking:
    """Everything `Layout.add` needs to commit one feasible placement: the new box's direct
    supports and the boxes resting on its top, and the new chain lengths of every comparable box."""

    below: tuple[int, ...]
    above: tuple[int, ...]
    down_set: frozenset[int]  # every box reachable downward from the new one (D)
    up_set: frozenset[int]  # every box reachable upward from the new one (U)
    down: int
    up: int
    added_load: dict[int, float]  # box in D -> mass newly resting on it
    new_up: dict[int, int]  # box in D -> its new longest chain upward
    new_down: dict[int, int]  # box in U -> its new longest chain downward
    load_left: float  # the new box's own load minus the mass of U


class Layout:
    def __init__(self, capacity: int, delta: float) -> None:
        self.delta = delta
        self.n = 0
        self.x0 = np.empty(capacity)
        self.y0 = np.empty(capacity)
        self.z0 = np.empty(capacity)
        self.x1 = np.empty(capacity)  # real far faces: x0 + extent
        self.y1 = np.empty(capacity)
        self.z1 = np.empty(capacity)
        self.spare = np.empty(capacity)  # load_left, as an array for `supported`
        self.room = np.empty(capacity, dtype=np.int64)  # tiers - down: how many more tiers may go above
        self.pieces: list[Piece] = []
        self.codes: list[str] = []
        self.below: list[list[int]] = []
        self.above: list[list[int]] = []
        self.down_set: list[set[int]] = []
        self.up_set: list[set[int]] = []
        self.down: list[int] = []
        self.up: list[int] = []
        self.load_left: list[float] = []
        self.mass = 0.0

    # --- batch tests over many candidate corners -------------------------------------------------

    def collision_free(self, xs: np.ndarray, ys: np.ndarray, z: np.ndarray, a: np.ndarray, b: np.ndarray, c: float | np.ndarray) -> np.ndarray:
        """Per candidate (corner xs, ys, z; extents a, b along x, y; height c): no box overlaps it,
        and every box at a shared height is at least `delta` away along x or y."""
        n = self.n
        if n == 0:
            return np.ones(len(xs), dtype=bool)
        d = self.delta
        x0, y0, z0 = self.x0[:n], self.y0[:n], self.z0[:n]
        x1, y1, z1 = self.x1[:n], self.y1[:n], self.z1[:n]
        vertical = (z0[None, :] < z[:, None] + np.atleast_1d(c)[:, None] - EPS) & (z[:, None] < z1[None, :] - EPS)
        apart = (
            (xs[:, None] + a[:, None] + d <= x0[None, :] + EPS)
            | (x1[None, :] + d <= xs[:, None] + EPS)
            | (ys[:, None] + b[:, None] + d <= y0[None, :] + EPS)
            | (y1[None, :] + d <= ys[:, None] + EPS)
        )
        return ~np.any(vertical & ~apart, axis=1)

    def supported(
        self, xs: np.ndarray, ys: np.ndarray, z: np.ndarray, a: np.ndarray, b: np.ndarray, alpha: float, mass: float
    ) -> np.ndarray:
        """Per candidate: on the floor, or at least `alpha` of its base on tops it rests on, each of
        which still has `mass` of load to spare and room for one more tier above it -- a cheap
        necessary part of constraint 8, so that `stacking` runs on fewer candidates."""
        on_floor = z <= TOUCH
        n = self.n
        if n == 0:
            return on_floor
        ox, oy, touching = self._contact(xs, ys, z, a, b, self.z1[:n])
        area = np.where(touching, ox * oy, 0.0).sum(axis=1)
        weak = (self.spare[:n] < mass - EPS) | (self.room[:n] < 1)
        return on_floor | ((area >= alpha * a * b - 1e-12) & ~np.any(touching & weak[None, :], axis=1))

    def _contact(
        self, xs: np.ndarray, ys: np.ndarray, level: np.ndarray, a: np.ndarray, b: np.ndarray, faces: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Footprint overlaps along x and y with every box, and which boxes have a face in `faces`
        (their tops or bottoms) at `level` over a positive overlap -- the checker's "rests on" test."""
        n = self.n
        ox = np.minimum(xs[:, None] + a[:, None], self.x1[None, :n]) - np.maximum(xs[:, None], self.x0[None, :n])
        oy = np.minimum(ys[:, None] + b[:, None], self.y1[None, :n]) - np.maximum(ys[:, None], self.y0[None, :n])
        touching = (np.abs(faces[None, :] - level[:, None]) <= TOUCH) & (ox > TOUCH) & (oy > TOUCH)
        return ox, oy, touching

    # --- one candidate: constraint 8 -------------------------------------------------------------

    def stacking(self, x: float, y: float, z: float, a: float, b: float, c: float, piece: Piece) -> Stacking | None:
        """The load and tier consequences of putting `piece` at (x, y, z) with extents (a, b, c), or
        `None` if some box -- the new one or one comparable with it -- would break constraint 8."""
        below = self._resting(x, y, z, a, b, self.z1, lower=True) if z > TOUCH else ()
        above = self._resting(x, y, z + c, a, b, self.z0, lower=False)
        down = 1 + max((self.down[i] for i in below), default=0)
        up = 1 + max((self.up[j] for j in above), default=0)
        if down + up - 1 > piece.tiers:
            return None
        down_set = set(below).union(*(self.down_set[i] for i in below))
        up_set = set(above).union(*(self.up_set[j] for j in above))
        up_mass = sum(self.pieces[j].mass for j in up_set)
        load_left = (INF if piece.load is None else piece.load) - up_mass
        if load_left < -EPS:
            return None

        added_load: dict[int, float] = {}
        for i in down_set:
            new = up_set - self.up_set[i] if up_set else ()
            added = piece.mass + sum(self.pieces[j].mass for j in new)
            if added > self.load_left[i] + EPS:
                return None
            added_load[i] = added
        new_up = self._chains(down_set, below, up, downward=True)
        new_down = self._chains(up_set, above, down, downward=False)
        for i, u in new_up.items():
            if self.down[i] + u - 1 > self.pieces[i].tiers:
                return None
        for j, d in new_down.items():
            if d + self.up[j] - 1 > self.pieces[j].tiers:
                return None
        return Stacking(
            below=tuple(below), above=tuple(above), down_set=frozenset(down_set), up_set=frozenset(up_set),
            down=down, up=up, added_load=added_load, new_up=new_up, new_down=new_down, load_left=load_left,
        )

    def _resting(self, x: float, y: float, level: float, a: float, b: float, faces: np.ndarray, lower: bool) -> tuple[int, ...]:
        """Boxes whose top (`lower`) or bottom touches `level` over the footprint -- the checker's
        "rests on" pairs the new box would join. A box on the floor rests on nothing."""
        n = self.n
        if n == 0:
            return ()
        ox, oy, touching = self._contact(
            np.array([x]), np.array([y]), np.array([level]), np.array([a]), np.array([b]), faces[:n]
        )
        hits = np.flatnonzero(touching[0])
        if not lower:
            hits = hits[self.z0[hits] > TOUCH]
        return tuple(int(i) for i in hits)

    def _chains(self, closure: set[int], direct: tuple[int, ...], own: int, downward: bool) -> dict[int, int]:
        """For every box of `closure` (all below the new box when `downward`, else all above it):
        its longest chain away from the new box's side once the new box and its `own` chain length
        on the far side are added. Edges run between boxes in `closure`, nearest first."""
        if not closure:
            return {}
        # Nearest first: going down, higher boxes first; going up, lower boxes first.
        order = sorted(closure, key=lambda i: -self.z0[i] if downward else self.z0[i])
        direct_set = set(direct)
        hops: dict[int, int] = {}  # edges from the new box to this one along the longest path
        for i in order:
            links = self.above[i] if downward else self.below[i]
            best = 1 if i in direct_set else 0
            for u in links:
                if u in hops:
                    best = max(best, hops[u] + 1)
            hops[i] = best
        chains = self.up if downward else self.down
        return {i: max(chains[i], h + own) for i, h in hops.items()}

    # --- commit ----------------------------------------------------------------------------------

    def add(self, piece: Piece, code: str, x: float, y: float, z: float, dims: tuple[float, float, float], s: Stacking) -> int:
        k = self.n
        a, b, c = dims
        self.x0[k], self.y0[k], self.z0[k] = x, y, z
        self.x1[k], self.y1[k], self.z1[k] = x + a, y + b, z + c
        self.n += 1
        self.pieces.append(piece)
        self.codes.append(code)
        self.mass += piece.mass
        self.below.append(list(s.below))
        self.above.append(list(s.above))
        for i in s.below:
            self.above[i].append(k)
        for j in s.above:
            self.below[j].append(k)
        self.down_set.append(set(s.down_set))
        self.up_set.append(set(s.up_set))
        self.down.append(s.down)
        self.up.append(s.up)
        self.load_left.append(s.load_left)
        self.spare[k] = s.load_left
        self.room[k] = piece.tiers - s.down
        grown_up = s.up_set | {k}
        for i in s.down_set:
            self.up_set[i] |= grown_up
            self.load_left[i] -= s.added_load[i]
            self.spare[i] = self.load_left[i]
            self.up[i] = s.new_up[i]
        grown_down = s.down_set | {k}
        for j in s.up_set:
            self.down_set[j] |= grown_down
            self.down[j] = s.new_down[j]
            self.room[j] = self.pieces[j].tiers - self.down[j]
        return k
