"""Mode A (docs/product/brief.md §2.2): pack every piece of a confirmed lot, the solver (E5) choosing the container mix
of least total cost from the run's cost table; every plan goes through the independent checker (the job does it).
What a plan is compared with: the lower bound (`src.bound`) and two baselines a person gets by filling one container
type after another (E1's fleet layer, one type per run): the cheapest single type and the fewest containers.

The default cost table is simulated: its costs are not quotes.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from typing import Any

from src.bound import lower_bound
from src.checker import check
from src.engines import e1
from src.formats import fits_container, instance_to_dict
from src.lot.engine import to_instance
from src.lot.schema import Lot
from src.model import ContainerType, Instance, Params

# Inner sizes and limits of common dry containers; costs simulated (USD per container), not quotes.
DEFAULT_CONTAINERS: tuple[ContainerType, ...] = (
    ContainerType(id="20GP", L=5.898, W=2.352, H=2.393, door_w=2.34, door_h=2.28, max_mass=28000.0, cost=1500.0),
    ContainerType(id="40GP", L=12.032, W=2.352, H=2.393, door_w=2.34, door_h=2.28, max_mass=26700.0, cost=2300.0),
    ContainerType(id="40HC", L=12.032, W=2.352, H=2.698, door_w=2.34, door_h=2.58, max_mass=26500.0, cost=2500.0),
)
ENGINE = "e5"  # the job picks `e5-orient` from the orient flag (`orient_for`)
BASELINE_TIME_S = 5.0  # E1 per container type: a heuristic run, not a search


def orient_for(instance: Instance) -> bool:
    """Whether E5 searches the orientations too: only when some line may tip; for an all-upright lot it adds nothing."""
    return any(line.tippable for line in instance.items)


def run_lot(lot: Lot, containers: tuple[ContainerType, ...] = DEFAULT_CONTAINERS) -> tuple[dict[str, Any], bool]:
    """The engine's lot as JSON (what a job takes) and the orient flag; `LotNotReady` when a field is not confirmed."""
    instance = to_instance(lot, containers)
    return instance_to_dict(instance), orient_for(instance)


@dataclass(frozen=True)
class Baseline:
    """One container type filled one after another: how many, at what cost, and whether the checker passed it."""

    type: str
    containers: int
    cost: float
    ok: bool
    seconds: float


def baselines(instance: Instance, params: Params, seed: int = 1, time_limit: float = BASELINE_TIME_S) -> list[Baseline]:
    """E1 with one container type at a time, for every type every line fits (a line that fits no single type leaves
    that type out: the fleet layer would move it to another type, and the baseline would no longer be one type)."""
    out = []
    for ctype in instance.container_types:
        if not all(fits_container(line, ctype) for line in instance.items):
            continue
        alone = replace(instance, container_types=(ctype,))
        start = time.monotonic()
        solution, _ = e1.solve(alone, params, time_limit, seed)
        result = check(alone, solution, params)
        out.append(Baseline(type=ctype.id, containers=len(solution.containers), cost=result.cost or 0.0, ok=result.ok,
                            seconds=round(time.monotonic() - start, 2)))
    return out


def compare(instance: Instance, params: Params, seed: int = 1) -> dict[str, Any]:
    """What a mode-A plan of `instance` is compared with: the lower bound, every single-type baseline, the cheapest
    one and the one with the fewest containers (ties: the cheaper). Only baselines the checker passed count."""
    bound = lower_bound(instance)
    rows = baselines(instance, params, seed)
    valid = [b for b in rows if b.ok]
    cheapest = min(valid, key=lambda b: (b.cost, b.containers), default=None)
    fewest = min(valid, key=lambda b: (b.containers, b.cost), default=None)
    return {
        "bound": {"cost": bound.cost, "fleet": bound.fleet, "binding": bound.binding},
        "baselines": [asdict(b) for b in rows],
        "cheapest_single": asdict(cheapest) if cheapest else None,
        "fewest_containers": asdict(fewest) if fewest else None,
        "settings": {"engine": "e1", "seed": seed, "time_limit": BASELINE_TIME_S, "delta": params.delta,
                     "alpha": params.alpha},
    }
