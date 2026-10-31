"""E2b = block building: the core of `src.engines.e2b.pack`
under the shared fleet layer (`src.engines.fleet`). No search: one deterministic pass per container,
so `seed` changes nothing.
"""
from __future__ import annotations

import random
from functools import partial
from typing import Any

from src.engines import fleet
from src.engines.base import Piece
from src.engines.e2b.pack import DEFAULT_CONFIG, Config, PackStats, pack
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, Params, Placement, Solution


def pack_one(
    items: list[Piece],
    ctype: ContainerType,
    params: Params,
    rng: random.Random,
    config: Config = DEFAULT_CONFIG,
    stats: PackStats | None = None,
) -> list[Placement]:
    """`src.engines.base.PackOne` for E2b; `rng` is unused (deterministic core)."""
    return pack(items, ctype, params.delta, params.alpha, config, stats)


def solve(
    instance: Instance, params: Params, time_limit: float, seed: int, config: Config = DEFAULT_CONFIG
) -> tuple[Solution, dict[str, Any]]:
    calls = 0
    total = PackStats()
    per_container: dict[frozenset[str], list[int]] = {}  # placed item ids -> items per block

    def counted(items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random) -> list[Placement]:
        nonlocal calls
        calls += 1
        call = PackStats()
        placed = pack_one(items, ctype, params, rng, config, call)
        per_container[frozenset(p.item for p in placed)] = call.blocks
        total.blocks += call.blocks
        total.spaces_generated += call.spaces_generated
        total.spaces_peak = max(total.spaces_peak, call.spaces_peak)
        total.spaces_examined += call.spaces_examined
        total.tries_capped += call.tries_capped
        return placed

    solution = fleet.solve(instance, params, time_limit, seed, counted)
    return solution, _diagnostics(solution, calls, total, per_container)


def solve_with(config: Config):
    """`solve` with a fixed `config`, picklable (the runner sends the engine to a child process)."""
    return partial(solve, config=config)


def _diagnostics(
    solution: Solution, calls: int, total: PackStats, per_container: dict[frozenset[str], list[int]]
) -> dict[str, Any]:
    by_k: dict[int, set[str]] = {}
    for p in solution.placements:
        by_k.setdefault(p.k, set()).add(p.item)
    blocks = [n for items in by_k.values() for n in per_container.get(frozenset(items), [])]
    return {
        "engine": "e2b",
        "pack_one_calls": calls,
        "blocks": len(blocks),
        "mean_items_per_block": round(sum(blocks) / len(blocks), 3) if blocks else 0.0,
        "max_items_per_block": max(blocks, default=0),
        "single_item_blocks": sum(1 for n in blocks if n == 1),
        "blocks_all_calls": len(total.blocks),
        "spaces_generated": total.spaces_generated,
        "spaces_examined": total.spaces_examined,
        "spaces_peak": total.spaces_peak,
        "spaces_given_up_at_try_cap": total.tries_capped,
        "tipped_items": sum(1 for p in solution.placements if p.o not in UPRIGHT_ORIENTATIONS),
        "last_container_swapped": solution.meta.get("last_container_swapped", False),
        "mixed_container_types": len({c.type for c in solution.containers}) > 1,
    }
