"""Hand-built instances with a known answer for each row, so a bound can be checked exactly."""
from __future__ import annotations

from src.bound import bound_from_dict, bound_to_dict, lower_bound
from src.checker import check
from src.model import ContainerType, Instance, ItemLine, Placement, Solution, solution_cost
from tests.builders import BOX, PARAMS, at, instance, line, solution

# BOX (tests/builders.py): L=10, W=2, H=2 -> volume 40, max_mass 1000, floor area 20, cost 1.0


def test_volume_binds_when_items_fill_the_container_by_volume_alone() -> None:
    # Two lines of volume 24 each, mass and floor both trivial: total volume 48 needs 2 containers,
    # mass (20 kg) and floor area (0, tiers > 1) each need only 1.
    inst = instance(
        line("L1", L=6.0, W=2.0, H=2.0, mass=10.0, tiers=5),
        line("L2", L=6.0, W=2.0, H=2.0, mass=10.0, tiers=5),
    )
    bound = lower_bound(inst)
    assert bound.cost == 2.0
    assert bound.fleet == {"BOX": 2}
    assert bound.binding == "volume"
    assert bound.rows["mass"].cost == 1.0
    assert bound.rows["floor"].cost == 0.0  # each line can bear the other: the row is inactive


def test_mass_binds_when_items_fill_the_container_by_mass_alone() -> None:
    # 3 items of 600 kg (1800 kg total) need 2 containers by mass (max 1000 kg); volume (3 m3) needs 1.
    inst = instance(line("L1", qty=3, L=1.0, W=1.0, H=1.0, mass=600.0, tiers=5))
    bound = lower_bound(inst)
    assert bound.cost == 2.0
    assert bound.fleet == {"BOX": 2}
    assert bound.binding == "mass"
    assert bound.contributing == ("mass",)
    assert bound.rows["volume"].cost == 1.0


def test_floor_binds_when_tiers_one_items_cannot_share_the_floor() -> None:
    # tiers == 1 forces each item alone on the floor (constraint 8: down(j) == up(j) == 1). 3 items of
    # 9 m2 footprint (27 m2 total) need 2 containers by floor area (20 m2); volume and mass are tiny.
    inst = instance(line("L1", qty=3, L=3.0, W=3.0, H=0.1, mass=1.0, tiers=1))
    bound = lower_bound(inst)
    assert bound.cost == 2.0
    assert bound.fleet == {"BOX": 2}
    assert bound.binding == "floor"
    assert bound.rows["volume"].cost == 1.0
    assert bound.rows["mass"].cost == 1.0


def test_tippable_item_takes_its_smallest_footprint_only_when_tippable() -> None:
    # 6 items, L=4 W=1 H=0.5: upright footprint 4 m2, tipped (H as a horizontal extent) 0.5 m2.
    # Non-tippable: fixed at 4 m2 * 6 = 24 m2 > 20 m2 floor area -> needs 2 containers.
    # Tiltable: minimum footprint 0.5 m2 * 6 = 3 m2 <= 20 m2 -> needs only 1.
    tippable = instance(line("L1", qty=6, L=4.0, W=1.0, H=0.5, mass=1.0, tippable=True, tiers=1))
    rigid = instance(line("L1", qty=6, L=4.0, W=1.0, H=0.5, mass=1.0, tippable=False, tiers=1))
    assert lower_bound(tippable).rows["floor"].cost == 1.0
    assert lower_bound(rigid).rows["floor"].cost == 2.0


