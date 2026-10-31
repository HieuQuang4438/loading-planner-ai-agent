"""Tests for knapsack pricing and engine `e5-knap`: the knapsack solver, the gamma update, the
reduced-cost filter on pricing results, the skip rule, and a full run that passes the checker."""
from __future__ import annotations

import random
import time

import pytest

from src.checker import check
from src.engines import e1
from src.engines.e5 import engine as e5_engine
from src.engines.e5 import knapsack
from src.engines.e5.engine import Settings, _Knap, _price_knapsack, solve
from src.engines.e5.pool import Pool, RecordingPacker
from src.model import ContainerType, Params, Placement
from tests.builders import BOX, instance, line, random_lot

P = Params(delta=0.05, alpha=0.8)
TIME = 1e5


def solve_ks(values, volumes, masses, qtys, volume_cap, mass_cap=1e9, time_limit=5.0):
    return knapsack.solve(values, volumes, masses, qtys, volume_cap, mass_cap, time_limit)


# --- the solver ------------------------------------------------------------------------------------


def test_knapsack_maximises_value_within_volume():
    # Volume cap 10: best is 2 x B (value 14, volume 10) over A + B (value 13, volume 9) or 5 x A (10).
    a = solve_ks([2.0, 7.0], [2.0, 5.0], [1.0, 1.0], [5, 5], 10.0)
    assert a == [0, 2]


def test_knapsack_respects_quantities_volume_and_mass():
    values, volumes, masses, qtys = [3.0, 2.0, 1.0], [1.0, 1.0, 1.0], [4.0, 1.0, 1.0], [2, 3, 9]
    a = solve_ks(values, volumes, masses, qtys, 6.0, 9.0)
    assert all(0 <= x <= q for x, q in zip(a, qtys))
    assert sum(x * v for x, v in zip(a, volumes)) <= 6.0
    assert sum(x * m for x, m in zip(a, masses)) <= 9.0
    assert a == [1, 3, 2]  # mass binds: 4 + 3 + 2 = 9; value 3 + 6 + 2 = 11 (two of A would cost 8 of the 9)


def test_knapsack_mass_alone_can_bind():
    a = solve_ks([1.0], [0.001], [10.0], [100], 100.0, 35.0)
    assert a == [3]


def test_knapsack_floor_alone_can_bind():
    # ample volume and mass; 1 m2 of floor per item and 3.5 m2 of floor: three items
    a = knapsack.solve([1.0], [0.1], [1.0], [10], 100.0, 1e6, 1.0, areas=[1.0], area_cap=3.5)
    assert a == [3]


def test_floor_share_divides_the_footprint_by_the_column_height():
    assert knapsack.floor_share(1.2, 1.0, 0.235, 172.9, 100, 0.0, 2.39) == pytest.approx(1.2)  # nothing on top
    assert knapsack.floor_share(1.0, 1.0, 0.5, 100.0, 100, None, 2.39) == pytest.approx(0.25)  # 4 fit in height
    assert knapsack.floor_share(1.0, 1.0, 0.5, 100.0, 2, None, 2.39) == pytest.approx(0.5)  # tiers
    assert knapsack.floor_share(1.0, 1.0, 0.5, 100.0, 100, 150.0, 2.39) == pytest.approx(0.5)  # load: one on top
    assert knapsack.floor_share(1.0, 1.0, 3.0, 100.0, 100, None, 2.39) == pytest.approx(1.0)  # at least 1


def test_knapsack_empty_and_zero_cases():
    assert solve_ks([], [], [], [], 10.0) == []
    assert solve_ks([1.0], [1.0], [1.0], [3], 10.0, time_limit=0.0) == [0]
    assert solve_ks([0.0, 0.0], [1.0, 1.0], [1.0, 1.0], [3, 3], 10.0) == [0, 0]  # nothing to gain
    assert solve_ks([1.0], [5.0], [1.0], [3], 4.0) == [0]  # nothing fits


# --- gamma -----------------------------------------------------------------------------------------


def test_gamma_moves_and_is_clamped():
    args = (0.05, 0.02, 0.5, 1.0)
    assert knapsack.next_gamma(0.9, False, *args) == pytest.approx(0.85)
    assert knapsack.next_gamma(0.9, True, *args) == pytest.approx(0.92)
    assert knapsack.next_gamma(0.51, False, *args) == 0.5
    assert knapsack.next_gamma(0.99, True, *args) == 1.0


