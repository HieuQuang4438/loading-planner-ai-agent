"""Tests for `e5-tilt` (probe): the `e1-tilt` core joins only when it changes some
orientation; its columns let the master use fewer containers; solutions pass the checker."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines.e5.engine import Settings, solve, tilt_changes
from src.model import ContainerType, Params
from tests.builders import instance, line

P = Params(delta=0.1, alpha=0.8)
LOW = ContainerType(id="LOW", L=10.0, W=2.1, H=1.9, door_w=2.1, door_h=1.9, max_mass=10000.0, cost=1.0)
CAPPED = Settings(alns_iterations=5, pricing_rounds=2, tilt_core=True)


def test_core_joins_only_when_tilting_changes_an_orientation():
    assert tilt_changes(instance(line("A", L=1.0, W=0.6, H=1.0, tippable=True), types=(LOW,)))
    assert not tilt_changes(instance(line("A", L=1.0, W=0.6, H=1.0), types=(LOW,)))
    assert not tilt_changes(instance(line("A", L=1.2, W=1.1, H=0.5, tippable=True), types=(LOW,)))
    _, diag = solve(instance(line("A", qty=3), types=(LOW,)), P, 1e5, 1, CAPPED)
    assert diag["tilt_core"] is False


def test_tilted_columns_save_a_container():
    # Upright, one LOW holds 27 (one tier); lying on W, 54 (three tiers). 40 items: 2 containers vs 1.
    inst = instance(line("A", qty=40, L=1.0, W=0.6, H=1.0, tippable=True), types=(LOW,))
    plain, _ = solve(inst, P, 1e5, 1, Settings(alns_iterations=5, pricing_rounds=2))
    sol, diag = solve(inst, P, 1e5, 1, CAPPED)
    result = check(inst, sol, P)
    assert result.ok, result.violations[:3]
    assert diag["tilt_core"] is True
    assert result.cost == pytest.approx(1.0)
    assert check(inst, plain, P).cost == pytest.approx(2.0)
