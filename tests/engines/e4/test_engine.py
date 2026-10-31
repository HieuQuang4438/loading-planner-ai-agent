"""Tests for E4: every solution passes the independent checker and
is never worse than the initial E1/E2 solve; a seed with an iteration cap gives one result; the
search stops at the lower bound; diagnostics carry the run figures."""
from __future__ import annotations

import random

import pytest

from src.bound import lower_bound
from src.checker import check
from src.engines import e1
from src.engines.e4 import solve, solve_e1, solve_e2
from src.engines.e4.operators import Context, Settings
from src.engines.e4.packer import Deadline, Packer
from src.engines.e4.search import Search
from src.engines.e4.state import from_solution, key
from src.formats import solution_to_dict
from src.model import ContainerType, Params
from tests.builders import instance, line, random_lot

P = Params(delta=0.05, alpha=0.8)
CAPPED = Settings(max_iterations=30)


@pytest.mark.parametrize("seed", [2, 4, 6, 8])
def test_e1_core_solutions_pass_the_checker_and_improve(seed):
    inst = random_lot(seed)
    sol, diag = solve(inst, P, 1e6, 1, "e1", CAPPED)
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert result.cost == pytest.approx(diag["cost"])
    assert diag["cost"] < diag["initial_cost"]  # these lots all improve within 30 iterations
    assert diag["iterations"] == 30 and diag["stop"] == "iterations"


def test_e2_core_solution_passes_the_checker():
    inst = random_lot(8)
    sol, diag = solve(inst, P, 1e6, 1, "e2", Settings(max_iterations=8))
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert diag["cost"] <= diag["initial_cost"]


@pytest.mark.parametrize("seed", [1, 3, 5])
def test_never_worse_than_the_initial_solution(seed):
    inst = random_lot(seed)
    _, diag = solve(inst, P, 1e6, 1, "e1", CAPPED)
    assert (diag["cost"], diag["emptiest_fill"]) <= (diag["initial_cost"], diag["emptiest_fill_initial"])


def test_same_seed_same_result():
    inst = random_lot(6)
    a, _ = solve(inst, P, 1e6, 7, "e1", CAPPED)
    b, _ = solve(inst, P, 1e6, 7, "e1", CAPPED)
    assert solution_to_dict(a) == solution_to_dict(b)


def test_stops_at_the_lower_bound():
    # Two 1 m cubes, one container type that holds both: the initial solve meets the bound.
    box = ContainerType(id="B", L=2.2, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
    inst = instance(line("A", qty=2), types=(box,))
    sol, diag = solve(inst, P, 60.0, 1, "e1")
    assert check(inst, sol, P).ok
    assert diag["stop"] == "bound" and diag["iterations"] == 0 and diag["cost"] == diag["bound"] == 1.0


def test_diagnostics_report_operators_and_timing():
    _, diag = solve(random_lot(2), P, 1e6, 1, "e1", CAPPED)
    assert set(diag["destroy"]) == {"worst", "random_containers", "random_items"}
    assert set(diag["repair"]) == {"greedy", "greedy_shuffle"}
    assert sum(op["uses"] for op in diag["destroy"].values()) == 30
    assert diag["time_initial"] <= diag["best_found_time"] <= diag["time_total"]
    assert diag["pack_one_calls"] > 0 and diag["improvements"] >= 1


def test_registered_engines_use_the_settings_tuned_for_their_core():
    box = ContainerType(id="B", L=2.2, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
    inst = instance(line("A", qty=2), types=(box,))
    _, d1 = solve_e1(inst, P, 60.0, 1)
    _, d2 = solve_e2(inst, P, 60.0, 1)
    assert d1["settings"]["destroy_share"] == 0.15 and d1["settings"]["reaction"] == 0.1
    assert d2["settings"]["reaction"] == 0.3 and d2["settings"]["destroy_share"] == 0.3


@pytest.mark.parametrize("acceptance", ["flat", "lahc"])
@pytest.mark.parametrize("seed", [2, 5])
def test_clock_free_acceptance_repeats_a_shorter_run_and_adds_iterations(acceptance, seed):
    # under "flat" and "lahc" iteration k does not depend on the budget, so a run of 40
    # iterations is a run of 15 plus 25 more: every operator used at least as often, never dearer.
    inst = random_lot(seed)
    _, short = solve(inst, P, 1e6, 3, "e1", Settings(max_iterations=15, acceptance=acceptance))
    _, long = solve(inst, P, 1e6, 3, "e1", Settings(max_iterations=40, acceptance=acceptance))
    assert (long["cost"], long["emptiest_fill"]) <= (short["cost"], short["emptiest_fill"])
    for kind in ("destroy", "repair"):
        for name, op in short[kind].items():
            assert long[kind][name]["uses"] >= op["uses"]
    assert long["improvements"] >= short["improvements"]


class _CutPacker(Packer):
    """Raises `Deadline` once `cut_at` core calls are made, as the clock would."""

    cut_at: int | None = None

    def pack(self, items, ctype, hints=None):
        if self.cut_at is not None and self.calls >= self.cut_at:
            raise Deadline
        return super().pack(items, ctype, hints)


def _search(inst, acceptance):
    settings = Settings(max_iterations=40, acceptance=acceptance)
    packer = _CutPacker(inst, P, e1.pack_one, float("inf"))
    initial_solution, _ = e1.solve(inst, P, 1e6, 3)
    initial = from_solution(inst, initial_solution, packer.pieces)
    return Search(initial, Context(inst, packer, random.Random(3), settings), lower_bound(inst).cost), packer


@pytest.mark.parametrize("acceptance", ["flat", "lahc"])
@pytest.mark.parametrize("cut", [5, 20])
def test_a_resumed_search_runs_the_same_iterations_as_one_run(acceptance, cut):
    # an iteration cut by the deadline is rolled back, so advancing, stopping and advancing again
    # gives what one advance gives.
    inst = random_lot(4)
    once, _ = _search(inst, acceptance)
    whole = once.advance(float("inf"))
    twice, packer = _search(inst, acceptance)
    packer.cut_at = cut
    first = twice.advance(float("inf"))
    assert first.stop == "time" and first.iterations < whole.iterations
    packer.cut_at = None
    again = twice.advance(float("inf"))
    assert (again.iterations, again.improvements, again.accepted) == (whole.iterations, whole.improvements, whole.accepted)
    assert key(again.best) == key(whole.best)
    assert (again.destroy, again.repair) == (whole.destroy, whole.repair)


def test_unknown_acceptance_is_rejected():
    with pytest.raises(ValueError, match="acceptance"):
        solve(random_lot(2), P, 1e6, 1, "e1", Settings(max_iterations=2, acceptance="x"))
