"""Tests for E5: every solution passes the independent
checker and is never worse than the ALNS incumbent; the master finds a mixed fleet; the run stops
at the lower bound; diagnostics carry the harvest-only master and the LP value."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines import base
from src.engines.e5.engine import Settings, solve
from src.model import ContainerType, Params
from tests.builders import instance, line, random_lot

P = Params(delta=0.05, alpha=0.8)
CAPPED = Settings(alns_iterations=10, pricing_rounds=2)
TIME = 1e5  # phases capped by iterations and rounds; the master solves to optimality on these lots


def test_e5_is_registered():
    assert "e5" in base.names()


@pytest.mark.parametrize("seed", [2, 5])
def test_solutions_pass_the_checker_and_never_lose_to_the_incumbent(seed):
    inst = random_lot(seed)
    sol, diag = solve(inst, P, TIME, 1, CAPPED)
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert result.cost == pytest.approx(diag["cost"])
    assert diag["cost"] <= diag["cost_harvest"] <= diag["incumbent_cost"] + 1e-9
    assert diag["pre_pricing"]["checker_ok"] and diag["final"]["checker_ok"]
    assert diag["lp_value"] <= diag["lp_value_harvest"] + 1e-9  # more columns never raise the LP
    assert diag["columns"] >= diag["columns_harvested"] > 0


def test_master_mixes_types_by_cost():
    # Five 1 m cubes. BIG holds four (cost 1.0), SMALL one (cost 0.3): BIG + SMALL = 1.3 is optimal.
    big = ContainerType(id="BIG", L=2.2, W=2.2, H=1.0, door_w=2.2, door_h=1.0, max_mass=1000.0, cost=1.0)
    small = ContainerType(id="SMALL", L=1.1, W=1.1, H=1.0, door_w=1.1, door_h=1.0, max_mass=1000.0, cost=0.3)
    inst = instance(line("A", qty=5), types=(big, small))
    sol, diag = solve(inst, P, TIME, 1, CAPPED)
    assert check(inst, sol, P).ok
    assert diag["cost"] == pytest.approx(1.3)
    assert sorted(c.type for c in sol.containers) == ["BIG", "SMALL"]


def test_stops_at_the_lower_bound():
    box = ContainerType(id="B", L=2.2, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
    inst = instance(line("A", qty=2), types=(box,))
    sol, diag = solve(inst, P, 60.0, 1)
    assert check(inst, sol, P).ok
    assert diag["stop"] == "bound" and diag["cost"] == diag["bound"] == 1.0
    assert "pre_pricing" not in diag
