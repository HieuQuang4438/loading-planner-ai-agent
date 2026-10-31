"""Tests for E5's pacing trial (engine e5-v2-pace): the sparse build gives the same LP and master, the
build time is reported apart from the solve, and a master that would not fit in the time left is skipped."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.checker import check
from src.engines.e5 import engine as e5_engine
from src.engines.e5 import master
from src.engines.e5.engine import VERSIONS, Settings, solve
from src.engines.e5.pool import Pool
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
PACE = replace(VERSIONS["e5-v2"], pace=True)


def _pool(inst) -> Pool:
    """The containers of a few short default E5 runs."""
    pool = Pool(inst)
    for seed in (1, 2, 3):
        sol, _ = solve(inst, P, 1e5, seed, Settings(alns_iterations=5, pricing_rounds=1))
        types = {c.k: next(t for t in inst.container_types if t.id == c.type) for c in sol.containers}
        for k, ctype in types.items():
            pool.add(ctype, [p for p in sol.placements if p.k == k], "test")
    return pool


def test_column_nonzero_lists_the_lines_it_holds():
    inst = random_lot(6)
    for col in _pool(inst).columns:
        assert col.nonzero == tuple((i, a) for i, a in enumerate(col.counts) if a)


def test_the_sparse_build_gives_the_same_lp_and_master():
    inst = random_lot(6)
    pool = _pool(inst)
    dense, sparse = master.solve_lp(inst, pool.columns), master.solve_lp(inst, pool.columns, sparse=True)
    assert dense.value == pytest.approx(sparse.value) and dense.duals == pytest.approx(sparse.duals)
    caps = {0: inst.items[0].qty + 1}
    for c in (None, caps):
        a = master.solve_mip(inst, pool.columns, None, 30.0, c)
        b = master.solve_mip(inst, pool.columns, None, 30.0, c, sparse=True, net_of_build=True)
        assert (a.status, a.cost, a.counts) == (b.status, b.cost, b.counts)
        assert 0.0 <= b.build <= b.time


def test_an_lp_with_no_time_left_is_not_solved():
    inst = random_lot(6)
    lp = master.solve_lp(inst, _pool(inst).columns, time_limit=0.0, sparse=True)
    assert lp.value is None and lp.status == "TIME"


# Capped by iterations and pricing rounds, not the clock: under load a 4 s run may start no pricing round.
CAPPED_V2 = replace(VERSIONS["e5-v2"], alns_iterations=5, pricing_rounds=1)


def test_every_version_reports_build_and_solve_time():
    _, diag = solve(random_lot(6), P, 1e5, 1, CAPPED_V2)
    for step in ("pre_pricing", "final"):
        assert diag[step]["build"] + diag[step]["solve"] == pytest.approx(diag[step]["time"], abs=2e-3)
    assert len(diag["pricing"]["lp_build"]) == len(diag["pricing"]["lp_solve"]) >= 1


def test_a_master_too_slow_to_build_is_skipped_and_the_incumbent_kept(monkeypatch):
    # Every master reports a 100 s build: pricing starts no round, the final master is skipped, no reuse round.
    real = master.solve_mip

    def slow(*args, **kw):
        return replace(real(*args, **kw), build=100.0)

    monkeypatch.setattr(e5_engine.master, "solve_mip", slow)
    inst = random_lot(6)
    sol, diag = solve(inst, P, 4.0, 1, PACE)
    assert check(inst, sol, P).ok
    assert diag["pricing"]["stop"] in ("pace", "time") and diag["pricing"]["rounds"] == 0
    assert diag["final"] == {"skipped": "pace", "reserve": 101.0}
    assert "reuse" not in diag
    assert diag["cost"] <= diag["incumbent_cost"] + 1e-9


def test_without_pace_the_same_slow_build_changes_nothing_but_the_numbers(monkeypatch):
    real = master.solve_mip
    monkeypatch.setattr(e5_engine.master, "solve_mip", lambda *a, **kw: replace(real(*a, **kw), build=100.0))
    _, diag = solve(random_lot(6), P, 1e5, 1, CAPPED_V2)
    assert diag["pricing"]["rounds"] >= 1 and "skipped" not in diag["final"]
