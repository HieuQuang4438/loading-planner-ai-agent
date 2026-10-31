"""E1's packing core for one container: build columns,
then lay their footprints on the floor with maxrects.

Floor step: each column's footprint is widened by `delta` along x and y, and so is the floor, so any
two columns laid without overlap are at least `delta` apart while no gap is forced against a wall
(constraint 5). Columns go in by volume, largest first; one that
would push the container past `max_mass` (constraint 6), or that fits nowhere, is skipped and the
next one tried. A column may be turned 90° only if its footprint still passes the door that way
(constraint 9) -- every piece in it is no wider than its bottom piece, so the bottom one decides.
Pieces in a column share the column's (x, y) corner, each inside the top face of the one below.

**Hints** (`src.engines.base.Hints`): the floor step is what no fixed rule gets
right, so that is what hints steer; column building is untouched. A column takes the hints of its
bottom piece's line. With `order`, columns are laid by that key first, volume second. With `turn`,
a column whose line has a turn hint tries only its preferred way (if the door allows it) and falls
back to the other way only when the preferred one fits nowhere. Without hints: exactly the rules
above.
"""
from __future__ import annotations

from src.engines.base import Hints, Piece
from src.engines.e1.columns import Column, build_columns
from src.engines.e1.maxrects import MaxRects
from src.engines.e1.orientation import base_orientation, dense_orientation, floor_ok, rotated, tilt_first_orientation
from src.model import ContainerType, Placement, line_of

EPS = 1e-9


def pack(
    items: list[Piece],
    ctype: ContainerType,
    delta: float,
    hints: Hints | None = None,
    tilt_first: bool = False,
    dense: bool = False,
) -> list[Placement]:
    """Placements (k = 0) for as many of `items` as this core fits into one empty `ctype`. Items
    with no orientation fitting `ctype` at all are left out. `tilt_first` swaps the orientation rule
    for `tilt_first_orientation` (probe); `dense` picks, among the piece's allowed
    orientations, the one with the most pieces per m² of floor (`dense_orientation`)."""
    if dense:
        def orient(piece: Piece, ctype: ContainerType) -> str | None:
            return dense_orientation(piece, ctype, delta)
    else:
        orient = tilt_first_orientation if tilt_first else base_orientation
    entries = []
    for piece in items:
        code = orient(piece, ctype)
        if code is not None:
            entries.append((piece, code))
    columns = build_columns(entries, ctype)
    return lay_floor(columns, ctype, delta, hints)


def lay_floor(columns: list[Column], ctype: ContainerType, delta: float, hints: Hints | None = None) -> list[Placement]:
    if hints is not None and hints.order:
        columns = sorted(columns, key=lambda c: hints.order_key(_line(c)))  # stable: volume order breaks ties
    floor = MaxRects(ctype.L + delta, ctype.W + delta)
    placements: list[Placement] = []
    mass = 0.0
    lightest = min((c.mass for c in columns), default=0.0)
    for column in columns:
        if not floor.free or mass + lightest > ctype.max_mass + EPS:
            break
        if mass + column.mass > ctype.max_mass + EPS:
            continue
        spot = _insert(floor, column, ctype, delta, hints)
        if spot is None:
            continue
        x, y, turned = spot
        mass += column.mass
        for piece, code, z in column.stack:
            placements.append(Placement(item=piece.item, k=0, x=x, y=y, z=z, o=rotated(code) if turned else code))
    return placements


def _line(column: Column) -> str:
    return line_of(column.stack[0][0].item)


def _insert(floor: MaxRects, column: Column, ctype: ContainerType, delta: float, hints: Hints | None) -> tuple[float, float, bool] | None:
    plain, turned = floor_ok(column.fx, column.fy, ctype), floor_ok(column.fy, column.fx, ctype)
    w, h = column.fx + delta, column.fy + delta
    if hints is None or not hints.turn or not (plain and turned):
        return floor.insert(w, h, plain=plain, turned=turned)
    prefer_turned = hints.turned(_line(column))
    spot = floor.insert(w, h, plain=not prefer_turned, turned=prefer_turned)
    if spot is None:
        spot = floor.insert(w, h, plain=prefer_turned, turned=not prefer_turned)
    return spot
