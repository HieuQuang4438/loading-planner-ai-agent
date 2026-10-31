"""Cost lower bound per instance, and which constraint explains it.

Three relaxations of the container-selection problem. Each is a valid lower bound on the true
minimum fleet cost, because every row below drops constraints the real problem has (or ignores a
quantity that can only make packing harder), so any real solution needs at least as many containers
as the relaxed row requires:

- **volume**: every item's volume must fit inside some container's volume. Ignores shape, gaps and
  orientation entirely.
- **mass**: every item's mass must fit inside some container's mass limit. Ignores shape entirely.
- **floor**: an item is forced onto the container floor when its `tiers == 1`, or when no other item
  of the lot can bear it (`_on_floor`). Proof: if item `j` is not on the floor, constraint 7 makes it
  rest on some item `i`, so `j` lies in the upward "rests on" closure of `i` and constraint 8
  (docs/reference/constraints.md) needs `load_i >= mass_j`; the stack through `i` then holds at least 2 items,
  so `tiers_i >= 2`. Hence `j` is on the floor whenever `tiers_j == 1` or every other item `i` has
  `tiers_i == 1` or `load_i < mass_j` (`load` empty means unlimited; `j`'s own line counts as a
  possible supporter only when its `qty >= 2`). Floor-forced items never overlap in x-y, so the sum
  of their footprints, over a fleet's total floor area, must fit; `delta` is ignored (the real
  requirement only grows once gaps are added, so dropping it keeps the bound valid, just looser). A
  tippable item may present any of its three faces to the floor, so its footprint is the smallest of
  the three; a non-tippable item is always upright, so its footprint is fixed at `L * W`. The row
  compares area only: it cannot see that two wide items do not fit side by side across the width.

`lower_bound` solves the combined 3-row integer program exactly by small branch-and-bound (the
number of container types is a handful, so exact enumeration beats adding a MIP dependency), and
solves each row alone to report which single constraint explains the combined result ("binding"),
and drops each row in turn to report which rows raise the combined result ("contributing").
This module imports only `src.model`, never solver code — there is none yet, and this module must
stay usable without one.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from src.model import Instance, ItemLine

EPS = 1e-6  # cost/quantity tolerance, matches src.checker.EPS

ROW_NAMES: tuple[str, ...] = ("volume", "mass", "floor")


@dataclass(frozen=True)
class RowBound:
    """The exact minimum fleet cost that satisfies one relaxed row alone."""

    cost: float
    fleet: dict[str, int]  # container type id -> count, zero counts omitted


@dataclass(frozen=True)
class Bound:
    """The combined lower bound, plus each row's own bound for the "binding" report."""

    cost: float
    fleet: dict[str, int]
    binding: str  # "volume" | "mass" | "floor" | "mixed" | "none" (empty lot)
    rows: dict[str, RowBound] = field(default_factory=dict)  # keyed by ROW_NAMES
    # Rows without which the combined bound would be lower. A row can contribute without binding
    # alone: under "mixed", mass may raise the bound above the volume row's own.
    contributing: tuple[str, ...] = ()


def lower_bound(instance: Instance) -> Bound:
    types = instance.container_types
    ids = [t.id for t in types]
    costs = [t.cost for t in types]
    coeffs = {
        "volume": [t.volume for t in types],
        "mass": [t.max_mass for t in types],
        "floor": [t.L * t.W for t in types],
    }
    targets = {
        "volume": sum(line.qty * line.volume for line in instance.items),
        "mass": sum(line.qty * line.mass for line in instance.items),
        "floor": sum(line.qty * _min_footprint(line) for line in _on_floor(instance.items)),
    }

    rows = {name: _row_bound(costs, ids, coeffs[name], targets[name]) for name in ROW_NAMES}

    active = [name for name in ROW_NAMES if targets[name] > EPS]
    if not active:
        return Bound(cost=0.0, fleet={}, binding="none", rows=rows)

    combined_cost, combined_alloc = _min_cost_cover(
        costs, [coeffs[name] for name in active], [targets[name] for name in active]
    )
    combined_cost = round(combined_cost, 9)  # drop float noise from summing costs
    fleet = {ids[i]: n for i, n in enumerate(combined_alloc) if n > 0}
    binding = _binding(rows, active, combined_cost)
    # A row that binds alone keeps the bound whatever else is dropped, so only it can contribute.
    candidates = active if binding == "mixed" else [binding]
    contributing = tuple(
        name for name in candidates if _without(costs, coeffs, targets, rows, active, name) < combined_cost - EPS
    )

    return Bound(cost=combined_cost, fleet=fleet, binding=binding, rows=rows, contributing=contributing)


