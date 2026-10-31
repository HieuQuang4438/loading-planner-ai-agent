"""E2b's packing core for one container: block building
over maximal spaces, greedy.

Items of one line (same size, mass, tiers, load, tiltability) form a **type**. A **block** is
`nx * ny * nz` items of one type in one orientation, `delta` apart across, stacked without a gap
(`nz <= tiers`, `(nz - 1) * m <= load`). The core takes the space with the lowest corner (`z`, then
`x`, then `y`) and puts into it the block with the largest measure (volume, or base area, per
`Config`) that passes the exact checks of `src.engines.e2b.container`; a space that takes no block is
dropped for good (the checks only tighten as the container fills). Placing a block cuts the spaces
(`src.engines.e2b.spaces`).

**Where in the space.** A block goes at a corner of the space: (min x, min y) first; when the space
floor is above the container floor, also the three other corners, since support may be under any
of them.

**Search order.** Every (type, orientation) has an upper bound on the measure of any block it can
form in the space (as many items as fit, remaining count and remaining mass allow). They are
tried in bound order and expanded lazily into concrete `(nx, ny, nz)` candidates, best first; the
search stops when the next bound cannot beat the best block already found. At most `MAX_TRIES`
candidates are checked per space.

Orientation follows E1 and E2 (`src.engines.e1.orientation`): upright unless forced to tilt, and
also turned 90° about the vertical axis when the door allows. Every orientation is one "way" of the
type. No `hints`: E2b is not a decoder for E3, E4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from src.engines.base import Piece
from src.engines.e1.orientation import base_orientation, floor_ok, rotated
from src.engines.e2b.container import EPS, INF, TOUCH, Container, Shape
from src.engines.e2b.spaces import Spaces
from src.model import ContainerType, Placement

BIG = 10**9
MAX_TRIES = 64  # candidates checked per space before it is given up

_Way = tuple[str, float, float, float]  # (orientation code, extent along x, along y, along z)


@dataclass(frozen=True)
class Config:
    """`nz_max`: most layers in a block (`None`: as many as tiers, load and height allow; 1: single
    layer). `measure`: what "largest block" means, `"volume"` or `"area"` (base area)."""

    nz_max: int | None = None
    measure: str = "volume"

    def __post_init__(self) -> None:
        if self.measure not in ("volume", "area"):
            raise ValueError(f"unknown measure {self.measure!r}")


DEFAULT_CONFIG = Config()


@dataclass
class PackStats:
    """What one or more `pack` calls did (`stats` argument): items per block in placement order, the
    spaces made, the most held at once, the spaces looked at, and the spaces given up at `MAX_TRIES`."""

    blocks: list[int] = field(default_factory=list)
    spaces_generated: int = 0
    spaces_peak: int = 0
    spaces_examined: int = 0
    tries_capped: int = 0


@lru_cache(maxsize=None)
def ways_of(L: float, W: float, H: float, allowed: tuple[str, ...], ctype: ContainerType) -> tuple[_Way, ...]:
    """The piece's way up from `base_orientation`, then the same turned 90° if that passes the door;
    empty if the piece fits `ctype` no way."""
    probe = Piece("", L, W, H, 0.0, False, 1, None, allowed)
    code = base_orientation(probe, ctype)
    if code is None:
        return ()
    a, b, c = probe.dims(code)
    ways = [(code, a, b, c)]
    if abs(a - b) > EPS and floor_ok(b, a, ctype):
        ways.append((rotated(code), b, a, c))
    return tuple(ways)


class _Packer:
    def __init__(self, items: list[Piece], ctype: ContainerType, delta: float, alpha: float, config: Config) -> None:
        self.ctype, self.delta, self.config = ctype, delta, config
        order: dict[tuple, int] = {}
        self.queues: list[list[Piece]] = []
        self.ways: list[tuple[_Way, ...]] = []
        for p in items:
            sig = (p.L, p.W, p.H, p.mass, p.allowed, p.tiers, p.load)
            if sig not in order:
                ways = ways_of(p.L, p.W, p.H, p.allowed, ctype)
                if not ways:
                    continue  # fits this container type no way
                order[sig] = len(self.queues)
                self.queues.append([])
                self.ways.append(ways)
            if sig in order:
                self.queues[order[sig]].append(p)
        if not self.queues:
            return  # nothing fits this container type
        self.used = [0] * len(self.queues)
        nt = len(self.queues)
        self.remaining = np.array([len(q) for q in self.queues], dtype=np.int64)
        self.mass = np.array([q[0].mass for q in self.queues])
        self.tiers = np.array([q[0].tiers for q in self.queues], dtype=np.int64)
        self.load = np.array([INF if q[0].load is None else q[0].load for q in self.queues])
        self.item_volume = np.array([q[0].L * q[0].W * q[0].H for q in self.queues])
        self.nz_load = np.full(nt, BIG, dtype=np.int64)
        limited = (self.mass > 0) & (self.load != INF)
        self.nz_load[limited] = np.minimum(BIG, np.floor((self.load[limited] + EPS) / self.mass[limited]) + 1).astype(np.int64)
        tw = [(t, w) for t in range(nt) for w in range(len(self.ways[t]))]
        self.tw_t = np.array([t for t, _ in tw], dtype=np.int64)
        self.tw_w = [w for _, w in tw]
        ext = np.array([self.ways[t][w][1:] for t, w in tw])
        self.A, self.B, self.C = ext[:, 0], ext[:, 1], ext[:, 2]
        self.PX, self.PY = self.A + delta, self.B + delta
        self.tw_mass = self.mass[self.tw_t]
        self.tw_vol = self.item_volume[self.tw_t]
        self.tw_area = self.A * self.B
        self.tw_tiers = self.tiers[self.tw_t]
        self.tw_nz_load = self.nz_load[self.tw_t]
        self.container = Container(delta, alpha)
        self.spaces = Spaces(
            ctype.L + delta, ctype.W + delta, ctype.H, float(self.PX.min()), float(self.PY.min()), float(self.C.min())
        )
        self.lightest = float(self.mass.min())
        self.stats = PackStats()

    # --- main loop -------------------------------------------------------------------------------

    def run(self) -> list[Placement]:
        placements: list[Placement] = []
        max_mass = self.ctype.max_mass
        while len(self.spaces) and self.remaining.sum() > 0:
            if self.container.mass + self.lightest > max_mass + EPS:
                break
            i = self.spaces.lowest()
            space = self.spaces.a[i].copy()
            self.stats.spaces_examined += 1
            found = self._select(space)
            if found is None:
                self.spaces.drop(i)
                continue
            tw, plan = found
            placements += self._commit(tw, plan)
            s = plan.shape
            self.spaces.cut((plan.x0, plan.y0, plan.z0, plan.x0 + s.nx * s.px, plan.y0 + s.ny * s.py, plan.z0 + s.nz * s.c))
        self.stats.spaces_generated = self.spaces.generated
        self.stats.spaces_peak = self.spaces.peak
        return placements

    def _commit(self, tw: int, plan) -> list[Placement]:
        s = plan.shape
        t, w = int(self.tw_t[tw]), self.tw_w[tw]
        n = s.nx * s.ny * s.nz
        pieces = self.queues[t][self.used[t]:self.used[t] + n]
        self.used[t] += n
        self.remaining[t] -= n
        self.container.commit(plan)
        self.stats.blocks.append(n)
        code = self.ways[t][w][0]
        out = []
        for layer in range(s.nz):
            for j in range(s.ny):
                for i in range(s.nx):
                    piece = pieces[(layer * s.ny + j) * s.nx + i]
                    out.append(Placement(
                        item=piece.item, k=0, x=plan.x0 + i * s.px, y=plan.y0 + j * s.py, z=plan.z0 + layer * s.c, o=code,
                    ))
        return out

    # --- choosing a block ------------------------------------------------------------------------

    def _bounds(self, space: np.ndarray) -> tuple[np.ndarray, ...]:
        """Per (type, way): most columns along x and y, most layers, most items, and the bound on the
        measure of any block; and which entries can hold a block at all."""
        sx, sy, sz = space[3] - space[0], space[4] - space[1], space[5] - space[2]
        nxm = np.floor((sx + EPS) / self.PX).astype(np.int64)
        nym = np.floor((sy + EPS) / self.PY).astype(np.int64)
        nzm = np.minimum(np.floor((sz + EPS) / self.C).astype(np.int64), np.minimum(self.tw_tiers, self.tw_nz_load))
        if self.config.nz_max is not None:
            nzm = np.minimum(nzm, self.config.nz_max)
        cap = self.remaining[self.tw_t]
        mass_left = self.ctype.max_mass - self.container.mass
        if mass_left != INF:
            heavy = self.tw_mass > 0
            by_mass = np.full(len(cap), BIG, dtype=np.int64)
            by_mass[heavy] = np.minimum(BIG, np.floor((mass_left + EPS) / self.tw_mass[heavy])).astype(np.int64)
            cap = np.minimum(cap, by_mass)
        feasible = (nxm >= 1) & (nym >= 1) & (nzm >= 1) & (cap >= 1)
        if self.config.measure == "volume":
            bound = np.minimum(cap, nxm * nym * nzm) * self.tw_vol
        else:
            bound = np.minimum(cap, nxm * nym) * self.tw_area
        return nxm, nym, nzm, cap, bound, feasible

    def _candidates(self, tw: int, nxm: int, nym: int, nzm: int, cap: int) -> list[tuple[tuple, int, int, int]]:
        """Concrete `(nx, ny, nz)` blocks of one (type, way), best first: for every `nz` and every `nx`
        the most columns along y the remaining count allows."""
        nz = np.arange(1, min(nzm, cap) + 1)
        cap_n = cap // nz
        nx = np.arange(1, nxm + 1)
        ny = np.minimum(nym, cap_n[:, None] // nx[None, :])
        ok = ny >= 1
        nz_g, nx_g = np.broadcast_arrays(nz[:, None], nx[None, :])
        nx_c, ny_c, nz_c = nx_g[ok], ny[ok], nz_g[ok]
        volume = nx_c * ny_c * nz_c * self.tw_vol[tw]
        area = nx_c * ny_c * self.tw_area[tw]
        measure = volume if self.config.measure == "volume" else area
        rank = np.lexsort((-nz_c, -nx_c, -area, -volume, -measure))
        return [
            ((float(measure[r]), float(volume[r]), float(area[r]), -tw, int(nx_c[r]), int(nz_c[r])), int(nx_c[r]), int(ny_c[r]), int(nz_c[r]))
            for r in rank
        ]

    def _select(self, space: np.ndarray):
        z = float(space[2])
        near = []
        if z > TOUCH:
            near = self.container.near(z, float(space[0]), float(space[3]), float(space[1]), float(space[4]))
            if not near:
                return None  # nothing at this height to stand on
        nxm, nym, nzm, cap, bound, feasible = self._bounds(space)
        idx = np.flatnonzero(feasible)
        if not len(idx):
            return None
        order = idx[np.argsort(-bound[idx], kind="stable")]
        best_key = None
        best = None
        tries = 0
        for tw in order:
            tw = int(tw)
            if best_key is not None and bound[tw] < best_key[0] - 1e-9:
                break
            for key, nx, ny, nz in self._candidates(tw, int(nxm[tw]), int(nym[tw]), int(nzm[tw]), int(cap[tw])):
                if best_key is not None and key <= best_key:
                    break
                if tries >= MAX_TRIES:
                    self.stats.tries_capped += 1
                    return best
                tries += 1
                plan = self._place(space, near, tw, nx, ny, nz)
                if plan is not None:
                    best_key, best = key, (tw, plan)
                    break
        return best

    def _place(self, space: np.ndarray, near: list[int], tw: int, nx: int, ny: int, nz: int):
        t = int(self.tw_t[tw])
        shape = Shape(
            nx=nx, ny=ny, nz=nz, a=float(self.A[tw]), b=float(self.B[tw]), c=float(self.C[tw]),
            px=float(self.PX[tw]), py=float(self.PY[tw]), mass=float(self.mass[t]), tiers=int(self.tiers[t]),
            load=float(self.load[t]),
        )
        z = float(space[2])
        xs = [float(space[0])]
        ys = [float(space[1])]
        if z > TOUCH:
            xf, yf = float(space[3]) - nx * shape.px, float(space[4]) - ny * shape.py
            if xf > xs[0] + EPS:
                xs.append(xf)
            if yf > ys[0] + EPS:
                ys.append(yf)
        for y0 in ys:
            for x0 in xs:
                plan = self.container.try_place(shape, x0, y0, z, near)
                if plan is not None:
                    return plan
        return None


def pack(
    items: list[Piece],
    ctype: ContainerType,
    delta: float,
    alpha: float,
    config: Config = DEFAULT_CONFIG,
    stats: PackStats | None = None,
) -> list[Placement]:
    """Placements (k = 0) for as many of `items` as this core fits into one empty `ctype`. Items with
    no orientation fitting `ctype` at all are left out. `stats`, when given, accumulates run figures."""
    packer = _Packer(items, ctype, delta, alpha, config)
    if not packer.queues:
        return []
    placements = packer.run()
    if stats is not None:
        s = packer.stats
        stats.blocks += s.blocks
        stats.spaces_generated += s.spaces_generated
        stats.spaces_peak = max(stats.spaces_peak, s.spaces_peak)
        stats.spaces_examined += s.spaces_examined
        stats.tries_capped += s.tries_capped
    return placements
