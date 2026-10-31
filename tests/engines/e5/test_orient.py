"""`e5-orient`: the `e1-orient-dense` core and E2's orient mode; diagnostics; `e5` unchanged."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines import base
from src.engines.e5.engine import Settings, dense_changes, solve
from src.model import ContainerType, Params, is_tipped
from tests.builders import instance, line, random_lot

P = Params(delta=0.1, alpha=0.8)
LOW = ContainerType(id="LOW", L=10.0, W=2.1, H=1.9, door_w=2.1, door_h=1.9, max_mass=10000.0, cost=1.0)
CAPPED = Settings(alns_iterations=5, pricing_rounds=2, orient_dense_core=True, e2_orient=True)


def test_registered():
    assert "e5-orient" in base.names()


def test_orient_dense_core_joins_only_when_the_rule_changes_an_orientation():
    assert dense_changes(instance(line("A", L=1.0, W=0.6, H=1.0, tippable=True), types=(LOW,)), 0.1)
    assert not dense_changes(instance(line("A", L=1.0, W=0.6, H=1.0), types=(LOW,)), 0.1)
    _, diag = solve(instance(line("A", qty=3), types=(LOW,)), P, 1e5, 1, CAPPED)
    assert diag["orient_dense_core"] is False and "e1-orient-dense_initial_cost" not in diag


def test_orient_solution_is_valid_with_diagnostics():
    inst = instance(line("A", qty=40, L=1.0, W=0.6, H=1.0, tippable=True), types=(LOW,))
    sol, diag = solve(inst, P, 1e5, 1, CAPPED)
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert diag["engine"] == "e5-orient" and diag["orient_dense_core"] is True and diag["orient_e2"] is True
    assert "e1-orient-dense_initial_cost" in diag and "e2_time_initial" in diag
    assert sum(diag["containers_by_core"].values()) == len(sol.containers)
    assert diag["tipped_pieces"] == sum(1 for p in sol.placements if is_tipped(p.o))
    assert sum(diag["tipped_by_core"].values()) == diag["tipped_pieces"]
    assert diag["containers_from_e1_orient_dense"] == diag["containers_by_core"].get("e1-orient-dense", 0)
    assert "e1-orient-dense_alns" not in diag  # the dense core gives columns only, no search


def test_random_lot_is_valid_and_diagnostics_are_filled():
    inst = random_lot(5)
    sol, diag = solve(inst, P, 1e5, 1, CAPPED)
    assert check(inst, sol, P).ok
    assert sum(diag["containers_by_core"].values()) == len(sol.containers)


def test_default_e5_has_no_orient_dense_core_and_no_orient():
    inst = random_lot(5)
    sol, diag = solve(inst, P, 1e5, 1, Settings(alns_iterations=5, pricing_rounds=2))
    assert check(inst, sol, P).ok
    assert diag["engine"] == "e5" and diag["orient_dense_core"] is False and diag["orient_e2"] is False
    assert not any(k.startswith("e1-orient-dense") for k in diag)
    assert "e1-orient-dense" not in diag.get("columns_by_source", {})


@pytest.mark.parametrize("flags", [{"orient_dense_core": True}, {"e2_orient": True}])
def test_each_flag_alone_is_valid(flags):
    inst = random_lot(8)
    sol, _ = solve(inst, P, 1e5, 1, Settings(alns_iterations=5, pricing_rounds=2, **flags))
    assert check(inst, sol, P).ok
