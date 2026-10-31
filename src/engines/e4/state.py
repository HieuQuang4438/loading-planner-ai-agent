"""E4's solution state: a list of containers, each a type and
an item set with the layout the core gave that set (option 1A), and the lexicographic
objective -- cost first, then the free space of the
emptiest container.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from src.engines.base import Hints, Piece
from src.model import ContainerType, Instance, Params, Placement, Solution, UsedContainer

EPS = 1e-9
# Weight of the tie-break in the scalar objective simulated annealing compares: below the smallest
# cost step of the cost table (0.05, 40DC 1.00 vs 40HC 1.05), times a fill in [0, 1].
SECONDARY_WEIGHT = 0.01


@dataclass(eq=False)
class Box:
    """One used container. `placements` is empty while `dirty` (items changed, not yet re-packed)."""

    type: ContainerType
    items: frozenset[str]
    placements: tuple[Placement, ...]
    volume: float
    mass: float
    hints: Hints | None = None
    dirty: bool = False
    touched: bool = field(default=False, compare=False)  # changed by the current iteration's repair

    @property
    def fill(self) -> float:
        """Share of the tighter resource in use: volume or mass ("thể tích và tải
        còn lại")."""
        return max(self.volume / self.type.volume, self.mass / self.type.max_mass)

    def copy(self) -> Box:
        return replace(self, touched=False)


def make_box(ctype: ContainerType, placements: list[Placement], pieces: dict[str, Piece], hints: Hints | None) -> Box:
    items = frozenset(p.item for p in placements)
    return Box(
        type=ctype,
        items=items,
        placements=tuple(placements),
        volume=sum(pieces[i].L * pieces[i].W * pieces[i].H for i in items),
        mass=sum(pieces[i].mass for i in items),
        hints=hints,
    )


def cost(boxes: list[Box]) -> float:
    return round(sum(b.type.cost for b in boxes), 9)


def key(boxes: list[Box]) -> tuple[float, float]:
    """Lexicographic objective, lower is better: cost, then the fill of the emptiest container."""
    return cost(boxes), min((b.fill for b in boxes), default=0.0)


def scalar(boxes: list[Box]) -> float:
    c, fill = key(boxes)
    return c + SECONDARY_WEIGHT * fill


def signature(boxes: list[Box]) -> int:
    """Hash of the solution as (type, item set) pairs: Ropke-Pisinger score an accepted solution only
    the first time it is visited."""
    return hash(frozenset((b.type.id, b.items) for b in boxes))


def from_solution(instance: Instance, solution: Solution, pieces: dict[str, Piece]) -> list[Box]:
    by_k: dict[int, list[Placement]] = {c.k: [] for c in solution.containers}
    for p in solution.placements:
        by_k[p.k].append(p)
    boxes = []
    for c in solution.containers:
        ctype = instance.container_type(c.type)
        assert ctype is not None
        boxes.append(make_box(ctype, by_k[c.k], pieces, None))
    return boxes


def to_solution(instance: Instance, params: Params, boxes: list[Box]) -> Solution:
    containers, placements = [], []
    for k, box in enumerate(boxes, start=1):
        containers.append(UsedContainer(k=k, type=box.type.id))
        placements += [replace(p, k=k) for p in box.placements]
    return Solution(instance=instance.name, params=params, containers=containers, placements=placements)
