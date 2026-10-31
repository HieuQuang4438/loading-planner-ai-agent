"""Tests for `Settings.cores` and engines `e5-e1`, `e5-e2`: one packing core only;
checker-valid solutions; diagnostics carry the selected cores alone."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines.e5 import engine as e5_engine
from src.engines.e5.engine import Settings, solve
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
TIME = 1e5


def capped(**kw) -> Settings:
    return Settings(alns_iterations=10, pricing_rounds=2, **kw)


@pytest.mark.parametrize("cores", [(), ("e3",), ("e1", "e1"), ("e1", "x")])
def test_invalid_cores_are_rejected(cores):
    with pytest.raises(ValueError):
        solve(random_lot(2), P, TIME, 1, capped(cores=cores))


@pytest.mark.parametrize("core,other", [("e1", "e2"), ("e2", "e1")])
def test_single_core_is_valid_and_reports_only_that_core(core, other):
    inst = random_lot(2)
    sol, diag = solve(inst, P, TIME, 1, capped(cores=(core,)))
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert result.cost == pytest.approx(diag["cost"])
    assert diag["engine"] == f"e5-{core}"
    assert diag["cores"] == [core]
    assert diag["initial_deadline"] == "end"
    assert f"{core}_initial_cost" in diag
    assert not any(k.startswith(f"{other}_") for k in diag)
    assert diag["incumbent_core"] == core


def test_default_uses_both_cores():
    inst = random_lot(2)
    sol, diag = solve(inst, P, TIME, 1, capped())
    assert check(inst, sol, P).ok
    assert Settings().cores == ("e1", "e2")
    assert diag["engine"] == "e5"
    assert diag["cores"] == ["e1", "e2"]
    assert diag["initial_deadline"] == "alns_end"
    assert "e1_initial_cost" in diag and "e2_initial_cost" in diag


@pytest.mark.parametrize("to_end,from_s,expected", [(False, 30.0, False)])  # the e5-mono cases (to_end=True) are not kept: e5-mono is not registered here
def test_e5_mono_lets_the_second_initial_solve_run_past_the_harvest_deadline(monkeypatch, to_end, from_s, expected):
    # under e5-mono, from `initial_to_end_from` s, E2's initial solve gets the rest of the span,
    # not the rest of the harvest share; below it (10 s < 30 s here) nothing changes.
    limits = []
    real = e5_engine.fleet.solve

    def spy(instance, params, time_limit, seed, pack_one):
        limits.append(time_limit)
        return real(instance, params, time_limit, seed, pack_one)

    monkeypatch.setattr(e5_engine.fleet, "solve", spy)
    _, diag = solve(random_lot(2), P, 10.0, 1, capped(initial_to_end=to_end, initial_to_end_from=from_s))
    s = Settings()
    assert len(limits) == 2
    assert (limits[1] > s.alns_share * s.time_share * 10.0) is expected
    assert diag["engine"] == ("e5-mono" if to_end else "e5")
    assert diag["initial_deadline"] == ("end" if expected else "alns_end")


