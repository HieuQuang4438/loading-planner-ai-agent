"""Tests for E5 with E3's BRKGA in the harvest (engine `e5-brkga`): every solution passes the independent checker and is
never worse than the BRKGA incumbent; columns are filed under the BRKGA sources; `e5` keeps ALNS."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines.e5.engine import Settings, solve
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
CAPPED = Settings(search="brkga", brkga_generations=2, pricing_rounds=2)
TIME = 1e5  # phases capped by generations and rounds


@pytest.mark.parametrize("seed", [2, 5])
def test_brkga_solutions_pass_the_checker_and_never_lose_to_the_incumbent(seed):
    inst = random_lot(seed)
    sol, diag = solve(inst, P, TIME, 1, CAPPED)
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert diag["engine"] == "e5-brkga"
    assert result.cost == pytest.approx(diag["cost"])
    assert diag["cost"] <= diag["cost_harvest"] <= diag["incumbent_cost"] + 1e-9
    assert diag["pre_pricing"]["checker_ok"] and diag["final"]["checker_ok"]
    for core in ("e1", "e2"):
        stats = diag[f"{core}_brkga"]
        assert f"{core}_alns" not in diag
        assert stats["stop"] in ("generations", "bound")
        assert stats["decodes"] >= stats["population"] or stats["stop"] == "bound"
        assert stats["cost"] <= diag[f"{core}_initial_cost"] + 1e-9  # the initial solution is the incumbent
    sources = diag["columns_by_source"]
    assert not any(k.startswith("alns-") for k in sources)
    assert sum(sources.values()) == diag["columns"]


def test_same_seed_same_result_when_capped():
    inst = random_lot(2)
    _, a = solve(inst, P, TIME, 1, CAPPED)
    _, b = solve(inst, P, TIME, 1, CAPPED)
    assert a["cost"] == b["cost"] and a["columns_by_source"] == b["columns_by_source"]


def test_default_search_is_alns():
    assert Settings().search == "alns"
    inst = random_lot(2)
    _, diag = solve(inst, P, TIME, 1, Settings(alns_iterations=5, pricing_rounds=1))
    assert diag["engine"] == "e5"
    assert "e1_alns" in diag and "e1_brkga" not in diag
    assert not any(k.startswith("brkga-") for k in diag["columns_by_source"])


def test_unknown_search_is_rejected():
    with pytest.raises(ValueError):
        solve(random_lot(2), P, TIME, 1, Settings(search="tabu"))
