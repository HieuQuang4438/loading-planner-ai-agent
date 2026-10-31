"""E1 = "chồng trước, trải sàn sau": the column + maxrects
core of `src.engines.e1.pack` under the shared fleet layer (`src.engines.fleet`). No search: one
deterministic pass per container, so `seed` changes nothing.
"""
from __future__ import annotations

import random
from typing import Any

from src.engines import fleet
from src.engines.base import Hints, Piece
from src.engines.e1.pack import pack
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, Params, Placement, Solution, line_of


def pack_one(
    items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random, hints: Hints | None = None
) -> list[Placement]:
    """`src.engines.base.PackOne` for E1; `rng` is unused (deterministic core). `hints` steer the
    floor step (`src.engines.e1.pack`); without them the core runs exactly as the fleet layer uses it."""
    return pack(items, ctype, params.delta, hints)


def pack_one_tilt(
    items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random, hints: Hints | None = None
) -> list[Placement]:
    """`pack_one` with tippable pieces tipped onto their lowest height first (probe;
    E5's `e1-tilt` core)."""
    return pack(items, ctype, params.delta, hints, tilt_first=True)


def pack_one_orient_dense(
    items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random, hints: Hints | None = None
) -> list[Placement]:
    """`pack_one` with each piece in the allowed orientation that packs the most pieces per m² of
    floor (`src.engines.e1.orientation.dense_orientation`; E5's `e1-orient-dense` core)."""
    return pack(items, ctype, params.delta, hints, dense=True)


def solve(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    calls = 0

    def counted(items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random) -> list[Placement]:
        nonlocal calls
        calls += 1
        return pack_one(items, ctype, params, rng)

    solution = fleet.solve(instance, params, time_limit, seed, counted)
    return solution, _diagnostics(instance, solution, calls)


def solve_orient_dense(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E1 with the dense orientation rule (engine `e1-orient-dense`); deterministic, for screening."""
    calls = 0

    def counted(items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random) -> list[Placement]:
        nonlocal calls
        calls += 1
        return pack_one_orient_dense(items, ctype, params, rng)

    solution = fleet.solve(instance, params, time_limit, seed, counted)
    return solution, {**_diagnostics(instance, solution, calls), "engine": "e1-orient-dense"}


def _diagnostics(instance: Instance, solution: Solution, calls: int) -> dict[str, Any]:
    """Cheap figures read off the returned solution: every piece of a column shares the column's
    (k, x, y) corner, and no two columns can."""
    heights: dict[tuple[int, float, float], float] = {}
    counts: dict[tuple[int, float, float], int] = {}
    for p in solution.placements:
        line = instance.line(line_of(p.item))
        assert line is not None
        key = (p.k, p.x, p.y)
        top = p.z + line.dims(p.o)[2]
        heights[key] = max(heights.get(key, 0.0), top)
        counts[key] = counts.get(key, 0) + 1
    n_columns = len(counts)
    tippable = sum(line.qty for line in instance.items if any(c not in UPRIGHT_ORIENTATIONS for c in line.allowed))
    return {
        "engine": "e1",
        "columns": n_columns,
        "mean_pieces_per_column": round(len(solution.placements) / n_columns, 3) if n_columns else 0.0,
        "max_pieces_per_column": max(counts.values(), default=0),
        "mean_column_height_m": round(sum(heights.values()) / n_columns, 3) if n_columns else 0.0,
        "tipped_items": sum(1 for p in solution.placements if p.o not in UPRIGHT_ORIENTATIONS),
        "tippable_items": tippable,
        "pack_one_calls": calls,
        "last_container_swapped": solution.meta.get("last_container_swapped", False),
        "mixed_container_types": len({c.type for c in solution.containers}) > 1,
    }
