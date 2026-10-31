"""Tests for the shared fleet layer: type choice, the
last-container swap, and the packing-core contract, all driven by small hand-written `pack_one`
stubs instead of a real packing core, so each scenario is exact and geometry-independent.
"""
from __future__ import annotations

import random
import time

import pytest

from src.engines import fleet
from src.engines.base import expand_pieces
from src.model import ContainerType, Placement
from tests.builders import PARAMS, instance, line

RNG = random.Random(0)


def _one_at_a_time(items, ctype, params, rng):
    p = items[0]
    return [Placement(item=p.item, k=0, x=0.0, y=0.0, z=0.0, o="LWH")]


def _place_all(items, ctype, params, rng):
    return [Placement(item=p.item, k=0, x=float(i), y=0.0, z=0.0, o="LWH") for i, p in enumerate(items)]


def _nothing(items, ctype, params, rng):
    return []


def test_fleet_picks_the_cheapest_type_when_every_type_can_hold_everything():
    expensive = ContainerType(id="A", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=1.0)
    cheap = ContainerType(id="B", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=0.4)
    inst = instance(line("A", qty=3, L=1, W=1, H=1, mass=1), types=(expensive, cheap))

    solution = fleet.solve(inst, PARAMS, time_limit=10.0, seed=1, pack_one=_one_at_a_time)

    assert len(solution.containers) == 3
    assert {c.type for c in solution.containers} == {"B"}


def test_fleet_swaps_the_emptiest_container_into_a_cheaper_type_when_repacking_it_succeeds():
    # The stub's own "capacity" (per-container item count) differs by type id, standing in for a
    # real core's geometry: BIG fits 3 items/container, SMALL only 2. That extra container is why
    # SMALL (3 containers, 2.1) still loses to BIG (2 containers, 2.0) as the *primary* choice, even
    # though SMALL costs less per container — but SMALL can still swap in for whichever one BIG
    # container ends up with 2 items or fewer, since a fresh repack of just those items fits.
    capacity = {"BIG": 3, "SMALL": 2}

    def capped(items, ctype, params, rng):
        chosen = items[: capacity[ctype.id]]
        return [Placement(item=p.item, k=0, x=float(i), y=0.0, z=0.0, o="LWH") for i, p in enumerate(chosen)]

    big = ContainerType(id="BIG", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=1.0)
    small = ContainerType(id="SMALL", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=0.7)
    inst = instance(line("A", qty=5, L=1, W=1, H=1, mass=1), types=(big, small))

    solution = fleet.solve(inst, PARAMS, time_limit=10.0, seed=1, pack_one=capped)

    # Cheapest primary plan: BIG, 2 containers of 3 and 2 items (cost 2.0). The 2-item container is
    # the emptiest; repacking just its 2 items into a fresh, empty SMALL succeeds (capacity 2), and
    # SMALL is cheaper, so it gets swapped in: 1.0 + 0.7 = 1.7.
    types = sorted(c.type for c in solution.containers)
    assert types == ["BIG", "SMALL"]
    total_cost = sum(inst.container_type(c.type).cost for c in solution.containers)
    assert total_cost == pytest.approx(1.7)
    swapped = next(c for c in solution.containers if c.type == "SMALL")
    swapped_items = [p.item for p in solution.placements if p.k == swapped.k]
    assert len(swapped_items) == 2


def test_swap_repacks_the_emptiest_container_instead_of_replaying_its_old_placements():
    # This container's items sit spread across BIG's full length (x up to 66) -- replayed as-is,
    # they would not fit inside SMALL's shorter length (L=10) at all. A fresh repack call on SMALL
    # (via `_place_all`, which always packs its given pieces compactly from x=0) finds room instead,
    # which is exactly the case a naive "do the old coordinates still fit" check would have missed.
    big = ContainerType(id="BIG", L=100, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=1.0)
    small = ContainerType(id="SMALL", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=0.5)
    inst = instance(line("A", qty=3, L=1, W=1, H=1, mass=1), types=(big, small))
    spread = [Placement(item=f"A#{i + 1}", k=1, x=i * 33.0, y=0.0, z=0.0, o="LWH") for i in range(3)]
    plan = fleet._Plan(cost=big.cost, containers=[("BIG", spread)])

    swapped = fleet._swap_emptiest(inst, plan, PARAMS, seed=1, pack_one=_place_all)

    assert swapped.containers[0][0] == "SMALL"
    assert {p.item for p in swapped.containers[0][1]} == {"A#1", "A#2", "A#3"}
    assert swapped.cost == pytest.approx(small.cost)


def test_plan_for_type_routes_an_item_that_does_not_fit_the_primary_type_to_its_cheapest_fit():
    a = ContainerType(id="A", L=20, W=2, H=2, door_w=2, door_h=2, max_mass=1000, cost=1.0)
    b = ContainerType(id="B", L=1.2, W=2, H=2, door_w=2, door_h=2, max_mass=1000, cost=2.0)
    inst = instance(
        line("small", qty=3, L=1.0, W=1.0, H=1.0, mass=1.0),
        line("big", qty=1, L=15.0, W=1.0, H=1.0, mass=1.0),  # only fits A: too long for B
        types=(a, b),
    )
    pieces = expand_pieces(inst)

    plan = fleet._plan_for_type(inst, pieces, b, PARAMS, RNG, _place_all, deadline=float("inf"))

    by_type = {}
    for type_id, placements in plan.containers:
        by_type.setdefault(type_id, []).extend(p.item for p in placements)
    assert by_type["B"] == ["small#1", "small#2", "small#3"]  # fit B, the primary type, directly
    assert by_type["A"] == ["big#1"]  # misfit for B, routed to the only (and cheapest) type it fits
    assert plan.cost == pytest.approx(2.0 + 1.0)


def test_pack_one_placing_nothing_raises_instead_of_looping_forever():
    ctype = ContainerType(id="X", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=1.0)
    inst = instance(line("A", L=1, W=1, H=1, mass=1), types=(ctype,))

    with pytest.raises(ValueError, match="placed 0 items"):
        fleet.solve(inst, PARAMS, time_limit=10.0, seed=1, pack_one=_nothing)


def test_solve_raises_fleet_timeout_when_no_type_finishes_in_time():
    # Two items, one placed per (slow) call: the first call alone takes 10x the whole time budget,
    # so the loop's second deadline check (before it would open a second container) always raises —
    # a wide enough margin that this is not a close clock race.
    ctype = ContainerType(id="X", L=10, W=10, H=10, door_w=10, door_h=10, max_mass=1000, cost=1.0)
    inst = instance(line("A", qty=2, L=1, W=1, H=1, mass=1), types=(ctype,))

    def one_then_sleep(items, ctype_, params, rng):
        time.sleep(0.2)
        p = items[0]
        return [Placement(item=p.item, k=0, x=0.0, y=0.0, z=0.0, o="LWH")]

    with pytest.raises(fleet.FleetTimeout):
        fleet.solve(inst, PARAMS, time_limit=0.02, seed=1, pack_one=one_then_sleep)
