"""Mode B (docs/product/brief.md §2.2; ADR-0002): the containers at hand are fixed, the solver (`e5-fill`) packs as
many pieces as fit, lexicographically by the user's priority order; what is left over is reported. Every plan goes
through the independent checker as the lot of the pieces it places (the job does it).

What a plan is compared with: the baseline a person gets by offering pieces in priority order, container after
container (E1's core, `src.engines.fill.sequential`), checked the same way.
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from src.checker import check
from src.engines import e1, fill
from src.lot.engine import to_instance
from src.lot.schema import Lot
from src.model import ContainerType, Instance, Params, Placement, Solution, UsedContainer, item_id, line_of

ENGINE = "e5-fill"  # the job picks `e5-fill-orient` from the orient flag (`mode_a.orient_for`)


def fill_instance(lot: Lot, containers: tuple[ContainerType, ...], fleet: dict[str, int], priority: list[str] | None,
                  partial: bool) -> Instance:
    """The engine's lot with the run's fleet, priority (default: the lot's line order) and partial flag; `LotNotReady`
    when a field is not confirmed, ValueError when the settings do not fit the lot."""
    instance = to_instance(lot, containers)
    meta = {**instance.meta, fill.META_KEY: {"fleet": {t: n for t, n in fleet.items() if n},
                                              "priority": list(priority or [line.id for line in instance.items]),
                                              "partial": partial}}
    instance = replace(instance, meta=meta)
    fill.spec_of(instance)
    return instance


def baseline(instance: Instance, params: Params) -> dict[str, Any]:
    """Pieces offered in priority order, container after container, by E1's core; checked as the lot it places.
    Items are numbered per line from 1, as the engine's are: the lot checked has each line's placed count, so a piece
    kept under its E1 number (`SKU-C#48` when three of 50 do not fit) would be no item of it."""
    spec = fill.spec_of(instance)
    start = time.monotonic()
    packed = fill.sequential(instance, spec, params, e1.pack_one)
    containers, placements = [], []
    numbers: dict[str, int] = {}
    for k, (ctype, placed) in enumerate([c for c in packed if c[1]], 1):
        containers.append(UsedContainer(k, ctype.id))
        for p in placed:
            line = line_of(p.item)
            numbers[line] = numbers.get(line, 0) + 1
            placements.append(Placement(item_id(line, numbers[line]), k, p.x, p.y, p.z, p.o))
    solution = Solution(instance.name, params, containers, placements)
    result = check(fill.placed_instance(instance, solution), solution, params)
    held = fill.placed_counts(packed)
    return {
        "lines": [{"id": line, "placed": held.get(line, 0)} for line in spec.priority],
        "placed": sum(held.values()),
        "total": instance.n_items,
        "containers": len(containers),
        "ok": result.ok,
        "seconds": round(time.monotonic() - start, 2),
        "settings": {"engine": "e1", "delta": params.delta, "alpha": params.alpha},
    }
