"""Step 1 of E1's core, column building.

Pieces are taken by base area, largest first, then by mass, heaviest first. Each goes on top of an
existing column when its base fits inside the top piece's top face (turned 90° if need be), the
column stays within `ctype.H`, every piece already in the column still has load to spare for it, the
column's piece count stays within the smallest `tiers` in it, and the column's mass stays within
`ctype.max_mass` (a heavier column could never go into this type at all). Among several such columns
the one with the smallest top face wins, then the tallest; with none, the piece starts a new column.

A piece resting wholly inside the top face of the one below is 100% supported (constraint 7), and
with no piece spanning two columns, constraint 8 reduces to the one-dimensional check here.

Speed: columns are bucketed by their stacking state (top face, height, spare load, count, tier cap,
mass) -- identical items build identical columns, so a lot of thousands of pieces usually has only a
few dozen distinct states -- and a column that no piece of the lot could ever go on is set aside.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.engines.base import Piece
from src.engines.e1.orientation import rotated
from src.model import ContainerType

EPS = 1e-9
INF = float("inf")

# (top x, top y, height, spare load, count, tier cap, mass): everything the stacking rule looks at.
_State = tuple[float, float, float, float, int, int, float]


@dataclass
class Column:
    order: int  # creation index: the deterministic tie-break when sorting columns
    fx: float  # footprint along x in the column frame (the bottom piece's extents)
    fy: float
    stack: list[tuple[Piece, str, float]] = field(default_factory=list)  # (piece, code, z), bottom first
    height: float = 0.0
    mass: float = 0.0
    volume: float = 0.0


def build_columns(entries: list[tuple[Piece, str]], ctype: ContainerType) -> list[Column]:
    """Columns built from `entries` (each piece with its column-frame base code, from
    `src.engines.e1.orientation.base_orientation`), sorted by volume, largest first."""
    if not entries:
        return []
    dims = [p.dims(code) for p, code in entries]
    order = sorted(range(len(entries)), key=lambda i: (-dims[i][0] * dims[i][1], -entries[i][0].mass, i))
    min_mass = min(p.mass for p, _ in entries)
    min_h = min(d[2] for d in dims)

    open_: dict[_State, list[Column]] = {}
    closed: list[Column] = []
    n_columns = 0
    for i in order:
        piece, code = entries[i]
        a, b, h = dims[i]
        key = _best_column(open_, a, b, h, piece, ctype)
        if key is None:
            column = Column(order=n_columns, fx=a, fy=b)
            n_columns += 1
            spare, count, cap = INF, 0, piece.tiers
        else:
            bucket = open_[key]
            column = bucket.pop()
            if not bucket:
                del open_[key]
            tx, ty, _, spare, count, cap, _ = key
            if not (a <= tx + EPS and b <= ty + EPS):
                code, a, b = rotated(code), b, a
        column.stack.append((piece, code, column.height))
        column.height += h
        column.mass += piece.mass
        column.volume += a * b * h
        spare = min(spare - piece.mass, INF if piece.load is None else piece.load)
        count, cap = count + 1, min(cap, piece.tiers)
        state = (a, b, column.height, spare, count, cap, column.mass)
        if _closed(state, ctype, min_mass, min_h):
            closed.append(column)
        else:
            open_.setdefault(state, []).append(column)

    columns = closed + [c for bucket in open_.values() for c in bucket]
    columns.sort(key=lambda c: (-c.volume, c.order))
    return columns


def _best_column(
    open_: dict[_State, list[Column]], a: float, b: float, h: float, piece: Piece, ctype: ContainerType
) -> _State | None:
    best: _State | None = None
    best_rank = (INF, INF)
    for key in open_:
        tx, ty, height, spare, count, cap, mass = key
        if height + h > ctype.H + EPS or spare < piece.mass - EPS or mass + piece.mass > ctype.max_mass + EPS:
            continue
        if count + 1 > min(cap, piece.tiers):
            continue
        if not ((a <= tx + EPS and b <= ty + EPS) or (b <= tx + EPS and a <= ty + EPS)):
            continue
        rank = (tx * ty, -height)
        if rank < best_rank:
            best, best_rank = key, rank
    return best


def _closed(state: _State, ctype: ContainerType, min_mass: float, min_h: float) -> bool:
    """No piece of this lot could ever go on top of a column in this state."""
    _, _, height, spare, count, cap, mass = state
    return (
        count >= cap
        or spare < min_mass - EPS
        or height + min_h > ctype.H + EPS
        or mass + min_mass > ctype.max_mass + EPS
    )