def _without(
    costs: list[float],
    coeffs: dict[str, list[float]],
    targets: dict[str, float],
    rows: dict[str, RowBound],
    active: list[str],
    dropped: str,
) -> float:
    """The combined bound with one row dropped."""
    kept = [name for name in active if name != dropped]
    if not kept:
        return 0.0
    if len(kept) == 1:
        return rows[kept[0]].cost
    cost, _ = _min_cost_cover(costs, [coeffs[name] for name in kept], [targets[name] for name in kept])
    return cost


def _binding(rows: dict[str, RowBound], active: list[str], combined_cost: float) -> str:
    """Which single row's own bound equals the combined bound.

    Ties (two rows independently equal the combined bound) report the first in `ROW_NAMES` order
    (volume, then mass, then floor) — any of the tied rows is an equally correct explanation. When no
    single row's bound equals the combined bound, the rows only bind together: report "mixed".
    """
    matches = [name for name in active if abs(rows[name].cost - combined_cost) <= EPS]
    return matches[0] if matches else "mixed"


def _row_bound(costs: list[float], ids: list[str], coeff: list[float], target: float) -> RowBound:
    if target <= EPS:
        return RowBound(cost=0.0, fleet={})
    cost, alloc = _min_cost_cover(costs, [coeff], [target])
    return RowBound(cost=round(cost, 9), fleet={ids[i]: n for i, n in enumerate(alloc) if n > 0})


def _on_floor(lines: Sequence[ItemLine]) -> list[ItemLine]:
    """Lines whose every item must sit on the container floor (module docstring, floor row)."""
    return [line for line in lines if line.tiers == 1 or not any(_can_bear(i, line) for i in lines)]


def _can_bear(lower: ItemLine, upper: ItemLine) -> bool:
    """Whether some item of `lower` could carry an item of `upper` resting on it (constraint 8).

    Same-line support needs a second item of that line. The `EPS` slack matches the checker's own
    load test, so this never calls a stack infeasible that the checker would accept.
    """
    if lower.tiers < 2:
        return False
    if lower.id == upper.id and lower.qty < 2:
        return False
    return lower.load is None or lower.load >= upper.mass - EPS


def _min_footprint(line: ItemLine) -> float:
    """Smallest floor footprint (x-y extent) over the line's allowed orientations."""
    if line.orientations is None:
        if not line.tippable:
            return line.L * line.W
        return min(line.L * line.W, line.L * line.H, line.W * line.H)
    return min(a * b for a, b, _ in (line.dims(o) for o in line.allowed))


