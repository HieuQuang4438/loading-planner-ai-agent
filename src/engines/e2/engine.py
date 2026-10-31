"""E2 = extreme point: the core of `src.engines.e2.pack`
under the shared fleet layer (`src.engines.fleet`). No search: one deterministic pass per container,
so `seed` changes nothing.
"""
from __future__ import annotations

import random
from typing import Any

import numpy as np

from src.engines import fleet
from src.engines.base import Hints, Piece
from src.engines.e2.layout import TOUCH
from src.engines.e2.pack import pack
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, Params, Placement, Solution, line_of


def pack_one(
    items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random, hints: Hints | None = None
) -> list[Placement]:
    """`src.engines.base.PackOne` for E2; `rng` is unused (deterministic core). `hints` steer piece
    order and turn preference (`src.engines.e2.pack`); without them the core runs as the fleet layer
    uses it."""
    return pack(items, ctype, params.delta, params.alpha, hints)


def pack_one_orient(
    items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random, hints: Hints | None = None
) -> list[Placement]:
    """`pack_one` with every allowed orientation tried at every extreme point (E5's
    `e2-orient` core)."""
    return pack(items, ctype, params.delta, params.alpha, hints, orient=True)


def solve(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    calls = 0

    def counted(items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random) -> list[Placement]:
        nonlocal calls
        calls += 1
        return pack_one(items, ctype, params, rng)

    solution = fleet.solve(instance, params, time_limit, seed, counted)
    return solution, _diagnostics(instance, solution, calls)


def support_profile(instance: Instance, solution: Solution) -> list[tuple[int, float]]:
    """(number of boxes it rests on, supported share of its base) for every box off the floor, by
    the checker's "rests on" relation and tolerance (read off the solution, not the core's state)."""
    by_k: dict[int, list[tuple[float, float, float, float, float, float]]] = {}
    for p in solution.placements:
        line = instance.line(line_of(p.item))
        assert line is not None
        l, w, h = line.dims(p.o)
        by_k.setdefault(p.k, []).append((p.x, p.y, p.z, l, w, h))
    profile: list[tuple[int, float]] = []
    for boxes in by_k.values():
        x, y, z, l, w, h = (np.array(col) for col in zip(*boxes))
        top = z + h
        for j in np.flatnonzero(z > TOUCH):
            ox = np.minimum(x[j] + l[j], x + l) - np.maximum(x[j], x)
            oy = np.minimum(y[j] + w[j], y + w) - np.maximum(y[j], y)
            rests = (np.abs(top - z[j]) <= TOUCH) & (ox > TOUCH) & (oy > TOUCH)
            profile.append((int(rests.sum()), float((ox * oy)[rests].sum() / (l[j] * w[j]))))
    return profile


def _diagnostics(instance: Instance, solution: Solution, calls: int) -> dict[str, Any]:
    profile = support_profile(instance, solution)
    tippable = sum(line.qty for line in instance.items if any(c not in UPRIGHT_ORIENTATIONS for c in line.allowed))
    return {
        "engine": "e2",
        "items_off_floor": len(profile),
        "bridged_items": sum(1 for n, _ in profile if n >= 2),
        "overhanging_items": sum(1 for _, share in profile if share < 1.0 - 1e-9),
        "min_support_share": round(min((share for _, share in profile), default=1.0), 4),
        "tipped_items": sum(1 for p in solution.placements if p.o not in UPRIGHT_ORIENTATIONS),
        "tippable_items": tippable,
        "pack_one_calls": calls,
        "last_container_swapped": solution.meta.get("last_container_swapped", False),
        "mixed_container_types": len({c.type for c in solution.containers}) > 1,
    }


def solve_orient(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E2 with the orient mode (engine `e2-orient`); deterministic, for screening."""
    calls = 0

    def counted(items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random) -> list[Placement]:
        nonlocal calls
        calls += 1
        return pack_one_orient(items, ctype, params, rng)

    solution = fleet.solve(instance, params, time_limit, seed, counted)
    return solution, {**_diagnostics(instance, solution, calls), "engine": "e2-orient"}
