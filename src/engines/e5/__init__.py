"""E5 = set cover (>= qty, surplus trimmed afterwards) over containers laid out by E1's and E2's cores.
Versions: `solve_v1` / `solve_v2` are registered under
`src.engines.base` as `"e5-v1"` / `"e5-v2"` / `"e5-v3"` / `"e5-v4"`, `solve_orient_v1` /
`solve_orient_v2` / `solve_orient_v3` / `solve_orient_v4` as `"e5-orient-v1"` / `"e5-orient-v2"` / `"e5-orient-v3"` / `"e5-orient-v4"`, and `solve` / `solve_orient` as `"e5"` / `"e5-orient"`, the default version
(`engine.DEFAULT_VERSION`). The branch variants build on e5-v1: `solve_brkga` as `"e5-brkga"` (E3's BRKGA instead) and `solve_tilt` as `"e5-tilt"` (probe), `solve_e1` / `solve_e2` as `"e5-e1"` / `"e5-e2"` (one packing core only) and `solve_blocks` as `"e5-blocks"` (E2b seeds ALNS on E1 and E2) and `solve_seed_e1` as `"e5-seed-e1"` (E1 seeds instead control) and `solve_knap` as `"e5-knap"` (knapsack pricing); milestone 4's trial engines (`"e5-mono"` = e5-v2, `"e5-mono-*"`) are kept to rerun its numbers; `solve_ps` / `solve_orient_ps` as `"e5-ps"` / `"e5-orient-ps"` (e5-v3 / e5-orient-v3 plus PackingSolver as a column
generator, `solve_psbs` / `solve_orient_psbs` as `"e5-psbs"` / `"e5-orient-psbs"` (the same with `boxstacks` and a door
filter; they need `packingsolver3d`, which is not in `requirements.txt`); `solve_v2_pace` as
`"e5-v2-pace"` is a trial on e5-v2, `solve_v2_lean` as `"e5-v2-lean"` one on e5-v2-pace that
equals e5-v3 (kept to rerun its numbers); `solve_v3_stall` / `solve_orient_v3_stall` as `"e5-v3-stall"` /
`"e5-orient-v3-stall"` equal e5-v4 / e5-orient-v4 (trial names; runs record e5-v4). All by
`src.engines` (the built-in registry), not here.

OR-Tools is imported only when `solve` runs, as for E6 and E7.
"""
from __future__ import annotations

from typing import Any

from src.model import Instance, Params, Solution


def _version(instance: Instance, params: Params, time_limit: float, seed: int, version: str | None,
             orient: bool = False, start: Solution | None = None, ps: bool | str = False) -> tuple[Solution, dict[str, Any]]:
    """One E5 version (None: the default one), with the orientation option when `orient`; `start`:
    an earlier solution to continue from; `ps`: PackingSolver as a column generator."""
    from dataclasses import replace

    from src.engines.e5.engine import DEFAULT_VERSION, PS_INITIAL_SHARE, PS_PRICE_TIME, VERSIONS
    from src.engines.e5.engine import solve as solve_e5

    s = VERSIONS[version or DEFAULT_VERSION]
    if orient:
        s = replace(s, orient_dense_core=True, e2_orient=True)
    if ps:
        s = replace(s, ps_initial_share=PS_INITIAL_SHARE, ps_price_time=PS_PRICE_TIME)
        if ps == "boxstacks":
            s = replace(s, ps_solver="boxstacks", ps_door_filter=True)
    return solve_e5(instance, params, time_limit, seed, s, start)


