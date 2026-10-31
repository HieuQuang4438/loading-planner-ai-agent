"""E4 = ALNS over E1's or E2's packing core.

The initial solution is the full E1 or E2 solve -- core plus the shared fleet layer -- called with
the same `time_limit` as the plain E1/E2 engine, so it is exactly their solution (option 7A);
whatever time it leaves, up to `time_share` of `time_limit`, goes to the ALNS loop (`search.run`). On the
largest lots E2's own solve can take nearly all of it, leaving few or no iterations: `diagnostics`
records this (`time_initial`, `iterations`) rather than hiding it.
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable

from src.bound import lower_bound
from src.engines import e1, e2
from src.engines.e4.operators import Context, Settings
from src.engines.e4.packer import HintedPackOne, Packer
from src.engines.e4.search import run
from src.engines.e4.state import cost, from_solution, key, to_solution
from src.model import Instance, Params, Solution

CoreSolve = Callable[[Instance, Params, float, int], "tuple[Solution, dict[str, Any]]"]

CORES: dict[str, tuple[CoreSolve, HintedPackOne]] = {
    "e1": (e1.solve, e1.pack_one),
    "e2": (e2.solve, e2.pack_one),
}

# Chosen on split dev: one grid per core, each change against
# the untuned `Settings()`; E1 kept a smaller destroy share, E2 a faster weight reaction.
DEFAULTS: dict[str, Settings] = {
    "e1": Settings(destroy_share=0.15),
    "e2": Settings(reaction=0.3),
}


def solve(
    instance: Instance, params: Params, time_limit: float, seed: int, core: str, settings: Settings | None = None
) -> tuple[Solution, dict[str, Any]]:
    settings = settings or DEFAULTS[core]
    start = time.monotonic()
    deadline = start + settings.time_share * time_limit
    core_solve, pack_one = CORES[core]
    initial_solution, _ = core_solve(instance, params, time_limit, seed)
    time_initial = time.monotonic() - start

    packer = Packer(instance, params, pack_one, deadline)
    ctx = Context(instance, packer, random.Random(seed), settings)
    initial = from_solution(instance, initial_solution, packer.pieces)
    bound = lower_bound(instance).cost
    outcome = run(initial, ctx, bound, deadline)

    solution = to_solution(instance, params, outcome.best)
    return solution, {
        "engine": f"e4-{core}",
        "core": core,
        "initial_cost": cost(initial),
        "cost": cost(outcome.best),
        "bound": bound,
        "stop": outcome.stop,
        "time_initial": round(time_initial, 3),
        "time_total": round(time.monotonic() - start, 3),
        "iterations": outcome.iterations,
        "improvements": outcome.improvements,
        "accepted": outcome.accepted,
        "best_found_time": round(time_initial + outcome.best_time, 3) if outcome.improvements else round(time_initial, 3),
        "emptiest_fill_initial": round(key(initial)[1], 4),
        "emptiest_fill": round(key(outcome.best)[1], 4),
        "destroy": outcome.destroy,
        "repair": outcome.repair,
        "pack_one_calls": packer.calls,
        "cache_hits": packer.hits,
        "hint_wins": ctx.hint_wins,
        "hinted_containers": sum(1 for b in outcome.best if b.hints is not None),
        "settings": {
            "start_temperature": settings.start_temperature,
            "end_temperature": settings.end_temperature,
            "reaction": settings.reaction,
            "segment": settings.segment,
            "destroy_share": settings.destroy_share,
            "hint_retry": settings.hint_retry,
        },
    }


def solve_e1(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    return solve(instance, params, time_limit, seed, "e1")


def solve_e2(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    return solve(instance, params, time_limit, seed, "e2")
