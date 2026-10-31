"""Tests for E5's lean pool trial (engine e5-v2-lean): sparse columns hold what dense ones do and give the
same masters; the reduction before each integer master drops only dominated columns, then cuts by reduced cost,
always keeping the hint and best cover."""
from __future__ import annotations

import time
from dataclasses import replace
from functools import cache

import pytest

from src.checker import check
from src.engines.e5 import engine as e5_engine
from src.engines.e5 import master
from src.engines.e5.engine import VERSIONS, Settings, solve
from src.engines.e5.pool import Pool
from src.engines.e5.reduce import Reducer
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
LEAN = replace(VERSIONS["e5-v2"], pace=True, sparse_pool=True, reduce_master=True)


@cache
def _lot(n: int) -> tuple:
    """`random_lot(n)` and (type, placements) of every container of a few short default E5 runs on it."""
    inst = random_lot(n)
    return inst, tuple(_containers(inst))


def _containers(inst) -> list:
    out = []
    for seed in (1, 2, 3):
        sol, _ = solve(inst, P, 1e5, seed, Settings(alns_iterations=5, pricing_rounds=1))
        types = {c.k: next(t for t in inst.container_types if t.id == c.type) for c in sol.containers}
        out += [(ctype, [p for p in sol.placements if p.k == k]) for k, ctype in types.items()]
    return out


def _pools(n: int) -> tuple[Pool, Pool]:
    inst, containers = _lot(n)
    dense, sparse = Pool(inst), Pool(inst, sparse=True)
    for ctype, placements in containers:
        assert dense.add(ctype, placements, "test") == sparse.add(ctype, placements, "test")
        # Each container minus its last item too: plenty of dominated columns.
        assert dense.add(ctype, placements[:-1], "sub") == sparse.add(ctype, placements[:-1], "sub")
    return dense, sparse


def _dominates(p, q) -> bool:
    if p is q or p.type.id != q.type.id:
        return False
    held = dict(p.nonzero)
    return all(held.get(i, 0) >= a for i, a in q.nonzero)


def test_sparse_and_dense_pools_hold_the_same_columns():
    dense, sparse = _pools(6)
    assert len(dense) == len(sparse) > 0
    for a, b in zip(dense.columns, sparse.columns):
        assert not a.sparse and b.sparse
        assert (a.type, a.nonzero, a.layout, a.source, a.cost) == (b.type, b.nonzero, b.layout, b.source, b.cost)
        assert not hasattr(b, "counts")
    for p, col in enumerate(sparse.columns):
        assert sparse.index(col.key) == p


def test_the_master_on_sparse_columns_equals_the_one_on_dense_columns():
    dense, sparse = _pools(6)
    inst = dense.instance
    a, b = master.solve_lp(inst, dense.columns, sparse=True), master.solve_lp(inst, sparse.columns, sparse=True)
    assert a.value == pytest.approx(b.value) and a.duals == pytest.approx(b.duals)
    for col_a, col_b in zip(dense.columns, sparse.columns):
        assert e5_engine._reduced_cost(col_a, a.duals) == e5_engine._reduced_cost(col_b, a.duals)
    for caps in (None, {0: inst.items[0].qty + 1}):
        x = master.solve_mip(inst, dense.columns, None, 30.0, caps, sparse=True, net_of_build=True)
        y = master.solve_mip(inst, sparse.columns, None, 30.0, caps, sparse=True, net_of_build=True)
        assert (x.status, x.cost, x.counts) == (y.status, y.cost, y.counts)


def test_dominance_removes_only_dominated_columns_and_keeps_the_forced_ones():
    _, pool = _pools(6)
    cols = pool.columns
    dominated = {q for q in range(len(cols)) if any(_dominates(p, cols[q]) for p in cols)}
    assert dominated
    forced = {min(dominated), 0}
    red = Reducer(pool, 10**9).reduce(forced, None, time.monotonic() + 60.0)
    assert red.complete and red.cut == 0 and red.duals is None
    assert set(red.index) == (set(range(len(cols))) - dominated) | forced
    assert red.dominated == len(dominated - forced)


