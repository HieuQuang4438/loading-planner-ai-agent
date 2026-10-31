"""Tests for E5's ALNS stall trial (engines e5-v3-stall, e5-orient-v3-stall): a core whose ALNS stalls
stops by iteration count, and step 5 skips when no core can resume; e5-v3 records where its ALNS improved."""
from __future__ import annotations

from dataclasses import replace

from src.checker import check
from src.engines.e5.engine import VERSIONS, solve
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)
STALL = replace(VERSIONS["e5-v3-stall"], alns_stall_min=20)  # a short floor keeps the test fast
FIELDS = ("improvement_iterations", "last_improvement_iteration", "last_improvement_time")


def test_a_stalled_alns_stops_well_before_the_harvest_deadline_and_step_5_is_skipped():
    inst = random_lot(6)
    sol, diag = solve(inst, P, 20.0, 1, STALL)
    assert check(inst, sol, P).ok
    stalled = [diag[f"{c}_alns"] for c in diag["cores"] if diag.get(f"{c}_alns", {}).get("stop") == "stall"]
    if not stalled:
        return  # every core reached the bound or improved to the end: nothing to assert on this lot
    for a in stalled:
        assert a["time"] < 0.6 * 0.95 * 20.0 / 2  # well before this core's share of the harvest
        last = a["last_improvement_iteration"]
        assert a["iterations"] == last + int(max(20, 2.0 * last)) + 1
    if len(stalled) == len(diag["cores"]) and "reuse" in diag:
        assert diag["reuse"]["stop"] == "stall" and diag["reuse"]["rounds"] == 0


def test_e5_v3_records_where_its_alns_improved_and_is_otherwise_unchanged():
    inst = random_lot(6)
    capped = replace(VERSIONS["e5-v3"], alns_iterations=40, pricing_rounds=1)
    sol, diag = solve(inst, P, 1e5, 1, capped)
    assert check(inst, sol, P).ok
    for core in diag["cores"]:
        a = diag.get(f"{core}_alns")
        if a is None:
            continue
        assert all(f in a for f in FIELDS)
        assert len(a["improvement_iterations"]) == a["improvements"]
        assert a["last_improvement_iteration"] == (a["improvement_iterations"][-1] if a["improvements"] else 0)
        assert (a["last_improvement_time"] is None) == (a["improvements"] == 0)
        assert a["stop"] != "stall"
    again, diag2 = solve(inst, P, 1e5, 1, capped)
    assert [diag[f"{c}_alns"]["improvement_iterations"] for c in diag["cores"] if f"{c}_alns" in diag] == [
        diag2[f"{c}_alns"]["improvement_iterations"] for c in diag2["cores"] if f"{c}_alns" in diag2]
    assert again.containers == sol.containers
