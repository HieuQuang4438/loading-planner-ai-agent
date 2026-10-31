"""Tests for E5's leftover-time rounds (engine e5-mono): when the final master finishes early, each
core's ALNS resumes and the master runs again; the returned solution still passes the checker."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines.e5.engine import Settings, solve
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
MONO = Settings(initial_to_end=True, alns_acceptance="flat", trim_retries=5, reuse_time=True)


def test_leftover_time_goes_back_to_alns_and_the_master():
    inst = random_lot(6)  # final master OPTIMAL well before the end of the span
    sol, diag = solve(inst, P, 6.0, 1, MONO)
    assert check(inst, sol, P).ok
    assert diag["final"]["status"] == "OPTIMAL"
    reuse = diag["reuse"]
    assert reuse["rounds"] >= 1 and reuse["columns_added"] > 0
    assert sum(reuse["iterations"].values()) > 0
    assert reuse["masters"] and reuse["masters"][0]["status"] in ("OPTIMAL", "FEASIBLE")
    assert diag["cost"] <= diag["final"]["cost_trimmed"] + 1e-9


def test_no_round_without_the_setting():
    _, diag = solve(random_lot(6), P, 3.0, 1, Settings(initial_to_end=True, alns_acceptance="flat"))
    assert "reuse" not in diag


def test_a_search_capped_by_iterations_ends_the_rounds():
    # alns_iterations stops every search for good ("iterations"), so nothing is left to resume.
    _, diag = solve(random_lot(6), P, 6.0, 1, Settings(initial_to_end=True, alns_acceptance="flat",
                                                       reuse_time=True, alns_iterations=5))
    if diag["final"]["status"] == "OPTIMAL":
        assert diag["reuse"]["stop"] in ("search", "bound") and diag["reuse"]["rounds"] == 0
    else:
        pytest.skip("final master used the whole span")