def _min_cost_cover(
    costs: Sequence[float], coeffs: Sequence[Sequence[float]], targets: Sequence[float]
) -> tuple[float, tuple[int, ...]]:
    """Exact solve of `min sum(costs[t]*n[t])` s.t. for every row r, `sum(coeffs[r][t]*n[t]) >= targets[r]`,
    every `n[t]` a non-negative integer.

    Branch-and-bound over container types: few types (a handful at most), so exact enumeration beats
    a MIP dependency. Two things keep the search small despite that: the incumbent starts from an
    LP-rounded near-optimal solution instead of a loose one (see `_lp_rounded_feasible`), and every
    node is pruned by the LP-dual bound from `_dual_vertices` (tighter than any single row's own
    ratio bound, since it lets rows combine). Branching order also tries values closest to the
    incumbent's own counts first, so `state[0]` converges to near-optimal almost immediately and
    prunes the rest of the tree. The last type is not branched on: its count is the smallest that
    meets every remaining row. None of this affects correctness: the recursion below still proves
    the returned value is the true minimum, by exhausting every allocation the pruning bound cannot
    rule out.
    """
    n = len(costs)
    rows = [r for r in range(len(targets)) if targets[r] > EPS]
    if not rows:
        return 0.0, (0,) * n
    for r in rows:
        if all(coeffs[r][t] <= EPS for t in range(n)):
            raise ValueError("no container type can satisfy a required row; instance is infeasible")

    vertices = _dual_vertices(rows, coeffs, costs)

    def lp_lower(remaining: Sequence[float]) -> float:
        best = 0.0
        for y in vertices:
            value = sum(y[i] * remaining[r] for i, r in enumerate(rows))
            if value > best:
                best = value
        return best

    # Feasible incumbent: the cheapest single type that alone satisfies every row...
    best_cost = math.inf
    best_alloc: tuple[int, ...] | None = None
    for t in range(n):
        if all(coeffs[r][t] > EPS for r in rows):
            count = max(math.ceil(targets[r] / coeffs[r][t] - EPS) for r in rows)
            cost = costs[t] * count
            if cost < best_cost:
                best_cost, best_alloc = cost, tuple(count if i == t else 0 for i in range(n))
    if best_alloc is None:
        # No single type covers every row alone: seed with a coarse per-type combination instead,
        # still feasible (every row is satisfiable by some type, checked above).
        best_alloc = tuple(
            max((math.ceil(targets[r] / coeffs[r][t] - EPS) for r in rows if coeffs[r][t] > EPS), default=0)
            for t in range(n)
        )
        best_cost = sum(c * v for c, v in zip(costs, best_alloc))
    # ...and an LP-rounded incumbent: solve the continuous relaxation exactly (few rows and types, so
    # enumerating its vertices is cheap), floor it, then greedily add whole containers until every row
    # is met again. With targets much larger than a single container's capacity, as here, this lands
    # within a container or two of the true integer optimum, so branch-and-bound below starts from a
    # near-optimal incumbent instead of proving optimality from a loose one. Only tightens pruning;
    # the search still proves optimality, so this heuristic's own quality never affects correctness.
    rounded_cost, rounded_alloc = _lp_rounded_feasible(costs, coeffs, targets, rows, n)
    if rounded_cost < best_cost:
        best_cost, best_alloc = rounded_cost, rounded_alloc

    state: list = [best_cost, best_alloc]
    hint = best_alloc  # the incumbent's own counts: a good guess for a fast route to the optimum

    def recurse(idx: int, remaining: list[float], partial_cost: float, alloc: list[int]) -> None:
        if partial_cost + lp_lower(remaining) >= state[0] - EPS:
            return
        if idx == n:
            if all(remaining[r] <= EPS for r in rows) and partial_cost < state[0] - EPS:
                state[0], state[1] = partial_cost, tuple(alloc)
            return
        if idx == n - 1:
            # Last type: the cheapest completion is the smallest count that meets every row, if any.
            open_rows = [r for r in rows if remaining[r] > EPS]
            if any(coeffs[r][idx] <= EPS for r in open_rows):
                return
            v = max((math.ceil(remaining[r] / coeffs[r][idx] - EPS) for r in open_rows), default=0)
            total = partial_cost + v * costs[idx]
            if total < state[0] - EPS:
                state[0], state[1] = total, tuple(alloc) + (v,)
            return
        cost_cap = math.floor((state[0] - partial_cost) / costs[idx] + EPS) if costs[idx] > EPS else 0
        if all(coeffs[r][idx] > EPS for r in rows):
            # Beyond this many units, this type alone already covers every remaining row; more of it
            # only adds cost, so it is dominated and can never be part of an optimal completion.
            cover_cap = max(
                (math.ceil(remaining[r] / coeffs[r][idx] - EPS) for r in rows if remaining[r] > EPS), default=0
            )
        else:
            cover_cap = math.inf  # this type alone can never cover every row; only the cost cap limits it
        max_v = min(cost_cap, cover_cap)
        # Try values closest to the incumbent's own count for this type first: it is usually close to
        # optimal, so this tends to tighten `state[0]` almost immediately, which prunes every other
        # branch (here and at every other level) far more aggressively than trying v = 0, 1, 2, ...
        for v in sorted(range(0, max(max_v, 0) + 1), key=lambda v: abs(v - hint[idx])):
            alloc.append(v)
            new_remaining = [remaining[r] - v * coeffs[r][idx] for r in range(len(remaining))]
            recurse(idx + 1, new_remaining, partial_cost + v * costs[idx], alloc)
            alloc.pop()

    recurse(0, list(targets), 0.0, [])
    return state[0], state[1]


def _lp_rounded_feasible(
    costs: Sequence[float], coeffs: Sequence[Sequence[float]], targets: Sequence[float], rows: list[int], n: int
) -> tuple[float, tuple[int, ...]]:
    """The continuous relaxation's exact optimum (min cost, `n[t] >= 0` real), floored to integers and
    topped up to restore feasibility. Solved the same way as `_dual_vertices`, but over the *primal*
    polytope: a vertex sets some rows to have slack (their target already exceeded) and makes the rest
    tight against exactly as many free (possibly positive) types, all others held at zero."""
    best_value = math.inf
    best_x: list[float] | None = None
    for k in range(1, len(rows) + 1):
        for row_subset in itertools.combinations(rows, k):
            for type_subset in itertools.combinations(range(n), k):
                matrix = [[coeffs[r][t] for t in type_subset] for r in row_subset]
                target_vec = [targets[r] for r in row_subset]
                solved = _solve_square(matrix, target_vec)
                if solved is None or any(v < -EPS for v in solved):
                    continue
                x = [0.0] * n
                for i, t in enumerate(type_subset):
                    x[t] = solved[i]
                if all(sum(coeffs[r][t] * x[t] for t in range(n)) >= targets[r] - EPS for r in rows):
                    value = sum(c * v for c, v in zip(costs, x))
                    if value < best_value:
                        best_value, best_x = value, x
    if best_x is None:
        alloc = [0] * n  # unreachable: feasibility of every row was checked by the caller
    else:
        alloc = [math.floor(v + EPS) for v in best_x]
    remaining = [targets[r] - sum(coeffs[r][t] * alloc[t] for t in range(n)) for r in range(len(targets))]
    _top_up(costs, coeffs, remaining, rows, alloc)
    return sum(c * v for c, v in zip(costs, alloc)), tuple(alloc)


