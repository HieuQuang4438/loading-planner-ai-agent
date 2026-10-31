"""E5's master problem over the column pool:

    min  sum_p c_t(p) x_p     s.t.  sum_p a_ip x_p >= qty_i  (every line i),  x_p >= 0

LP relaxation by GLOP (its duals drive pricing), integer version by SCIP; both on one thread.
Covering with `>=` keeps the duals nonnegative and the integer problem feasible whenever the pool
covers each line at all; surplus items are removed afterwards (`src.engines.e5.trim`).

Columns come from a heuristic core, so neither the LP value nor SCIP's best bound is a lower bound
on the instance's cost: they bound only what these columns can do.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from src.engines.e5.pool import AnyColumn
from src.model import Instance


@dataclass
class LPResult:
    value: float | None  # None: no optimal LP (pool does not cover some line, or the time limit hit)
    duals: list[float] = field(default_factory=list)
    time: float = 0.0  # build + solve
    build: float = 0.0  # of `time`, building the model
    status: str = "OPTIMAL"  # OPTIMAL, TIME (limit hit, or none left after the build), NOT_SOLVED


@dataclass
class MIPResult:
    status: str  # OPTIMAL, FEASIBLE, NOT_SOLVED
    cost: float | None
    bound: float | None
    counts: dict[int, int] = field(default_factory=dict)  # column index -> copies
    time: float = 0.0  # build + solve
    build: float = 0.0  # of `time`, building the model


def _cap(column: AnyColumn, qty: list[int]) -> int:
    """Most copies of a column any minimal cover uses: enough to cover its scarcest-needed line."""
    if column.sparse:
        return max(math.ceil(qty[i] / a) for i, a in column.nonzero)
    return max(math.ceil(q / a) for q, a in zip(qty, column.counts) if a)


def solve_lp(
    instance: Instance, columns: list[AnyColumn], time_limit: float | None = None, sparse: bool = False
) -> LPResult:
    """`time_limit` (engine e5-v2-pace): seconds for build and solve together; None: no limit.
    `sparse`: build from each column's nonzero lines; the model is the same. A `SparseColumn` needs `sparse`."""
    from ortools.linear_solver import pywraplp

    t0 = time.monotonic()
    lp = pywraplp.Solver.CreateSolver("GLOP")
    lp.SetNumThreads(1)
    qty = [line.qty for line in instance.items]
    rows = [lp.Constraint(float(q), lp.infinity()) for q in qty]
    obj = lp.Objective()
    for col in columns:
        v = lp.NumVar(0.0, lp.infinity(), "")
        obj.SetCoefficient(v, col.cost)
        for i, a in (col.nonzero if sparse else enumerate(col.counts)):
            if a:
                rows[i].SetCoefficient(v, float(a))
    obj.SetMinimization()
    build = time.monotonic() - t0
    if time_limit is not None:
        left = time_limit - build
        if left <= 0.0:
            return LPResult(None, [], build, build, "TIME")
        lp.SetTimeLimit(max(int(left * 1000), 1))
    status = lp.Solve()
    elapsed = time.monotonic() - t0
    if status != pywraplp.Solver.OPTIMAL:
        timed_out = time_limit is not None and elapsed >= time_limit
        return LPResult(None, [], elapsed, build, "TIME" if timed_out else "NOT_SOLVED")
    return LPResult(obj.Value(), [max(r.dual_value(), 0.0) for r in rows], elapsed, build)


def solve_mip(
    instance: Instance, columns: list[AnyColumn], hint: dict[int, int] | None, time_limit: float,
    caps: dict[int, int] | None = None, sparse: bool = False, net_of_build: bool = False,
) -> MIPResult:
    """`caps`: line index -> most items of that line the cover may hold (re-solve after a
    failed trim); a capped line is covered within [qty, cap]. (engine e5-v2-pace): `sparse` builds
    the same model from each column's nonzero lines with `SetCoefficient`, not Python expressions;
    `net_of_build` takes the build time off `time_limit`, so SCIP's limit is what is left of it."""
    from ortools.linear_solver import pywraplp

    t0 = time.monotonic()
    mip = pywraplp.Solver.CreateSolver("SCIP")
    mip.SetNumThreads(1)
    qty = [line.qty for line in instance.items]
    xs = [mip.IntVar(0.0, float(_cap(col, qty)), "") for col in columns]
    if sparse:
        rows, capped = [], {}
        for i, q in enumerate(qty):  # the dense build's constraint order: each line's cover, then its cap
            rows.append(mip.Constraint(float(q), mip.infinity()))
            if caps and i in caps:
                capped[i] = mip.Constraint(-mip.infinity(), float(caps[i]))
        obj = mip.Objective()
        for x, col in zip(xs, columns):
            obj.SetCoefficient(x, col.cost)
            for i, a in col.nonzero:
                rows[i].SetCoefficient(x, a)
                if i in capped:
                    capped[i].SetCoefficient(x, a)
        obj.SetMinimization()
    else:
        for i, q in enumerate(qty):
            terms = [(x, col.counts[i]) for x, col in zip(xs, columns) if col.counts[i]]
            mip.Add(sum(a * x for x, a in terms) >= q)
            if caps and i in caps:
                mip.Add(sum(a * x for x, a in terms) <= caps[i])
        mip.Minimize(sum(col.cost * x for x, col in zip(xs, columns)))
    if hint:
        mip.SetHint(xs, [float(hint.get(p, 0)) for p in range(len(columns))])
    build = time.monotonic() - t0
    limit = time_limit - build if net_of_build else time_limit
    mip.SetTimeLimit(max(int(limit * 1000), 100))
    status = mip.Solve()
    elapsed = time.monotonic() - t0
    names = {pywraplp.Solver.OPTIMAL: "OPTIMAL", pywraplp.Solver.FEASIBLE: "FEASIBLE"}
    if status not in names:
        return MIPResult("NOT_SOLVED", None, None, {}, elapsed, build)
    counts = {p: int(round(x.solution_value())) for p, x in enumerate(xs)}
    counts = {p: n for p, n in counts.items() if n}
    cost = round(sum(columns[p].cost * n for p, n in counts.items()), 9)
    bound = mip.Objective().BestBound()
    bound = round(bound, 9) if math.isfinite(bound) and abs(bound) < 1e12 else None
    return MIPResult(names[status], cost, bound, counts, elapsed, build)
