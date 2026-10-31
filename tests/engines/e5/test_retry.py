"""Tests for E5's master re-solve after a failed trim (engine e5-mono): the failed line's cover
is capped at qty + the surplus trim removed, the master is solved again, at most `retries` times."""
from __future__ import annotations

import time

from src.engines.e5 import engine as e5_engine
from src.engines.e5 import master
from src.engines.e5.engine import Settings, solve
from src.engines.e5.trim import TrimFailed
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)


def _spy(monkeypatch, fails: int):
    """Trim fails `fails` times on line 0 (surplus 3, 1 left), then works; records each master's caps."""
    calls = []
    real_trim, real_mip = e5_engine.trim, master.solve_mip

    def fake_trim(instance, boxes, repack=None):
        if len(calls) <= fails:
            raise TrimFailed("stuck", instance.items[0].id, 3, 1)
        return real_trim(instance, boxes, repack)

    def mip(instance, columns, hint, limit, caps=None, **kw):
        calls.append(dict(caps or {}))
        return real_mip(instance, columns, hint, limit, caps, **kw)

    monkeypatch.setattr(e5_engine, "trim", fake_trim)
    monkeypatch.setattr(e5_engine.master, "solve_mip", mip)
    return calls


def test_a_failed_trim_caps_the_line_and_solves_again(monkeypatch):
    inst = random_lot(2)
    pool = _pool(inst)
    calls = _spy(monkeypatch, fails=1)
    _, _, diag = e5_engine._master(inst, P, pool, {}, 5.0, time.monotonic() + 30, "mip-final", [], 0.0, 5)
    assert calls == [{}, {0: inst.items[0].qty + 2}]  # qty + surplus 3 - left 1
    assert diag["retries"] == 1 and "trim_failed" not in diag
    assert diag["caps"] == {inst.items[0].id: inst.items[0].qty + 2}


def test_retries_stop_at_the_limit(monkeypatch):
    inst = random_lot(2)
    pool = _pool(inst)
    calls = _spy(monkeypatch, fails=99)
    _, cand, diag = e5_engine._master(inst, P, pool, {}, 5.0, time.monotonic() + 30, "mip-final", [], 0.0, 2)
    assert len(calls) == 3 and cand is None and diag["retries"] == 2 and "trim_failed" in diag


def test_no_retry_without_the_setting(monkeypatch):
    calls = _spy(monkeypatch, fails=99)
    solve(random_lot(2), P, 1e5, 1, Settings(alns_iterations=5, pricing_rounds=1))
    assert all(c == {} for c in calls)


def _pool(inst):
    """A pool holding the containers of a short default E5 run."""
    from src.engines.e5.pool import Pool

    pool = Pool(inst)
    sol, _ = solve(inst, P, 1e5, 1, Settings(alns_iterations=5, pricing_rounds=1))
    types = {c.k: next(t for t in inst.container_types if t.id == c.type) for c in sol.containers}
    for k, ctype in types.items():
        pool.add(ctype, [p for p in sol.placements if p.k == k], "test")
    return pool