def solve(instance: Instance, params: Params, time_limit: float, seed: int,
          start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """`e5`: the default version (e5-v4)."""
    return _version(instance, params, time_limit, seed, None, start=start)


def solve_v1(instance: Instance, params: Params, time_limit: float, seed: int,
             start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """E5 as first built, before the changes of v2 to v4."""
    return _version(instance, params, time_limit, seed, "e5-v1", start=start)


def solve_v2(instance: Instance, params: Params, time_limit: float, seed: int,
             start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """e5-v1 that does not get dearer when the time limit grows."""
    return _version(instance, params, time_limit, seed, "e5-v2", start=start)


def solve_v3(instance: Instance, params: Params, time_limit: float, seed: int,
             start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """e5-v2 keeping each step's deadline and solving the master on a reduced pool."""
    return _version(instance, params, time_limit, seed, "e5-v3", start=start)


def solve_v4(instance: Instance, params: Params, time_limit: float, seed: int,
             start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """e5-v3 whose ALNS stops when it stalls."""
    return _version(instance, params, time_limit, seed, "e5-v4", start=start)


def solve_orient(instance: Instance, params: Params, time_limit: float, seed: int,
                 start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """`e5-orient`: the default version plus the `e1-orient-dense` core and E2's core trying every allowed
    orientation."""
    return _version(instance, params, time_limit, seed, None, orient=True, start=start)


def solve_orient_v1(instance: Instance, params: Params, time_limit: float, seed: int,
                    start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    return _version(instance, params, time_limit, seed, "e5-v1", orient=True, start=start)


def solve_orient_v2(instance: Instance, params: Params, time_limit: float, seed: int,
                    start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    return _version(instance, params, time_limit, seed, "e5-v2", orient=True, start=start)


def solve_orient_v3(instance: Instance, params: Params, time_limit: float, seed: int,
                    start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    return _version(instance, params, time_limit, seed, "e5-v3", orient=True, start=start)


def solve_orient_v4(instance: Instance, params: Params, time_limit: float, seed: int,
                    start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    return _version(instance, params, time_limit, seed, "e5-v4", orient=True, start=start)


def solve_v3_stall(instance: Instance, params: Params, time_limit: float, seed: int,
                   start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """Equals e5-v4 (trial name; runs record e5-v4)."""
    return _version(instance, params, time_limit, seed, "e5-v3-stall", start=start)


def solve_orient_v3_stall(instance: Instance, params: Params, time_limit: float, seed: int,
                          start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    return _version(instance, params, time_limit, seed, "e5-v3-stall", orient=True, start=start)


def solve_ps(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-ps`: e5-v3 plus PackingSolver as a column generator (not a service engine). Raises
    `src.packingsolver.PackingSolverMissing` when `packingsolver3d` is not installed."""
    return _version(instance, params, time_limit, seed, "e5-v3", ps=True)


def solve_orient_ps(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-orient-ps`: e5-orient-v3 plus PackingSolver as a column generator (not a service engine)."""
    return _version(instance, params, time_limit, seed, "e5-v3", orient=True, ps=True)


def solve_psbs(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-psbs`: `e5-ps` with PackingSolver's `boxstacks` solver (load and tier limits) and only rotations that pass the
    container door (not a service engine)."""
    return _version(instance, params, time_limit, seed, "e5-v3", ps="boxstacks")


def solve_orient_psbs(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-orient-psbs`: `e5-orient-ps` with `boxstacks` and the door filter (not a service engine)."""
    return _version(instance, params, time_limit, seed, "e5-v3", orient=True, ps="boxstacks")


def solve_brkga(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(search="brkga"))


def solve_tilt(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E5 plus the `e1-tilt` core (probe; not a service engine)."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(tilt_core=True))


def solve_e1(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E5 with E1's core only."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(cores=("e1",)))


def solve_e2(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E5 with E2's core only."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(cores=("e2",)))


def solve_blocks(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E5 whose initial solution is E2b's, searched by ALNS on E1's and E2's cores."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(initial_core="e2b"))


def solve_seed_e1(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E5 whose initial solution is E1's, searched by ALNS on E1's and E2's cores (control)."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(initial_core="e1"))


def solve_knap(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """E5 whose pricing hands the cores knapsack item sets (not a service engine)."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(pricing="knapsack"))


def solve_mono_flat(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-mono` as measured: initial solves to the end and the "flat" ALNS, no re-solve."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(initial_to_end=True, alns_acceptance="flat"))


def solve_mono_lahc(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-mono` whose harvest ALNS accepts by late acceptance (candidate)."""
    from src.engines.e5.engine import Settings
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, Settings(initial_to_end=True, alns_acceptance="lahc"))


def _mono_at(instance: Instance, params: Params, time_limit: float, seed: int, temperature: float) -> tuple[Solution, dict[str, Any]]:
    """e5-v2 with its "flat" ALNS at `temperature` x T0 instead of 0.2 (0.1 left S c2 lots dearer than
    e5-v1)."""
    from dataclasses import replace

    from src.engines.e5.engine import VERSIONS
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, replace(VERSIONS["e5-v2"], alns_flat_temperature=temperature))


def solve_mono_t10(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """`e5-mono` as measured at 6bbe16f: "flat" ALNS at 0.1 x T0."""
    return _mono_at(instance, params, time_limit, seed, 0.1)  # module-level: run workers pickle the solver


def solve_mono_t30(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    return _mono_at(instance, params, time_limit, seed, 0.3)


def solve_v2_pace(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """e5-v2 whose masters and LP build sparse and keep to their deadlines (trial, not a version)."""
    from dataclasses import replace

    from src.engines.e5.engine import VERSIONS
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed, replace(VERSIONS["e5-v2"], pace=True))


def solve_v2_lean(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """e5-v2-pace whose pool stores sparse columns and whose integer masters get at most `master_columns` columns
    past the dominance pass. Equals e5-v3; kept to rerun its numbers."""
    from dataclasses import replace

    from src.engines.e5.engine import VERSIONS
    from src.engines.e5.engine import solve as solve_e5

    return solve_e5(instance, params, time_limit, seed,
                    replace(VERSIONS["e5-v2"], pace=True, sparse_pool=True, reduce_master=True))


__all__ = ["solve", "solve_v1", "solve_v2", "solve_v3", "solve_orient", "solve_orient_v1", "solve_orient_v2", "solve_orient_v3", "solve_v4", "solve_orient_v4", "solve_ps", "solve_orient_ps", "solve_psbs", "solve_orient_psbs", "solve_v3_stall", "solve_orient_v3_stall", "solve_v2_pace", "solve_v2_lean", "solve_mono_lahc", "solve_mono_flat", "solve_mono_t10", "solve_mono_t30", "solve_brkga", "solve_tilt", "solve_e1", "solve_e2", "solve_blocks", "solve_seed_e1", "solve_knap"]
