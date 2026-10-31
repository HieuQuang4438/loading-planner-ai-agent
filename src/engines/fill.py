"""E5-fill: mode B (docs/product/brief.md §2.2; ADR-0002): a fixed set of containers, as many pieces as fit, by the
user's priority order. E5's idea with the objective turned round: E1's and E2's cores lay out containers (columns);
an integer master picks at most the available number of each type so that, lexicographically by priority, the most
pieces of each line go in.

    max  lexicographic (y_1, ..., y_n)   s.t.  y_i = sum_p a_ip x_p <= qty_i,  sum_{p of type t} x_p <= n_t

With partial lines off, y_i is 0 or qty_i. The master packs (`<= qty`), it does not cover, so no surplus is ever
trimmed and each chosen layout is used as the core made it. The baseline's containers (`sequential`) are always in
the pool and handed to the master as its hint, so the result never holds fewer pieces of the first line on which they
differ. Columns come from the cores only: "most" is over the layouts found, not a proven optimum.

The run's settings ride in `instance.meta["fill"]`: {"fleet": {type id: count}, "priority": [line ids], "partial":
bool}. The returned solution places a subset of the lot; the caller checks it against the lot of placed pieces
(`placed_instance`), so the checker's rules stay as they are.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from src.engines import e1, e2
from src.engines.base import Hints, Piece, expand_pieces
from src.engines.e5.pool import Pool
from src.model import ContainerType, Instance, Params, Placement, Solution, UsedContainer, item_id, line_of

META_KEY = "fill"
LP_SHARE = 0.6  # of the time limit, generating columns; the rest for the masters
WEIGHT_CAP = 1e9  # largest lexicographic weight one master holds: past it, the lines go to the next master
PRICING_BASE = 4.0  # LP value of a line one place higher in priority, per m³: steers pricing only

PackOne = Callable[[list[Piece], ContainerType, Params, random.Random, Hints | None], list[Placement]]


@dataclass(frozen=True)
class FillSpec:
    fleet: tuple[tuple[str, int], ...]  # (type id, count) in the lot's type order
    priority: tuple[str, ...]  # every line id, first = most wanted
    partial: bool

    @property
    def size(self) -> int:
        return sum(n for _, n in self.fleet)


def spec_of(instance: Instance) -> FillSpec:
    """The run's fleet, priority and partial flag; ValueError when they do not fit the lot."""
    raw = instance.meta.get(META_KEY)
    if not isinstance(raw, dict):
        raise ValueError("mode B needs instance.meta['fill']")
    fleet = raw.get("fleet") or {}
    types = {t.id for t in instance.container_types}
    if set(fleet) - types or any(not isinstance(n, int) or n < 0 for n in fleet.values()):
        raise ValueError("fleet: counts must be whole numbers >= 0 of the lot's container types")
    ordered = tuple((t.id, fleet.get(t.id, 0)) for t in instance.container_types if fleet.get(t.id, 0))
    lines = [line.id for line in instance.items]
    priority = tuple(raw.get("priority") or lines)
    if sorted(priority) != sorted(lines):
        raise ValueError("priority must name every line once")
    spec = FillSpec(ordered, priority, bool(raw.get("partial", True)))
    if spec.size == 0:
        raise ValueError("fleet is empty")
    return spec


def cores(orient: bool) -> list[tuple[str, PackOne]]:
    if orient:
        return [("e1", e1.pack_one_orient_dense), ("e2", e2.pack_one_orient)]
    return [("e1", e1.pack_one), ("e2", e2.pack_one)]


def priority_hints(order: list[str]) -> Hints:
    return Hints(order=tuple((line, float(r)) for r, line in enumerate(order)))


