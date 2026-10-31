"""Problem data: instances, model parameters and solutions.

Units: metres, kg, relative freight cost. Axes: x along the container length from the far wall
to the door, y across, z up. A placement's (x, y, z) is its minimum corner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# An orientation code names which item dimension lies along x, y and z, in that order.
# "LWH" is the item as listed; "WLH" is the same item turned 90° about the vertical axis.
UPRIGHT_ORIENTATIONS: tuple[str, ...] = ("LWH", "WLH")
ALL_ORIENTATIONS: tuple[str, ...] = ("LWH", "WLH", "LHW", "HLW", "WHL", "HWL")


def is_tipped(code: str) -> bool:
    """Whether an orientation code lies the item on its side or end (its listed `H` is not vertical)."""
    return code[2] != "H"


def turned(code: str) -> str:
    """The code after a 90° turn about the vertical axis."""
    return code[1] + code[0] + code[2]


def allowed_orientations(tippable: bool, orientations: tuple[str, ...] | None) -> tuple[str, ...]:
    """The orientations a line may use: its explicit set, else all six if tippable, else the upright two."""
    if orientations is not None:
        return orientations
    return ALL_ORIENTATIONS if tippable else UPRIGHT_ORIENTATIONS


@dataclass(frozen=True)
class ContainerType:
    id: str
    L: float
    W: float
    H: float
    door_w: float
    door_h: float
    max_mass: float
    cost: float

    @property
    def volume(self) -> float:
        return self.L * self.W * self.H


@dataclass(frozen=True)
class ItemLine:
    """A line of `qty` identical items."""

    id: str
    qty: int
    L: float
    W: float
    H: float
    mass: float
    tippable: bool
    tiers: int
    load: float | None  # None: unlimited; 0: nothing may rest on it
    # Explicit allowed orientation codes (JSON key `orientations`); `None` means the default derived
    # from `tippable`. Stored in `ALL_ORIENTATIONS` order, and `None` again when equal to the default.
    orientations: tuple[str, ...] | None = None
    # JSON `"tiers": null` (no stack-height limit through this item). `tiers` then holds an effective cap
    # no stack can reach (the lot's piece count), so engines and the checker read a plain int; writers and
    # views give `null` back. See `src.formats.line_from_dict`.
    tiers_unlimited: bool = False

    def __post_init__(self) -> None:
        if self.orientations is None:
            return
        codes = tuple(self.orientations)
        if not codes:
            raise ValueError(f"item line {self.id}: orientations must not be empty")
        unknown = [c for c in codes if c not in ALL_ORIENTATIONS]
        if unknown:
            raise ValueError(f"item line {self.id}: unknown orientation code(s) {unknown}")
        chosen = set(codes)
        if not self.tippable and not chosen <= set(UPRIGHT_ORIENTATIONS):
            raise ValueError(f"item line {self.id}: tippable is false but orientations has a tipped code")
        if any(turned(c) not in chosen for c in chosen):
            raise ValueError(f"item line {self.id}: orientations must hold both codes of each 90° turn (LWH+WLH, LHW+HLW, WHL+HWL)")
        ordered = tuple(c for c in ALL_ORIENTATIONS if c in chosen)
        default = ALL_ORIENTATIONS if self.tippable else UPRIGHT_ORIENTATIONS
        object.__setattr__(self, "orientations", None if ordered == default else ordered)

    @property
    def volume(self) -> float:
        return self.L * self.W * self.H

    @property
    def allowed(self) -> tuple[str, ...]:
        return allowed_orientations(self.tippable, self.orientations)

    def dims(self, orientation: str) -> tuple[float, float, float]:
        """Extents (l', w', h') along x, y, z in the given orientation."""
        size = {"L": self.L, "W": self.W, "H": self.H}
        return size[orientation[0]], size[orientation[1]], size[orientation[2]]

    def item_ids(self) -> list[str]:
        return [item_id(self.id, n) for n in range(1, self.qty + 1)]


@dataclass(frozen=True)
class Instance:
    name: str
    container_types: tuple[ContainerType, ...]
    items: tuple[ItemLine, ...]
    meta: dict[str, Any] = field(default_factory=dict, compare=False)

    def container_type(self, type_id: str) -> ContainerType | None:
        return next((t for t in self.container_types if t.id == type_id), None)

    def line(self, line_id: str) -> ItemLine | None:
        return next((line for line in self.items if line.id == line_id), None)

    @property
    def n_items(self) -> int:
        return sum(line.qty for line in self.items)


@dataclass(frozen=True)
class Params:
    """Modeller's choices, not factory data; every reported result states them."""

    delta: float  # minimum horizontal gap between two items, m
    alpha: float  # minimum supported share of an item's base, 0–1


@dataclass(frozen=True)
class UsedContainer:
    k: int
    type: str


@dataclass(frozen=True)
class Placement:
    item: str  # "<line id>#<n>"
    k: int
    x: float
    y: float
    z: float
    o: str  # orientation code


@dataclass
class Solution:
    instance: str
    params: Params
    containers: list[UsedContainer]
    placements: list[Placement]
    meta: dict[str, Any] = field(default_factory=dict)


def item_id(line_id: str, n: int) -> str:
    return f"{line_id}#{n}"


def line_of(item: str) -> str:
    return item.rsplit("#", 1)[0]


def solution_cost(instance: Instance, solution: Solution) -> float:
    """Freight cost of the containers the solution opens."""
    total = 0.0
    for used in solution.containers:
        ctype = instance.container_type(used.type)
        if ctype is None:
            raise ValueError(f"unknown container type {used.type!r}")
        total += ctype.cost
    return total
