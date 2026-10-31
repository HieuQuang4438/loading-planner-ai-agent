"""Tests for E4's stall rule: the search stops once the iterations since its last improvement exceed
max(stall_min, stall_ratio x the iteration of that improvement). Iteration counts only; off by default."""
from __future__ import annotations

import random
import time

import pytest

from src.bound import lower_bound
from src.engines import e1
from src.engines.e4.operators import Context, Settings
from src.engines.e4.packer import Packer
from src.engines.e4.search import Search
from src.engines.e4.state import from_solution
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)


def _search(settings: Settings) -> Search:
    inst = random_lot(4)
    packer = Packer(inst, P, e1.pack_one, float("inf"))
    initial_solution, _ = e1.solve(inst, P, 1e6, 3)
    initial = from_solution(inst, initial_solution, packer.pieces)
    return Search(initial, Context(inst, packer, random.Random(3), settings), lower_bound(inst).cost)


def _far() -> float:
    return time.monotonic() + 600.0


@pytest.mark.parametrize("stall_min,ratio", [(5, 2.0), (12, 0.5), (3, 4.0)])
def test_the_search_stops_at_the_first_iteration_past_the_threshold(stall_min, ratio):
    search = _search(Settings(max_iterations=5000, acceptance="flat", stall_min=stall_min, stall_ratio=ratio))
    out = search.advance(_far())
    assert out.stop == "stall"
    last = out.last_improvement_iteration
    assert out.iterations == last + int(max(stall_min, ratio * last)) + 1
    if out.improvement_iterations:
        assert out.improvement_iterations[-1] == last
        assert out.improvement_iterations == sorted(set(out.improvement_iterations))


def test_the_threshold_is_the_larger_of_the_floor_and_the_ratio_term():
    search = _search(Settings(stall_min=10, stall_ratio=2.0))
    search.last_improvement_iteration = 100  # ratio term 200 beats the floor
    search.iterations = 300
    assert not search.stalled(10, 2.0)
    search.iterations = 301
    assert search.stalled(10, 2.0)
    search.last_improvement_iteration = 2  # floor 10 beats the ratio term 4
    search.iterations = 12
    assert not search.stalled(10, 2.0)
    search.iterations = 13
    assert search.stalled(10, 2.0)


def test_a_stalled_search_stays_stalled_when_advanced_again():
    search = _search(Settings(max_iterations=5000, acceptance="flat", stall_min=5, stall_ratio=2.0))
    first = search.advance(_far())
    again = search.advance(_far())
    assert again.stop == "stall" and again.iterations == first.iterations
    assert again.improvement_iterations == first.improvement_iterations


def test_the_same_seed_stalls_at_the_same_iteration():
    a = _search(Settings(max_iterations=5000, acceptance="flat", stall_min=5)).advance(_far())
    b = _search(Settings(max_iterations=5000, acceptance="flat", stall_min=5)).advance(_far())
    assert (a.iterations, a.improvement_iterations) == (b.iterations, b.improvement_iterations)


def test_the_rule_is_off_by_default_and_the_diagnostics_are_neutral():
    plain = _search(Settings(max_iterations=60, acceptance="flat")).advance(_far())
    assert plain.stop == "iterations" and plain.iterations == 60
    assert plain.last_improvement_iteration == (plain.improvement_iterations[-1] if plain.improvement_iterations else 0)
    assert len(plain.improvement_iterations) == plain.improvements
    loose = _search(Settings(max_iterations=60, acceptance="flat", stall_min=10_000)).advance(_far())
    assert (loose.iterations, loose.improvements, loose.improvement_iterations) == (
        plain.iterations, plain.improvements, plain.improvement_iterations)