def _top_up(
    costs: Sequence[float],
    coeffs: Sequence[Sequence[float]],
    remaining: list[float],
    rows: list[int],
    alloc: list[int],
) -> None:
    """Add whole containers, in place, until every row's remaining requirement is met: repeatedly pick
    whichever type gives the most coverage of the currently most-deficient row per unit cost."""
    n = len(alloc)
    while any(remaining[r] > EPS for r in rows):
        best_t, best_score = None, math.inf
        for t in range(n):
            contrib = max(
                (coeffs[r][t] / remaining[r] for r in rows if remaining[r] > EPS and coeffs[r][t] > EPS), default=0.0
            )
            if contrib <= EPS:
                continue
            score = costs[t] / contrib
            if score < best_score:
                best_score, best_t = score, t
        if best_t is None:
            return  # unreachable: feasibility of every row was checked by the caller
        alloc[best_t] += 1
        for r in rows:
            remaining[r] -= coeffs[r][best_t]


def _dual_vertices(
    rows: list[int], coeffs: Sequence[Sequence[float]], costs: Sequence[float]
) -> list[tuple[float, ...]]:
    """Every vertex of `{y >= 0 : sum_r y_r * coeffs[r][t] <= costs[t] for every type t}`, the feasible
    region of the LP dual of the (relaxed, continuous) covering problem.

    By weak LP duality, any feasible `y` in that region gives a valid lower bound on the true integer
    cost: for every feasible allocation `n`, `sum_t costs[t]*n[t] >= sum_t (sum_r y_r*coeffs[r][t])*n[t]
    = sum_r y_r*(sum_t coeffs[r][t]*n[t]) >= sum_r y_r*targets[r]`, since each row's coverage is at
    least its target. The tightest such bound is the vertex maximising `sum_r y_r*remaining[r]`, and
    since the region is a polytope its optimum is attained at a vertex, so checking every vertex is
    exact for the LP relaxation (not for the integer problem — this is only the pruning bound).

    A vertex sets some `y_r = 0` and makes exactly `len(rows) - (rows zeroed)` of the per-type
    constraints tight; both the rows-to-zero and the types-to-tighten are enumerated. Reused across
    every branch-and-bound node in one `_min_cost_cover` call, since it depends only on `coeffs` and
    `costs`, not on the remaining requirement.
    """
    m = len(rows)
    n = len(costs)
    vertices: list[tuple[float, ...]] = []
    for zero_count in range(m):
        for zero_rows in itertools.combinations(range(m), zero_count):
            free = [i for i in range(m) if i not in zero_rows]
            k = len(free)
            for type_subset in itertools.combinations(range(n), k):
                matrix = [[coeffs[rows[free[i]]][t] for i in range(k)] for t in type_subset]
                target_vec = [costs[t] for t in type_subset]
                solved = _solve_square(matrix, target_vec)
                if solved is None or any(v < -EPS for v in solved):
                    continue
                y = [0.0] * m
                for i, ridx in enumerate(free):
                    y[ridx] = solved[i]
                if all(
                    sum(y[ridx] * coeffs[rows[ridx]][t] for ridx in range(m)) <= costs[t] + EPS
                    for t in range(n)
                ):
                    vertices.append(tuple(y))
    return vertices


def _solve_square(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Solve a small square linear system by Gauss-Jordan elimination with partial pivoting; `None`
    when the matrix is singular."""
    k = len(matrix)
    augmented = [row[:] + [b] for row, b in zip(matrix, vector)]
    for col in range(k):
        pivot_row = max(range(col, k), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) <= 1e-12:
            return None
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        augmented[col] = [v / pivot for v in augmented[col]]
        for r in range(k):
            if r != col and augmented[r][col] != 0:
                factor = augmented[r][col]
                augmented[r] = [rv - factor * cv for rv, cv in zip(augmented[r], augmented[col])]
    return [augmented[r][k] for r in range(k)]


def bound_to_dict(bound: Bound) -> dict[str, Any]:
    return {
        "cost": bound.cost,
        "fleet": dict(bound.fleet),
        "binding": bound.binding,
        "contributing": list(bound.contributing),
        "rows": {name: {"cost": row.cost, "fleet": dict(row.fleet)} for name, row in bound.rows.items()},
    }


def bound_from_dict(data: dict[str, Any]) -> Bound:
    return Bound(
        cost=data["cost"],
        fleet=dict(data["fleet"]),
        binding=data["binding"],
        contributing=tuple(data["contributing"]),
        rows={
            name: RowBound(cost=row["cost"], fleet=dict(row["fleet"]))
            for name, row in data["rows"].items()
        },
    )
