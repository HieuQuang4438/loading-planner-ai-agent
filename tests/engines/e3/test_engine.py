"""Tests for E3: every solution passes the independent checker and
is never worse than the initial E1/E2 solve; a seed with a generation cap gives one result; the
search stops at the lower bound and at the time limit; diagnostics carry the run figures."""
from __future__ import annotations

import time

import pytest

from src.checker import check
from src.engines.e3 import solve
from src.engines.e3.engine import slots_for
from src.engines.e3.search import Settings, population_size
from src.formats import solution_to_dict
from src.model import ContainerType, Params
from tests.builders import instance, line, random_lot

P = Params(delta=0.05, alpha=0.8)
CAPPED = Settings(max_generations=5, pop_min=10, pop_cap=10)


def test_population_size_is_clamped():
    s = Settings(pop_factor=1.0, pop_min=20, pop_cap=100)
    assert population_size(5, s) == 20
    assert population_size(64, s) == 64
    assert population_size(900, s) == 100


def test_slots_leave_room_beyond_the_incumbent():
    assert slots_for(1) == 3 and slots_for(10) == 15


@pytest.mark.parametrize("seed", [2, 4, 6, 8])
def test_e1_core_solutions_pass_the_checker(seed):
    inst = random_lot(seed)
    sol, diag = solve(inst, P, 1e6, 1, "e1", CAPPED)
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert result.cost == pytest.approx(diag["cost"])
    assert diag["generations"] == 5 and diag["stop"] == "generations"
    assert diag["decodes"] == 10 + 5 * (10 - 2)  # initial population, then all but the 2 elites


def test_e2_core_solution_passes_the_checker():
    inst = random_lot(8)
    sol, diag = solve(inst, P, 1e6, 1, "e2", Settings(max_generations=1, pop_min=6, pop_cap=6))
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert diag["cost"] <= diag["initial_cost"]


@pytest.mark.parametrize("seed", [1, 3, 5])
def test_never_worse_than_the_initial_solution(seed):
    _, diag = solve(random_lot(seed), P, 1e6, 1, "e1", CAPPED)
    assert (diag["cost"], diag["emptiest_fill"]) <= (diag["initial_cost"], diag["emptiest_fill_initial"])


def test_same_seed_same_result():
    inst = random_lot(6)
    a, _ = solve(inst, P, 1e6, 7, "e1", CAPPED)
    b, _ = solve(inst, P, 1e6, 7, "e1", CAPPED)
    assert solution_to_dict(a) == solution_to_dict(b)


def test_stops_at_the_lower_bound():
    box = ContainerType(id="B", L=2.2, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
    inst = instance(line("A", qty=2), types=(box,))
    sol, diag = solve(inst, P, 60.0, 1, "e1")
    assert check(inst, sol, P).ok
    assert diag["stop"] == "bound" and diag["decodes"] == 0 and diag["cost"] == diag["bound"] == 1.0


def test_respects_the_time_limit():
    inst = random_lot(1)
    start = time.monotonic()
    sol, diag = solve(inst, P, 2.0, 1, "e1")
    assert time.monotonic() - start < 2.0 * 1.05
    assert diag["stop"] == "time" and check(inst, sol, P).ok


def test_partial_restart_after_stalled_generations():
    _, diag = solve(random_lot(3), P, 1e6, 1, "e1", Settings(max_generations=12, pop_min=8, pop_cap=8, restart_after=3))
    assert diag["restarts"] >= 1


def test_diagnostics_report_counts_and_timing():
    _, diag = solve(random_lot(2), P, 1e6, 1, "e1", CAPPED)
    for field in ("decodes", "pack_one_calls", "cache_hits", "generations", "restarts", "best_found_time"):
        assert field in diag
    assert diag["time_initial"] <= diag["best_found_time"] <= diag["time_total"]
    assert diag["pack_one_calls"] > 0 and diag["population"] == 10
    assert diag["chromosome_length"] == 2 * 6 + diag["slots"]
