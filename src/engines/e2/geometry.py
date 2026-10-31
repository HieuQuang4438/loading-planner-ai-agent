"""E2's group-G packer: one call of the same core (`src.engines.e2.pack.pack`) per thpack problem, into a single
container, delta = 0, no mass limit, no load or tier limit, support share `G_ALPHA`. The core places
pieces until none fits, which is its own way of filling one container.

Group G has no support rule (its checker, `src.bench.geometry_checker`, does not look at it); E2
still keeps `G_ALPHA` so boxes do not float, the value of the main runs. Each box type stands on one fixed dim, E0's and E1's rule (`src.engines.e1.geometry.height_dim`),
so the G comparison changes only the core.
"""
from __future__ import annotations

from src.bench.geometry_checker import GPlacement
from src.bench.thpack import ThpackProblem
from src.engines.base import Piece
from src.engines.e1.geometry import NO_TIER_LIMIT, height_dim
from src.engines.e2.pack import pack
from src.model import ContainerType

G_ALPHA = 0.8


def solve_geometry(problem: ThpackProblem, _resource: object = None) -> list[GPlacement]:
    """`_resource` is the per-worker slot `src.run cmd_geometry` hands every group-G solver (E0's
    JVM bridge); E2 needs none."""
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
    for p in pack(pieces, ctype, delta=0.0, alpha=G_ALPHA):
        dx, dy, dz = by_item[p.item].dims(p.o)
        placements.append(GPlacement(type=box_type[p.item], x=p.x, y=p.y, z=p.z, dx=dx, dy=dy, dz=dz))
    return placements
