"""Which way up a piece goes in one container type.

Upright unless forced: a piece keeps its listed height `H` whenever some upright orientation clears
the interior and the door of `ctype` (constraints 4, 9). Only when none does -- and the piece is
allowed to be tipped (`Piece.allowed`) -- is it tipped over, onto whichever of its other two dims gives
the lowest feasible height. Only codes in `Piece.allowed` are ever returned (an allowed set always
holds both codes of a 90° turn, so a turned column stays allowed).

A "base" is an orientation code seen from the column's own frame; turning the whole column 90° about
the vertical axis swaps the first two letters of every code in it (`rotated`), since those name the
dims along x and y and the third (vertical) one stays put.
"""
from __future__ import annotations

import math
from functools import lru_cache

from src.engines.base import Piece
from src.model import ContainerType

EPS = 1e-9

# Tilted orientation codes grouped by the dim that stands vertical, in (unrotated, rotated) pairs.
_TILTED = {"W": ("LHW", "HLW"), "L": ("WHL", "HWL")}


def rotated(code: str) -> str:
    return code[1] + code[0] + code[2]


def floor_ok(fx: float, fy: float, ctype: ContainerType) -> bool:
    """Whether a footprint with extents (fx, fy) along (x, y) fits the floor and passes the door."""
    return fx <= ctype.L + EPS and fy <= min(ctype.W, ctype.door_w) + EPS


def base_orientation(piece: Piece, ctype: ContainerType) -> str | None:
    """The code this piece is stacked in, from the column frame; `None` if it fits `ctype` no way."""
    return _base_orientation(piece.L, piece.W, piece.H, piece.allowed, ctype)


@lru_cache(maxsize=None)
def _base_orientation(L: float, W: float, H: float, allowed: tuple[str, ...], ctype: ContainerType) -> str | None:
    size = {"L": L, "W": W, "H": H}
    families = [("LWH", "WLH")]
    # Lowest standing height first; a stable sort keeps "W" before "L" on a tie.
    families += sorted((_TILTED[d] for d in ("W", "L")), key=lambda pair: size[pair[0][2]])
    for code, turned in families:
        if code not in allowed:
            continue
        if size[code[2]] > min(ctype.H, ctype.door_h) + EPS:
            continue
        fx, fy = size[code[0]], size[code[1]]
        if floor_ok(fx, fy, ctype):
            return code
        if floor_ok(fy, fx, ctype):
            return turned
    return None


def tilt_first_orientation(piece: Piece, ctype: ContainerType) -> str | None:
    """As `base_orientation`, but a piece allowed to tip is tipped onto its lowest standing height first
    whenever that is below `H` and fits."""
    return _tilt_first(piece.L, piece.W, piece.H, piece.allowed, ctype)


@lru_cache(maxsize=None)
def _tilt_first(L: float, W: float, H: float, allowed: tuple[str, ...], ctype: ContainerType) -> str | None:
    size = {"L": L, "W": W, "H": H}
    for d in sorted(("W", "L"), key=lambda d: size[d]):
        if size[d] >= H - EPS:
            break
        code, turned = _TILTED[d]
        if code not in allowed or size[d] > min(ctype.H, ctype.door_h) + EPS:
            continue
        fx, fy = size[code[0]], size[code[1]]
        if floor_ok(fx, fy, ctype):
            return code
        if floor_ok(fy, fx, ctype):
            return turned
    return _base_orientation(L, W, H, allowed, ctype)


def dense_orientation(piece: Piece, ctype: ContainerType, delta: float) -> str | None:
    """The allowed orientation (turned if the door needs it) that packs the most pieces per m² of
    floor in `ctype` (E1's "dense" rule): a stack of `n = min(tiers, usable height // h,
    pieces the load lets stack)` over the footprint widened by `delta`. Ties go to the upright
    orientation, then to `base_orientation`'s order; `None` if the piece fits `ctype` no way."""
    return _dense(piece.L, piece.W, piece.H, piece.mass, piece.tiers, piece.load, piece.allowed, ctype, delta)


@lru_cache(maxsize=None)
def _dense(
    L: float, W: float, H: float, mass: float, tiers: int, load: float | None, allowed: tuple[str, ...],
    ctype: ContainerType, delta: float,
) -> str | None:
    size = {"L": L, "W": W, "H": H}
    if load is None:
        n_load = None
    elif load <= EPS or mass <= EPS:
        n_load = 1 if load <= EPS else None
    else:
        n_load = 1 + math.floor((load + EPS) / mass)
    families = [("LWH", "WLH")] + sorted((_TILTED[d] for d in ("W", "L")), key=lambda pair: size[pair[0][2]])
    best: tuple[float, str] | None = None
    for code, turned in families:
        if code not in allowed:
            continue
        h = size[code[2]]
        if h > min(ctype.H, ctype.door_h) + EPS:
            continue
        fx, fy = size[code[0]], size[code[1]]
        if floor_ok(fx, fy, ctype):
            chosen = code
        elif floor_ok(fy, fx, ctype):
            chosen = turned
        else:
            continue
        n = min(tiers, math.floor((ctype.H + EPS) / h))
        if n_load is not None:
            n = min(n, n_load)
        density = n / ((fx + delta) * (fy + delta))
        if best is None or density > best[0] * (1 + 1e-9):
            best = (density, chosen)
    return None if best is None else best[1]
