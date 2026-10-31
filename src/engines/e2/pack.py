"""E2's packing core for one container: extreme
points, the lowest one first, exact incremental checks of constraints 5, 7 and 8.

Pieces go in one at a time in E1's order: base area, largest first, then mass, heaviest first, then
input order. Each piece keeps E1's way up (`src.engines.e1.orientation.base_orientation`: upright
unless forced) and is tried turned both ways about the vertical axis, a way counting only if its
extent across the container still passes the door (constraint 9). Among all (point, turn) pairs
whose residual space holds the piece, the smallest z wins, then x, then y, then the preferred way;
the first of that order that passes the exact checks is taken. A piece with none, or one that would
push the container past `max_mass` (constraint 6), is skipped and the next tried.

**Two passes**: the container is packed once
preferring the unturned way and once preferring the turned way; the pass carrying more volume is
kept, then the one with more pieces, then the unturned pass. Still one deterministic result.

**Orient mode** (`orient=True`, engine `e2-orient`): `_ways` returns, besides the way above,
every other allowed orientation that clears the door and the interior, each also turned 90°, base way
first. The same placement order then chooses among them, so a piece is tipped only where that gets it
placed lower, nearer the wall or when the base way fits nowhere sooner. Off: exactly the ways above.

Speed: pieces equal in every field and way up behave the same, so once one fails, the next equal
one is skipped until something is placed. Exact checks run on candidates in batches, collision and
support vectorized with numpy over every placed box; only candidates passing both reach the load
and tier check.

**Hints** (`src.engines.base.Hints`). With `order`, pieces go in by their line's key
first, then in E1's order. With `turn`, the container is packed in **one** pass, each piece
preferring the way its line's hint names when two ways tie at the same point (the per-piece version
of the pass-wide preference above). Without hints: exactly the two passes above.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from src.engines.base import Hints, Piece
from src.engines.e1.orientation import _TILTED, base_orientation, floor_ok, rotated
from src.engines.e2.layout import EPS, Layout, Stacking
from src.engines.e2.points import ExtremePoints
from src.model import ContainerType, Placement, line_of

FIRST_BATCH = 32  # candidates checked in the first batch; each further batch is 4 times larger

_Way = tuple[str, float, float, float]  # (orientation code, extent along x, along y, along z)


def pack(
    items: list[Piece],
    ctype: ContainerType,
    delta: float,
    alpha: float,
    hints: Hints | None = None,
    orient: bool = False,
) -> list[Placement]:
    """Placements (k = 0) for as many of `items` as this core fits into one empty `ctype`: the
    better of the unturned-first and the turned-first pass (`_better`). Items with no orientation
    fitting `ctype` at all are left out. `orient` lets a piece take any allowed orientation."""
    entries: list[tuple[Piece, tuple[_Way, ...]]] = []
    for piece in items:
        ways = _ways(piece.L, piece.W, piece.H, piece.allowed, ctype, orient)
        if ways:
            entries.append((piece, ways))
    if not entries:
        return []
    if hints is not None and (hints.order or hints.turn):
        return _hinted(entries, ctype, delta, alpha, hints)
    unturned = _pass(entries, ctype, delta, alpha, turned_first=False)
    turned = _pass(entries, ctype, delta, alpha, turned_first=True)
    return turned if _better(turned, unturned, entries) else unturned


def _hinted(
    entries: list[tuple[Piece, tuple[_Way, ...]]], ctype: ContainerType, delta: float, alpha: float, hints: Hints
) -> list[Placement]:
    lines = [line_of(piece.item) for piece, _ in entries]
    order_key = [hints.order_key(line) for line in lines] if hints.order else None
    if not hints.turn:
        unturned = _pass(entries, ctype, delta, alpha, turned_first=False, order_key=order_key)
        turned = _pass(entries, ctype, delta, alpha, turned_first=True, order_key=order_key)
        return turned if _better(turned, unturned, entries) else unturned
    per_piece = [hints.turned(line) for line in lines]
    return _pass(entries, ctype, delta, alpha, turned_first=per_piece, order_key=order_key)


def _better(a: list[Placement], b: list[Placement], entries: list[tuple[Piece, tuple[_Way, ...]]]) -> bool:
    """Whether pass `a` beats pass `b`: more volume placed, then more pieces."""
    volume = {piece.item: piece.L * piece.W * piece.H for piece, _ in entries}
    va, vb = sum(volume[p.item] for p in a), sum(volume[p.item] for p in b)
    if abs(va - vb) > EPS:
        return va > vb
    return len(a) > len(b)


def _pass(
    entries: list[tuple[Piece, tuple[_Way, ...]]],
    ctype: ContainerType,
    delta: float,
    alpha: float,
    turned_first: bool | list[bool],
    order_key: list[float] | None = None,
) -> list[Placement]:
    """One greedy pass over `entries` in E1's order (after `order_key`, when given), ties between the
    two ways going to the turned one when `turned_first` (one flag for all, or one per entry)."""
    order = sorted(
        range(len(entries)), key=lambda i: (-entries[i][1][0][1] * entries[i][1][0][2], -entries[i][0].mass, i)
    )
    if order_key is not None:
        order.sort(key=lambda i: order_key[i])  # stable: E1's order breaks ties
    shapes = {ways for _, ways in entries}
    min_side = min(min(w[1], w[2]) for ways in shapes for w in ways)
    min_height = min(w[3] for ways in shapes for w in ways)
    lightest = min(p.mass for p, _ in entries)

    layout = Layout(len(entries), delta)
    points = ExtremePoints(ctype, min_side, min_height)
    failed_at: dict[tuple, int] = {}  # piece signature -> layout.n when it last failed
    for i in order:
        if layout.mass + lightest > ctype.max_mass + EPS or not len(points):
            break
        piece, ways = entries[i]
        if layout.mass + piece.mass > ctype.max_mass + EPS:
            continue
        signature = (piece.L, piece.W, piece.H, piece.mass, piece.tiers, piece.load, ways)
        if failed_at.get(signature) == layout.n:
            continue
        prefer = turned_first[i] if isinstance(turned_first, list) else turned_first
        spot = _best_spot(layout, points, piece, ways, alpha, prefer)
        if spot is None:
            failed_at[signature] = layout.n
            continue
        p, way, stacking = spot
        k = layout.add(piece, way[0], float(points.x[p]), float(points.y[p]), float(points.z[p]), way[1:], stacking)
        points.after_place(layout, k)
    return [
        Placement(item=layout.pieces[k].item, k=0, x=float(layout.x0[k]), y=float(layout.y0[k]), z=float(layout.z0[k]), o=layout.codes[k])
        for k in range(layout.n)
    ]


@lru_cache(maxsize=None)
def _ways(
    L: float, W: float, H: float, allowed: tuple[str, ...], ctype: ContainerType, every: bool = False
) -> tuple[_Way, ...]:
    """The piece's way up from `base_orientation`, then the same turned 90° if that passes the door;
    empty if the piece fits `ctype` no way. With `every`, then the other allowed orientations too
    (upright, then tipped by lowest height), each followed by its turn, all clearing door and interior."""
    probe = Piece("", L, W, H, 0.0, False, 1, None, allowed)
    code = base_orientation(probe, ctype)
    if code is None:
        return ()
    a, b, c = probe.dims(code)
    ways = [(code, a, b, c)]
    if abs(a - b) > EPS and floor_ok(b, a, ctype):
        ways.append((rotated(code), b, a, c))
    if every:
        size = {"L": L, "W": W, "H": H}
        families = [("LWH", "WLH")] + sorted((_TILTED[d] for d in ("W", "L")), key=lambda pair: size[pair[0][2]])
        seen = {w[0] for w in ways}
        for first, second in families:
            for o in (first, second):
                if o in seen or o not in allowed:
                    continue
                seen.add(o)
                a, b, c = probe.dims(o)
                if c <= min(ctype.H, ctype.door_h) + EPS and a <= ctype.L + EPS and b <= min(ctype.W, ctype.door_w) + EPS:
                    ways.append((o, a, b, c))
    return tuple(ways)


def _best_spot(
    layout: Layout,
    points: ExtremePoints,
    piece: Piece,
    ways: tuple[_Way, ...] | list[_Way],
    alpha: float,
    turned_first: bool = False,
) -> tuple[int, _Way, Stacking] | None:
    """(point index, way, stacking) of the first feasible (point, way) pair by smallest z, x, y, then
    the preferred way (unturned, or turned when `turned_first`), or `None`."""
    idx_parts, way_parts = [], []
    for w, (_, a, b, c) in enumerate(ways):
        fits = (a <= points.rx + EPS) & (b <= points.ry + EPS) & (c <= points.rz + EPS)
        idx = np.flatnonzero(fits)
        idx_parts.append(idx)
        way_parts.append(np.full(len(idx), w))
    idx = np.concatenate(idx_parts)
    if not len(idx):
        return None
    way_of = np.concatenate(way_parts)
    preference = -way_of if turned_first else way_of
    rank = np.lexsort((preference, points.y[idx], points.x[idx], points.z[idx]))
    idx, way_of = idx[rank], way_of[rank]

    extents = np.array([[a, b, c] for _, a, b, c in ways])
    start, size = 0, FIRST_BATCH
    while start < len(idx):
        p, w = idx[start:start + size], way_of[start:start + size]
        xs, ys, zs = points.x[p], points.y[p], points.z[p]
        a, b, c = extents[w, 0], extents[w, 1], extents[w, 2]
        ok = layout.collision_free(xs, ys, zs, a, b, c)
        if ok.any():
            ok[ok] = layout.supported(xs[ok], ys[ok], zs[ok], a[ok], b[ok], alpha, piece.mass)
        for j in np.flatnonzero(ok):
            stacking = layout.stacking(float(xs[j]), float(ys[j]), float(zs[j]), float(a[j]), float(b[j]), float(c[j]), piece)
            if stacking is not None:
                return int(p[j]), ways[int(w[j])], stacking
        start += size
        size *= 4
    return None
