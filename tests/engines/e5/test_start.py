"""Tests for E5 continuing from an earlier solution: a valid `start` is never beaten by the result, an
invalid one is ignored, and without one nothing changes."""
from __future__ import annotations

import dataclasses

import src.engines  # noqa: F401 - registers the engines
from src.checker import check
from src.engines import base, e1
from src.engines.e5.engine import VERSIONS, Settings, solve
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
FAST = dataclasses.replace(VERSIONS["e5-v2"], alns_iterations=30)


def cost(inst, sol) -> float:
    return sum(inst.container_type(c.type).cost for c in sol.containers)


def test_a_valid_start_is_used_and_the_result_costs_no_more():
    inst = random_lot(6)
    start, _ = e1.solve(inst, P, 3.0, 1)
    sol, diag = solve(inst, P, 6.0, 1, FAST, start=start)
    assert diag["start"] == "used"
    assert check(inst, sol, P).ok
    assert cost(inst, sol) <= cost(inst, start) + 1e-9


def test_a_start_nothing_beats_comes_back_as_it_was():
    inst = random_lot(6)
    first, _ = solve(inst, P, 4.0, 1, FAST)
    again, diag = solve(inst, P, 4.0, 1, FAST, start=first)
    assert check(inst, again, P).ok
    assert cost(inst, again) <= cost(inst, first) + 1e-9
    if cost(inst, again) >= cost(inst, first) - 1e-9:
        assert again == first and diag["source"] == "start"


def test_an_invalid_start_is_ignored_and_recorded():
    inst = random_lot(6)
    good, _ = e1.solve(inst, P, 3.0, 1)
    first, second = good.placements[0], good.placements[1]
    clash = dataclasses.replace(good, placements=[dataclasses.replace(first, k=second.k, x=second.x, y=second.y,
                                                                     z=second.z), *good.placements[1:]])
    assert not check(inst, clash, P).ok
    sol, diag = solve(inst, P, 4.0, 1, FAST, start=clash)
    assert diag["start"] == "invalid"
    assert check(inst, sol, P).ok


def test_a_start_of_another_lot_is_invalid():
    other, _ = e1.solve(random_lot(3), P, 3.0, 1)
    sol, diag = solve(random_lot(6), P, 4.0, 1, FAST, start=other)
    assert diag["start"] == "invalid" and check(random_lot(6), sol, P).ok


def test_without_a_start_the_diagnostics_have_no_start_key():
    _, diag = solve(random_lot(6), P, 3.0, 1, Settings(alns_iterations=10))
    assert "start" not in diag


def test_only_the_e5_versions_take_a_start():
    taking = {"e5", "e5-v1", "e5-v2", "e5-v3", "e5-orient", "e5-orient-v1", "e5-orient-v2", "e5-orient-v3",
              "e5-v3-stall", "e5-orient-v3-stall", "e5-v4", "e5-orient-v4"}
    for name in base.names():
        assert base.accepts_start(name) == (name in taking), name
    assert not base.accepts_start("e5-mono") and not base.accepts_start("e1-dense")