def test_mixed_fleet_finds_a_cheaper_combination_than_either_type_alone() -> None:
    # A: volume 10, cost 1. B: volume 100, cost 5. Target volume 105.
    # A alone: ceil(105/10) = 11 -> cost 11. B alone: ceil(105/100) = 2 -> cost 10.
    # Mixed, 1 A + 1 B: volume 110 >= 105, cost 6 -- cheaper than either pure fleet.
    a = ContainerType(id="A", L=10.0, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
    b = ContainerType(id="B", L=100.0, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=5.0)
    inst = Instance(
        name="mixed",
        container_types=(a, b),
        items=(ItemLine(id="L1", qty=105, L=1.0, W=1.0, H=1.0, mass=0.001, tippable=False, tiers=5, load=None),),
    )
    bound = lower_bound(inst)
    assert bound.cost == 6.0
    assert bound.fleet == {"A": 1, "B": 1}
    assert bound.binding == "volume"


def test_rows_that_bind_only_together_all_contribute() -> None:
    # A: volume 10, mass 100 kg, cost 1. B: volume 30, mass 10 kg, cost 1.5. Lot: 60 m3, 300 kg.
    # Volume alone: 2 B = 3.0. Mass alone: 3 A = 3.0. Both: 3 A + 1 B = 4.5, so each row raises it.
    a = ContainerType(id="A", L=10.0, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=100.0, cost=1.0)
    b = ContainerType(id="B", L=30.0, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=10.0, cost=1.5)
    inst = Instance(
        name="together",
        container_types=(a, b),
        items=(ItemLine(id="L1", qty=60, L=1.0, W=1.0, H=1.0, mass=5.0, tippable=False, tiers=5, load=None),),
    )
    bound = lower_bound(inst)
    assert bound.cost == 4.5
    assert bound.fleet == {"A": 3, "B": 1}
    assert bound.binding == "mixed"
    assert bound.contributing == ("volume", "mass")


def test_tied_rows_leave_no_single_contributing_row() -> None:
    # 50 m3 and 1500 kg each need 2 BOX alone and together: dropping either row keeps 2.
    inst = instance(line("L1", qty=4, L=5.0, W=2.0, H=1.25, mass=375.0, tiers=5))
    bound = lower_bound(inst)
    assert bound.cost == 2.0
    assert bound.binding == "volume"
    assert bound.contributing == ()


def test_bound_is_at_most_the_cost_of_a_real_checked_solution() -> None:
    inst = instance(line("L1", qty=3, L=1.0, W=1.0, H=1.0, mass=5.0, tiers=5))
    sol = solution(at("L1#1", 0.0), at("L1#2", 1.1), at("L1#3", 2.2))
    result = check(inst, sol, PARAMS)
    assert result.ok, result.violations
    bound = lower_bound(inst)
    assert bound.cost <= solution_cost(inst, sol) + 1e-9


# CELL: floor 2 m x 1 m (area 2), height 2, so one 2 x 1 x 1 item covers the whole floor and a second
# can only go on top of it. Floor-row costs below therefore count floor-forced items directly.
CELL = ContainerType(id="CELL", L=2.0, W=1.0, H=2.0, door_w=1.0, door_h=2.0, max_mass=1000.0, cost=1.0)


def _cell_item(id: str, qty: int = 1, mass: float = 10.0, tiers: int = 2, load: float | None = None) -> ItemLine:
    return line(id, qty=qty, L=2.0, W=1.0, H=1.0, mass=mass, tiers=tiers, load=load)


def _cell_solution(*placements: Placement, n: int = 1) -> Solution:
    return solution(*placements, containers=tuple((k, "CELL") for k in range(1, n + 1)))


def _assert_below_checked_cost(inst: Instance, sol: Solution) -> float:
    """The checker accepts `sol`, and the bound does not exceed its cost; returns the bound."""
    result = check(inst, sol, PARAMS)
    assert result.ok, result.violations
    bound = lower_bound(inst)
    assert bound.cost <= solution_cost(inst, sol) + 1e-9
    return bound.cost


def test_weak_item_that_can_rest_on_a_sturdy_one_is_not_forced_onto_the_floor() -> None:
    # B carries nothing (load 0), but A carries 10 kg, so B may sit on A. Only A is floor-forced
    # (B cannot bear it, and A's line has a single item), so the floor row needs 1 CELL, not 2.
    inst = instance(_cell_item("A", load=10.0), _cell_item("B", load=0.0), types=(CELL,))
    assert lower_bound(inst).rows["floor"].cost == 1.0
    sol = _cell_solution(at("A#1", 0.0), at("B#1", 0.0, z=1.0))
    assert _assert_below_checked_cost(inst, sol) == 1.0


def test_items_that_no_item_of_the_lot_can_bear_are_all_forced_onto_the_floor() -> None:
    # Every item is heavier than any load in the lot and tiers allow stacking, yet nothing can rest
    # on anything: all 3 items need their own floor, so 3 CELLs, although volume needs only 2.
    inst = instance(
        _cell_item("L1", qty=2, mass=10.0, tiers=100, load=5.0),
        _cell_item("L2", mass=20.0, tiers=100, load=8.0),
        types=(CELL,),
    )
    bound = lower_bound(inst)
    assert bound.binding == "floor"
    assert bound.rows["volume"].cost == 2.0
    sol = _cell_solution(at("L1#1", 0.0, k=1), at("L1#2", 0.0, k=2), at("L2#1", 0.0, k=3), n=3)
    assert _assert_below_checked_cost(inst, sol) == 3.0


def test_a_single_item_line_does_not_support_itself() -> None:
    alone = instance(_cell_item("L1", qty=1, tiers=5), types=(CELL,))
    pair = instance(_cell_item("L1", qty=2, tiers=5), types=(CELL,))
    assert lower_bound(alone).rows["floor"].cost == 1.0
    assert lower_bound(pair).rows["floor"].cost == 0.0  # one of the two may stand on the other
    sol = _cell_solution(at("L1#1", 0.0), at("L1#2", 0.0, z=1.0))
    assert _assert_below_checked_cost(pair, sol) == 1.0


def test_unlimited_load_supports_any_item_only_when_its_tiers_allow_a_stack() -> None:
    # H (500 kg, load 0) can rest on S only if S has no load limit and tiers >= 2.
    sturdy = instance(_cell_item("S", tiers=2, load=None), _cell_item("H", mass=500.0, load=0.0), types=(CELL,))
    no_stack = instance(_cell_item("S", tiers=1, load=None), _cell_item("H", mass=500.0, load=0.0), types=(CELL,))
    assert lower_bound(sturdy).rows["floor"].cost == 1.0  # only S is floor-forced
    assert lower_bound(no_stack).rows["floor"].cost == 2.0  # S has tiers 1, so H has no supporter
    sol = _cell_solution(at("S#1", 0.0), at("H#1", 0.0, z=1.0))
    assert _assert_below_checked_cost(sturdy, sol) == 1.0


def test_bound_round_trips_through_dict() -> None:
    inst = instance(line("L1", qty=3, L=3.0, W=3.0, H=0.1, mass=1.0, tiers=1))
    bound = lower_bound(inst)
    assert bound_from_dict(bound_to_dict(bound)) == bound
