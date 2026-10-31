"""E3 = BRKGA over E1's or E2's packing core.

As E4 (option 3A): the initial incumbent is the full E1 or E2 solve -- core plus the shared fleet
layer -- called with the same `time_limit` as the plain E1/E2 engine, so E3 is never worse than it;
whatever time that leaves, up to `time_share` of `time_limit`, goes to the BRKGA loop
(`search.run`). The decoder calls the core through E4's cached `Packer`. On the largest lots E2's own
solve can take nearly all the time, leaving few or no decodes: `diagnostics` records this
(`time_initial`, `decodes`, `generations`) rather than hiding it.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Callable

from src.bound import lower_bound
from src.engines import e1, e2
from src.engines.e3.decoder import Decoder
from src.engines.e3.search import Settings, run
from src.engines.e4.packer import HintedPackOne, Packer
from src.engines.e4.state import cost, from_solution, key, to_solution
from src.model import Instance, Params, Solution

CoreSolve = Callable[[Instance, Params, float, int], "tuple[Solution, dict[str, Any]]"]

CORES: dict[str, tuple[CoreSolve, HintedPackOne]] = {
    "e1": (e1.solve, e1.pack_one),
    "e2": (e2.solve, e2.pack_one),
}

# Chosen on split dev.
DEFAULTS: dict[str, Settings] = {
    "e1": Settings(),
    "e2": Settings(pop_factor=0.5, pop_min=10, pop_cap=50),
}


def slots_for(n_containers: int) -> int:
    """Container-type keys in the chromosome: the incumbent's count plus half again (at least 2)."""
    return n_containers + max(2, math.ceil(n_containers / 2))


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
    initial = from_solution(instance, initial_solution, packer.pieces)
    decoder = Decoder(instance, packer, slots_for(len(initial)))
    bound = lower_bound(instance).cost
    outcome = run(decoder, initial, [b.type.id for b in initial], settings, random.Random(seed), bound, deadline)

    solution = to_solution(instance, params, outcome.best)
    return solution, {
        "engine": f"e3-{core}",
        "core": core,
        "initial_cost": cost(initial),
        "cost": cost(outcome.best),
        "bound": bound,
        "stop": outcome.stop,
        "time_initial": round(time_initial, 3),
        "time_total": round(time.monotonic() - start, 3),
        "best_found_time": round(time_initial + outcome.best_time, 3) if outcome.improvements else round(time_initial, 3),
        "chromosome_length": decoder.length,
        "slots": decoder.slots,
        "population": outcome.population,
        "generations": outcome.generations,
        "decodes": outcome.decodes,
        "improvements": outcome.improvements,
        "restarts": outcome.restarts,
        "emptiest_fill_initial": round(key(initial)[1], 4),
        "emptiest_fill": round(key(outcome.best)[1], 4),
        "pack_one_calls": packer.calls,
        "cache_hits": packer.hits,
        "settings": {
            "elite": settings.elite,
            "mutant": settings.mutant,
            "rho_e": settings.rho_e,
            "pop_factor": settings.pop_factor,
            "pop_min": settings.pop_min,
            "pop_cap": settings.pop_cap,
            "restart_after": settings.restart_after,
        },
    }


def solve_e1(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    return solve(instance, params, time_limit, seed, "e1")


def solve_e2(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    return solve(instance, params, time_limit, seed, "e2")
