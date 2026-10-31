"""E5's knapsack pricing (engine `e5-knap`): the item set handed to a core is the best bounded
multi-constraint knapsack for the round's duals, not the lines in dual-per-volume order up to a cap.

For one container type and duals `pi`: maximise sum(pi_i a_i) subject to sum(volume_i a_i) <= gamma * V_t,
sum(mass_i a_i) <= gamma * Q_t, 0 <= a_i <= qty_i integer. `gamma` < 1 leaves room for what the volume and
mass sums cannot see (geometry, support, tiers); `next_gamma` adapts it from what the core packed.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

PI_SCALE = 1_000_000  # duals are scaled to integers: objective coefficient = round(pi * PI_SCALE)
VOLUME_SCALE = 1_000_000  # m3 -> cm3 (a volume of 0.5 m3 is 500 000)
MASS_SCALE = 1_000  # kg -> g
AREA_SCALE = 10_000  # m2 -> cm2
# CP-SAT needs integer data. Item sizes are rounded up and capacities down, so a solution is feasible in the
# real numbers too; the error is at most one unit (1 cm3, 1 g) per item. Duals are rounded to the nearest
# unit of 1e-6, which only matters for ties.


def floor_share(L: float, W: float, H: float, mass: float, tiers: int, load: float | None, ctype_h: float) -> float:
    """Floor area one item takes when stacked with its own kind: footprint over the items one column can hold,
    min(tiers, load // mass + 1, H_t // h), at least 1. Upright footprint; a surrogate for what the cores do."""
    by_load = math.inf if load is None else math.floor(load / mass + 1e-9) + 1 if mass > 0 else math.inf
    by_height = math.floor(ctype_h / H + 1e-9) if H > 0 else 1
    k = max(1, min(tiers, by_load, by_height))
    return L * W / k


def solve(
    values: Sequence[float], volumes: Sequence[float], masses: Sequence[float], qtys: Sequence[int],
    volume_cap: float, mass_cap: float, time_limit: float,
    areas: Sequence[float] | None = None, area_cap: float | None = None,
) -> list[int]:
    """Counts `a_i` of the best knapsack found within `time_limit` seconds, one CP-SAT worker.

    `areas` (floor area per item, `floor_share`) with `area_cap` add the floor constraint (choice
    1B): items nothing may stand on take floor, not volume. The best feasible solution is returned when the
    search stops before proving optimality; all zeros when there is none (no time, no positive value)."""
    from ortools.sat.python import cp_model

    n = len(values)
    out = [0] * n
    if n == 0 or time_limit <= 0.0:
        return out
    model = cp_model.CpModel()
    a = [model.NewIntVar(0, int(q), f"a{i}") for i, q in enumerate(qtys)]
    model.Add(sum(math.ceil(v * VOLUME_SCALE) * x for v, x in zip(volumes, a)) <= math.floor(volume_cap * VOLUME_SCALE))
    model.Add(sum(math.ceil(m * MASS_SCALE) * x for m, x in zip(masses, a)) <= math.floor(mass_cap * MASS_SCALE))
    if areas is not None and area_cap is not None:
        model.Add(sum(math.ceil(s * AREA_SCALE) * x for s, x in zip(areas, a)) <= math.floor(area_cap * AREA_SCALE))
    model.Maximize(sum(round(pi * PI_SCALE) * x for pi, x in zip(values, a)))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 1
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return out
    return [int(solver.Value(x)) for x in a]


def next_gamma(gamma: float, packed_all: bool, down: float, up: float, low: float, high: float) -> float:
    """The core packed the whole set: raise `gamma` by `up`; it did not: lower it by `down`; kept in [low, high]."""
    return min(max(gamma + up if packed_all else gamma - down, low), high)
