"""E1's group-G packer:
one call of the same core (`src.engines.e1.pack.pack`) per thpack problem, into a single container,
delta = 0, no mass limit, no load or tier limit -- columns by volume, largest first, until nothing
more fits, which is the core's own way of filling one container.

**Orientation flags.** thpack says, per box dim, whether it may stand vertical; `Piece` only knows
"upright" (listed `H` vertical) or "tippable" (any dim vertical), so the flags do not map onto it
directly. Each box type is instead fixed to one vertical dim -- the largest one its flags allow,
the same rule as E0 (`src.engines.e0.geometry.fixed_height_dim`) so the G comparison changes only the
core -- and becomes an untippable piece standing on the other two, still free to turn 90° about the
vertical axis. The group-G checker (`src.bench.geometry_checker`) would accept any allowed height.
"""
from __future__ import annotations

from src.bench.geometry_checker import GPlacement
from src.bench.thpack import ThpackBox, ThpackProblem
from src.engines.base import Piece
from src.engines.e1.pack import pack
from src.model import ContainerType

NO_TIER_LIMIT = 10**9


def height_dim(box: ThpackBox) -> int:
    """Index into `box.dims` standing vertical: the largest dim `box.vertical_ok` allows."""
    return max((i for i in range(3) if box.vertical_ok[i]), key=lambda i: box.dims[i])


def solve_geometry(problem: ThpackProblem, _resource: object = None) -> list[GPlacement]:
    """`_resource` is the per-worker slot `src.run cmd_geometry` hands every group-G solver (E0's
    JVM bridge); E1 needs none."""
    length, width, height = problem.container
    ctype = ContainerType(
        id="G", L=length, W=width, H=height, door_w=width, door_h=height, max_mass=float("inf"), cost=1.0
    )
    pieces: list[Piece] = []
    box_type: dict[str, int] = {}
    for box in problem.boxes:
        h = height_dim(box)
        d1, d2 = (box.dims[i] for i in range(3) if i != h)
        for n in range(box.qty):
            item = f"{box.type}#{n + 1}"
            pieces.append(Piece(item, d1, d2, box.dims[h], 0.0, False, NO_TIER_LIMIT, None))
            box_type[item] = box.type
    by_item = {p.item: p for p in pieces}
    placements = []
    for p in pack(pieces, ctype, delta=0.0):
        dx, dy, dz = by_item[p.item].dims(p.o)
        placements.append(GPlacement(type=box_type[p.item], x=p.x, y=p.y, z=p.z, dx=dx, dy=dy, dz=dz))
    return placements