def test_knap_state_keeps_gamma_per_type():
    knap = _Knap(Settings())
    knap.update("A", False)
    knap.update("A", False)
    knap.update("B", True)
    assert knap.gamma == {"A": pytest.approx(0.8), "B": pytest.approx(0.92)}


# --- the filter and the skip rule ------------------------------------------------------------------


def stub_pack_one(items, ctype, params, rng, hints=None):
    return [Placement(p.item, 0, float(j), 0.0, 0.0, "LWH") for j, p in enumerate(items)]


def test_recording_packer_files_only_what_the_filter_admits():
    inst = instance(line("A", qty=3), line("B", qty=3))
    pool = Pool(inst)
    packer = RecordingPacker(inst, P, stub_pack_one, time.monotonic() + 60, pool, "t")
    packer.pack(["A#1", "A#2"], BOX)
    assert len(pool) == 1  # no filter: filed
    packer.admit = lambda ctype, placed: len(placed) > 2
    packer.pack(["B#1", "B#2"], BOX)
    packer.pack(["B#1", "B#2", "B#3"], BOX)
    assert [c.counts for c in pool.columns] == [(2, 0), (0, 3)]
    packer.pack(["B#1", "B#2"], BOX)  # a cache hit is offered again, and rejected again
    assert len(pool) == 2
    packer.admit = lambda ctype, placed: True
    packer.pack(["B#1", "B#2"], BOX)  # the same hit, now admitted
    assert [c.counts for c in pool.columns] == [(2, 0), (0, 3), (0, 2)]


def make_round(duals, types=(BOX,), qty=8):
    inst = instance(line("A", qty=qty, L=2.0, W=1.0, H=1.0), line("B", qty=qty, L=1.0, W=1.0, H=1.0), types=types)
    pool = Pool(inst)
    packer = RecordingPacker(inst, P, e1.pack_one, time.monotonic() + 60, pool, "pricing")
    knap = _Knap(Settings(pricing="knapsack"))
    _price_knapsack(inst, pool, {"e1": packer}, duals, random.Random(1), Settings(pricing="knapsack"), knap)
    return inst, pool, packer, knap


def test_every_column_priced_in_has_negative_reduced_cost():
    duals = [0.30, 0.20]
    inst, pool, packer, knap = make_round(duals)
    assert len(pool) > 0 and knap.sets == 1 and knap.solves == 1
    for col in pool.columns:
        assert col.cost - sum(pi * a for pi, a in zip(duals, col.counts)) < -e5_engine.REDUCED_COST_TOL
    assert packer.admit is None  # restored after the round


def test_set_that_cannot_beat_the_cost_is_not_given_to_the_core():
    inst, pool, packer, knap = make_round([0.01, 0.01])  # 16 items at most, 0.16 < 1.0
    assert knap.solves == 1 and knap.sets == 0
    assert packer.calls == 0 and len(pool) == 0


def test_lines_without_a_positive_dual_are_left_out():
    inst, pool, packer, knap = make_round([0.0, 0.5], qty=30)
    assert len(pool) > 0
    assert all(col.counts[0] == 0 for col in pool.columns)


# --- the engine ------------------------------------------------------------------------------------


def test_unknown_pricing_is_rejected():
    with pytest.raises(ValueError):
        solve(random_lot(2), P, TIME, 1, Settings(pricing="x"))


def test_default_pricing_is_unchanged():
    assert Settings().pricing == "greedy"
    _, diag = solve(random_lot(2), P, TIME, 1, Settings(alns_iterations=10, pricing_rounds=2))
    assert diag["engine"] == "e5"
    assert "knapsack_solves" not in diag.get("pricing", {})


def test_knap_run_passes_the_checker_and_reports_diagnostics():
    inst = random_lot(5)
    sol, diag = solve(inst, P, TIME, 1, Settings(alns_iterations=10, pricing_rounds=3, pricing="knapsack"))
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert result.cost == pytest.approx(diag["cost"])
    assert diag["engine"] == "e5-knap"
    pricing = diag["pricing"]
    if pricing["rounds"]:
        assert pricing["knapsack_solves"] >= pricing["knapsack_sets_over_cost"] >= 0
        assert len(pricing["negative_per_round"]) == pricing["rounds"]
        assert sum(pricing["negative_per_round"]) == pricing["columns_negative"]
        assert all(0.5 <= g <= 1.0 for g in pricing["gamma"].values())
        assert pricing["knapsack_time"] >= 0.0