def test_a_reducer_kept_across_a_growing_pool_finds_what_a_fresh_one_does():
    inst, containers = _lot(7)
    pool = Pool(inst, sparse=True)
    reducer = Reducer(pool, 10**9)
    half = len(containers) // 2
    for ctype, placements in containers[:half]:
        pool.add(ctype, placements, "test")
    reducer.reduce(set(), None, time.monotonic() + 60.0)
    for ctype, placements in containers[half:]:
        pool.add(ctype, placements, "test")
        pool.add(ctype, placements[:-1], "sub")
    for ctype, placements in containers[:half]:
        pool.add(ctype, placements[1:], "sub")
    again = reducer.reduce(set(), None, time.monotonic() + 60.0)
    fresh = Reducer(pool, 10**9).reduce(set(), None, time.monotonic() + 60.0)
    assert again.index == fresh.index and again.dominated == fresh.dominated > 0


def test_the_cut_keeps_the_lowest_reduced_costs_and_the_forced_columns():
    _, pool = _pools(6)
    inst, cols = pool.instance, pool.columns
    duals = master.solve_lp(inst, cols, sparse=True).duals
    forced = {len(pool) - 1, len(pool) - 2}
    red = Reducer(pool, 5).reduce(forced, duals, time.monotonic() + 60.0)
    assert red.duals == "lp" and red.kept_by_reduced_cost == 5 and red.cut > 0
    assert len(red.index) <= 5 + len(forced) and forced <= set(red.index)
    rc = {p: e5_engine._reduced_cost(cols[p], duals) for p in range(len(pool))}
    undominated = {q for q in range(len(cols)) if not any(_dominates(p, cols[q]) for p in cols)}
    chosen = set(red.index) - forced
    assert chosen <= undominated and len(chosen) == 5
    assert max(rc[p] for p in chosen) <= min(rc[p] for p in undominated - set(red.index)) + 1e-9


def test_a_master_on_a_cut_pool_keeps_its_hint_and_maps_back_to_the_pool():
    _, pool = _pools(6)
    inst = pool.instance
    sol, _ = solve(inst, P, 1e5, 4, Settings(alns_iterations=5, pricing_rounds=1))
    hint: dict[int, int] = {}
    for c in sol.containers:
        ctype = next(t for t in inst.container_types if t.id == c.type)
        p = pool.add(ctype, [x for x in sol.placements if x.k == c.k], "hint")
        hint[p] = hint.get(p, 0) + 1
    duals = master.solve_lp(inst, pool.columns, sparse=True).duals
    now = time.monotonic()
    res, cand, diag = e5_engine._master(inst, P, pool, hint, 5.0, now + 5.0, "mip-test", [], now + 5.0, 0, True,
                                        Reducer(pool, 3), duals, set())
    red = diag["reduce"]
    assert red["after"] == diag["columns"] <= 3 + len(hint) and red["before"] == len(pool)
    assert res.cost is not None and res.cost <= e5_engine._cover_cost(pool, hint) + 1e-9
    assert all(0 <= p < len(pool) for p in res.counts)
    assert res.cost == pytest.approx(e5_engine._cover_cost(pool, res.counts))
    if cand is not None:
        assert check(inst, cand.solution, P).ok


def test_e5_v2_lean_runs_on_a_small_cap_and_is_no_worse_than_the_incumbent():
    inst = random_lot(6)
    sol, diag = solve(inst, P, 6.0, 1, replace(LEAN, master_columns=5))
    assert check(inst, sol, P).ok
    assert diag["cost"] <= diag["incumbent_cost"] + 1e-9
    red = diag["pre_pricing"]["reduce"]
    assert red["after"] <= 5 + red["forced"] and red["before"] == diag["pre_lp"]["columns"]


def test_a_sparse_pool_needs_pace():
    with pytest.raises(ValueError):
        solve(random_lot(6), P, 4.0, 1, replace(LEAN, pace=False))