def fill_pass(instance: Instance, spec: FillSpec, params: Params, pack_one: PackOne, counts: dict[str, int],
              order: list[str]) -> list[tuple[ContainerType, list[Placement]]]:
    """Fill the fleet's containers one after another (type order) with `counts` pieces per line, offered in `order`;
    a piece that fits nowhere is left out. Placements carry item ids numbered per line from 1."""
    pieces = {p.item: p for p in expand_pieces(instance)}
    rank = {line: r for r, line in enumerate(order)}
    left = sorted((item_id(line, n) for line, c in counts.items() for n in range(1, c + 1)),
                  key=lambda i: (rank[line_of(i)], int(i.rsplit("#", 1)[1])))
    hints = priority_hints(order)
    out = []
    for type_id, n in spec.fleet:
        ctype = instance.container_type(type_id)
        assert ctype is not None
        for _ in range(n):
            if not left:
                return out
            placed = pack_one([pieces[i] for i in left], ctype, params, random.Random(0), hints)
            taken = {p.item for p in placed}
            left = [i for i in left if i not in taken]
            out.append((ctype, placed))
    return out


def placed_counts(containers: list[tuple[ContainerType, list[Placement]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, placed in containers:
        for p in placed:
            counts[line_of(p.item)] = counts.get(line_of(p.item), 0) + 1
    return counts


def sequential(instance: Instance, spec: FillSpec, params: Params, pack_one: PackOne) -> list[tuple[ContainerType, list[Placement]]]:
    """The baseline a person gets: pieces offered in priority order, container after container. With partial lines
    off, a line is kept only when all of it goes in together with the lines kept before it."""
    order = list(spec.priority)
    qty = {line.id: line.qty for line in instance.items}
    if spec.partial:
        return fill_pass(instance, spec, params, pack_one, qty, order)
    kept: dict[str, int] = {}
    best: list[tuple[ContainerType, list[Placement]]] = []
    for line in order:
        trial = {**kept, line: qty[line]}
        packed = fill_pass(instance, spec, params, pack_one, trial, order)
        if placed_counts(packed) == trial:
            kept, best = trial, packed
    return best


def lex_chunks(order: list[str], qty: dict[str, int]) -> list[list[str]]:
    """Lines in priority order, cut where the lexicographic weights of one master would pass `WEIGHT_CAP`."""
    chunks: list[list[str]] = [[]]
    size = 1.0
    for line in order:
        if chunks[-1] and size * (qty[line] + 1) > WEIGHT_CAP:
            chunks.append([])
            size = 1.0
        chunks[-1].append(line)
        size *= qty[line] + 1
    return chunks


def solve(instance: Instance, params: Params, time_limit: float, seed: int, orient: bool = False
          ) -> tuple[Solution, dict[str, Any]]:
    t0 = time.monotonic()
    spec = spec_of(instance)
    rng = random.Random(seed)
    pool = Pool(instance)
    qty = {line.id: line.qty for line in instance.items}
    order = list(spec.priority)
    index = pool.line_index
    types = {t.id: t for t in instance.container_types}
    calls = 0

    def file(containers: list[tuple[ContainerType, list[Placement]]], source: str) -> list[int]:
        cols = [pool.add(ctype, placed, source) for ctype, placed in containers]
        return [c for c in cols if c is not None]

    baseline_cols: list[int] = []
    for name, core in cores(orient):
        cols = file(sequential(instance, spec, params, core), f"baseline-{name}")
        calls += len(cols)
        if name == "e1":
            baseline_cols = cols
    deadline = t0 + LP_SHARE * time_limit
    vol = {line.id: line.volume for line in instance.items}
    value = {line: vol[line] * PRICING_BASE ** (len(order) - 1 - r) for r, line in enumerate(order)}
    rounds = 0
    while time.monotonic() < deadline:
        rounds += 1
        duals = _lp_duals(instance, spec, pool, value)
        core_name, core = cores(orient)[rounds % 2]
        for type_id, _ in spec.fleet:
            if time.monotonic() >= deadline:
                break
            ctype = types[type_id]
            if duals is not None and rounds % 3 != 0:  # pricing: lines worth most per m³ after the duals go first
                gain = {line: (value[line] - duals[index[line]]) / vol[line] for line in order}
                lines = sorted((line for line in order if gain[line] > 1e-9), key=lambda line: -gain[line])
                counts = {line: qty[line] for line in lines}
            else:  # a random priority prefix, shuffled, with random amounts
                lines = order[:rng.randint(1, len(order))]
                rng.shuffle(lines)
                counts = {line: max(1, round(qty[line] * rng.uniform(0.2, 1.0))) for line in lines}
            if not lines:
                continue
            single = replace(spec, fleet=((type_id, 1),))
            file(fill_pass(instance, single, params, core, counts, lines), f"{'pricing' if duals else 'random'}-{core_name}")
            calls += 1
    hint = {c: baseline_cols.count(c) for c in set(baseline_cols)}
    counts, masters = _lex_master(instance, spec, pool, order, qty, hint, t0 + time_limit)
    solution = _solution(instance, params, pool, counts, spec)
    placed = placed_instance(instance, solution)
    held = {line.id: line.qty for line in placed.items}
    return solution, {
        "engine": "e5-fill-orient" if orient else "e5-fill",
        "fleet": dict(spec.fleet), "priority": order, "partial": spec.partial,
        "placed": {line: held.get(line, 0) for line in order},
        "pool": len(pool), "rounds": rounds, "core_calls": calls, "masters": masters,
        "time": round(time.monotonic() - t0, 2),
    }


def solve_orient(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    return solve(instance, params, time_limit, seed, orient=True)


def _lp_duals(instance: Instance, spec: FillSpec, pool: Pool, value: dict[str, float]
              ) -> list[float] | None:
    """LP of the packing master with `value` per piece: the duals of its line rows (`<= qty`)."""
    from ortools.linear_solver import pywraplp

    lp = pywraplp.Solver.CreateSolver("GLOP")
    lp.SetNumThreads(1)
    lines = [line.id for line in instance.items]
    rows = [lp.Constraint(-lp.infinity(), float(line.qty)) for line in instance.items]
    fleet = dict(spec.fleet)
    trows = {t: lp.Constraint(-lp.infinity(), float(n)) for t, n in fleet.items()}
    obj = lp.Objective()
    for col in pool.columns:
        if col.type.id not in fleet:
            continue
        x = lp.NumVar(0.0, lp.infinity(), "")
        obj.SetCoefficient(x, sum(value[lines[i]] * a for i, a in col.nonzero))
        for i, a in col.nonzero:
            rows[i].SetCoefficient(x, float(a))
        trows[col.type.id].SetCoefficient(x, 1.0)
    obj.SetMaximization()
    if lp.Solve() != pywraplp.Solver.OPTIMAL:
        return None
    return [max(r.dual_value(), 0.0) for r in rows]


def _lex_master(instance: Instance, spec: FillSpec, pool: Pool, order: list[str], qty: dict[str, int],
                hint: dict[int, int], end: float) -> tuple[dict[int, int], list[dict[str, Any]]]:
    """Copies per column: one SCIP master per chunk of lines (`lex_chunks`), each keeping what the masters before it
    reached. A master that finds nothing better keeps the hint."""
    from ortools.linear_solver import pywraplp

    index = pool.line_index
    fleet = dict(spec.fleet)
    cols = [c for c, col in enumerate(pool.columns) if col.type.id in fleet]
    chunks = lex_chunks(order, qty)
    fixed: dict[str, int] = {}
    best = dict(hint)
    log = []
    for n, chunk in enumerate(chunks):
        mip = pywraplp.Solver.CreateSolver("SCIP")
        mip.SetNumThreads(1)
        xs = {c: mip.IntVar(0.0, float(fleet[pool.columns[c].type.id]), "") for c in cols}
        held = {line: [] for line in order}
        for c in cols:
            for i, a in pool.columns[c].nonzero:
                held[instance.items[i].id].append((xs[c], a))
        y = {}
        for line in order:
            expr = sum(a * x for x, a in held[line]) if held[line] else 0
            mip.Add(expr <= qty[line])
            if not spec.partial:
                z = mip.BoolVar("")
                mip.Add(expr == qty[line] * z)
            if line in fixed:
                mip.Add(expr >= fixed[line])
            y[line] = expr
        for t, cap in fleet.items():
            mip.Add(sum(xs[c] for c in cols if pool.columns[c].type.id == t) <= cap)
        weight, objective = 1.0, 0
        for line in reversed(chunk):
            objective += weight * y[line]
            weight *= qty[line] + 1
        mip.Maximize(objective)
        mip.SetHint([xs[c] for c in cols], [float(best.get(c, 0)) for c in cols])
        left = (end - time.monotonic()) / (len(chunks) - n)
        mip.SetTimeLimit(max(int(left * 1000), 100))
        status = mip.Solve()
        if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            found = {c: int(round(xs[c].solution_value())) for c in cols}
            found = {c: k for c, k in found.items() if k}
            if _lex_key(pool, found, order, index) >= _lex_key(pool, best, order, index):
                best = found
        got = _held(pool, best, index, order)
        for line in chunk:
            fixed[line] = got[line]
        log.append({"lines": len(chunk), "status": {0: "OPTIMAL", 1: "FEASIBLE"}.get(status, "NOT_SOLVED")})
    return best, log


def _held(pool: Pool, counts: dict[int, int], index: dict[str, int], order: list[str]) -> dict[str, int]:
    out = dict.fromkeys(order, 0)
    names = {i: line for line, i in index.items()}
    for c, k in counts.items():
        for i, a in pool.columns[c].nonzero:
            out[names[i]] += a * k
    return out


def _lex_key(pool: Pool, counts: dict[int, int], order: list[str], index: dict[str, int]) -> tuple[int, ...]:
    held = _held(pool, counts, index, order)
    return tuple(held[line] for line in order)


def _solution(instance: Instance, params: Params, pool: Pool, counts: dict[int, int], spec: FillSpec) -> Solution:
    """Containers in the fleet's type order; items numbered per line from 1."""
    rank = {t: r for r, (t, _) in enumerate(spec.fleet)}
    chosen = sorted((c for c, k in counts.items() for _ in range(k)), key=lambda c: (rank[pool.columns[c].type.id], c))
    numbers: dict[str, int] = {}
    containers, placements = [], []
    for k, c in enumerate(chosen, 1):
        col = pool.columns[c]
        containers.append(UsedContainer(k, col.type.id))
        for line, x, y, z, o in col.layout:
            numbers[line] = numbers.get(line, 0) + 1
            placements.append(Placement(item_id(line, numbers[line]), k, x, y, z, o))
    return Solution(instance.name, params, containers, placements)


def placed_instance(instance: Instance, solution: Solution) -> Instance:
    """The lot of the pieces `solution` places: each line's `qty` = its placed count, lines with none dropped. A mode B
    solution is checked against this lot, by the same checker."""
    placed: dict[str, int] = {}
    for p in solution.placements:
        placed[line_of(p.item)] = placed.get(line_of(p.item), 0) + 1
    lines = tuple(replace(line, qty=placed[line.id]) for line in instance.items if placed.get(line.id))
    return replace(instance, items=lines)


def fleet_excess(instance: Instance, solution: Solution) -> list[str]:
    """Container types a mode B solution opens more of than the fleet has."""
    fleet = dict(spec_of(instance).fleet)
    used: dict[str, int] = {}
    for c in solution.containers:
        used[c.type] = used.get(c.type, 0) + 1
    return [t for t, n in used.items() if n > fleet.get(t, 0)]


__all__ = ["solve", "solve_orient", "spec_of", "sequential", "placed_instance", "fleet_excess", "META_KEY",
           "FillSpec", "lex_chunks"]
