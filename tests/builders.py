"""Small hand-made instances and solutions for tests."""
from __future__ import annotations

from src.model import ContainerType, Instance, ItemLine, Params, Placement, Solution, UsedContainer

BOX = ContainerType(id="BOX", L=10.0, W=2.0, H=2.0, door_w=2.0, door_h=1.9, max_mass=1000.0, cost=1.0)
PARAMS = Params(delta=0.1, alpha=0.8)


def line(
    id: str,
    qty: int = 1,
    L: float = 1.0,
    W: float = 1.0,
    H: float = 1.0,
    mass: float = 10.0,
    tippable: bool = False,
    tiers: int = 5,
    load: float | None = None,
    orientations: tuple[str, ...] | None = None,
) -> ItemLine:
    return ItemLine(id=id, qty=qty, L=L, W=W, H=H, mass=mass, tippable=tippable, tiers=tiers, load=load,
                    orientations=orientations)


def instance(*lines: ItemLine, types: tuple[ContainerType, ...] = (BOX,)) -> Instance:
    return Instance(name="test", container_types=types, items=lines)


def at(item: str, x: float, y: float = 0.0, z: float = 0.0, o: str = "LWH", k: int = 1) -> Placement:
    return Placement(item=item, k=k, x=x, y=y, z=z, o=o)


def solution(*placements: Placement, containers: tuple[tuple[int, str], ...] = ((1, "BOX"),)) -> Solution:
    return Solution(
        instance="test",
        params=PARAMS,
        containers=[UsedContainer(k=k, type=t) for k, t in containers],
        placements=list(placements),
    )


def random_lot(seed: int, n_lines: int = 6, max_qty: int = 30) -> Instance:
    """A reproducible mixed lot on the standard container table:
    pallet-sized lines, some tippable, some load- or tier-limited. Used to pin engine outputs."""
    import random

    rng = random.Random(seed)
    lines = []
    for n in range(n_lines):
        L = round(rng.uniform(0.6, 2.4), 2)
        W = round(rng.uniform(0.5, min(L, 2.2)), 2)
        H = round(rng.uniform(0.4, 2.0), 2)
        lines.append(
            ItemLine(
                id=f"L{n + 1}",
                qty=rng.randint(1, max_qty),
                L=L,
                W=W,
                H=H,
                mass=round(rng.uniform(50.0, 900.0), 1),
                tippable=rng.random() < 0.3,
                tiers=rng.randint(1, 4),
                load=rng.choice([None, 0.0, round(rng.uniform(200.0, 2000.0), 1)]),
            )
        )
    return Instance(name=f"random-{seed}", container_types=STANDARD_CONTAINERS, items=tuple(lines))


# The standard container table: costs are made-up relative
# numbers (40DC = 1.0), for tests only.
STANDARD_CONTAINERS: tuple[ContainerType, ...] = (
    ContainerType(id="20DC", L=5.90, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=28000.0, cost=0.60),
    ContainerType(id="40DC", L=12.03, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=26700.0, cost=1.00),
    ContainerType(id="40HC", L=12.03, W=2.35, H=2.69, door_w=2.34, door_h=2.58, max_mass=26500.0, cost=1.05),
    ContainerType(id="45HC", L=13.56, W=2.35, H=2.70, door_w=2.34, door_h=2.58, max_mass=27700.0, cost=1.20),
)
