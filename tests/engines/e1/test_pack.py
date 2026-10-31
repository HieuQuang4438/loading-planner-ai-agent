"""Tests for E1's one-container core and its engine wrapper:
every layout passes the independent checker; tilts only when forced; door, mass and delta respected."""
from __future__ import annotations

import random

from src.checker import check
from src.engines.base import expand_pieces
from src.engines.e1 import pack_one, solve
from src.engines.e1.orientation import base_orientation
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, Params
from tests.builders import BOX, PARAMS, instance, line, solution

RNG = random.Random(0)
DC20 = ContainerType(id="20DC", L=5.9, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=28000.0, cost=0.6)
DC40 = ContainerType(id="40DC", L=12.03, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=26700.0, cost=1.0)
HC40 = ContainerType(id="40HC", L=12.03, W=2.35, H=2.69, door_w=2.34, door_h=2.58, max_mass=26500.0, cost=1.05)


def _check_one(inst: Instance, ctype: ContainerType, params: Params = PARAMS):
    placed = pack_one(expand_pieces(inst), ctype, params, RNG)
    sol = solution(*[p.__class__(p.item, 1, p.x, p.y, p.z, p.o) for p in placed], containers=((1, ctype.id),))
    return placed, check(inst, sol, params)


def test_one_container_layout_passes_the_checker_apart_from_unplaced_items():
    inst = instance(
        line("A", qty=6, L=1.8, W=1.2, H=0.6, mass=200.0, load=500.0, tiers=3),
        line("B", qty=8, L=1.0, W=0.8, H=0.5, mass=50.0, load=100.0, tiers=4),
        line("C", qty=10, L=0.6, W=0.5, H=0.4, mass=20.0, load=0.0, tiers=5),
    )
    placed, result = _check_one(inst, BOX)
    assert placed
    assert {v.constraint for v in result.violations} <= {2}  # only "not placed", if anything
    assert any(p.z > 0 for p in placed)  # it did stack


def test_upright_piece_is_never_tilted_even_if_tippable():
    inst = instance(line("A", qty=4, L=1.0, W=0.8, H=1.2, tippable=True), types=(DC20,))
    placed, result = _check_one(inst, DC20)
    assert result.ok, result.violations
    assert all(p.o in UPRIGHT_ORIENTATIONS for p in placed)


def test_piece_too_tall_for_the_door_is_tilted_onto_its_lowest_feasible_side():
    # Standing 2.3 m > door 2.28 m. Lying on W (0.9) is lower than lying on L (1.0).
    inst = instance(line("A", qty=3, L=1.0, W=0.9, H=2.3, tippable=True), types=(DC20,))
    placed, result = _check_one(inst, DC20)
    assert result.ok, result.violations
    assert len(placed) == 3
    assert all(p.o in ("LHW", "HLW") for p in placed)


def test_piece_that_fits_no_way_is_left_out():
    inst = instance(line("A", qty=1, L=1.0, W=1.0, H=2.3, tippable=False), types=(DC20,))
    assert base_orientation(expand_pieces(inst)[0], DC20) is None
    assert pack_one(expand_pieces(inst), DC20, PARAMS, RNG) == []


def test_a_column_only_turns_where_its_footprint_still_passes_the_door():
    narrow_door = ContainerType(id="ND", L=6.0, W=2.35, H=2.39, door_w=2.0, door_h=2.28, max_mass=1e5, cost=1.0)
    # 2.2 m long: through the door only with L along x, which fits 2 x 2 on this floor. Turned, a
    # fifth would fit the interior (x 4.6-5.6, y 0-2.2) but not the 2.0 m door.
    inst = instance(line("A", qty=5, L=2.2, W=1.0, H=1.0, tiers=1), types=(narrow_door,))
    placed, result = _check_one(inst, narrow_door)
    assert {v.constraint for v in result.violations} <= {2}
    assert len(placed) == 4
    assert all(p.o == "LWH" for p in placed)


def test_container_mass_limit_is_respected():
    light = ContainerType(id="LIGHT", L=10.0, W=2.0, H=2.0, door_w=2.0, door_h=1.9, max_mass=25.0, cost=1.0)
    inst = instance(line("A", qty=5, mass=10.0, H=0.3), types=(light,))
    placed, _ = _check_one(inst, light)
    assert len(placed) == 2


def test_delta_separates_columns_but_not_stacked_pieces():
    params = Params(delta=0.2, alpha=0.8)
    inst = instance(line("A", qty=12, L=0.9, W=0.9, H=0.9, tiers=2))
    placed, result = _check_one(inst, BOX, params)
    assert {v.constraint for v in result.violations} <= {2}
    assert any(p.z > 0 for p in placed)


def test_solve_is_checker_valid_on_random_small_lots_and_ignores_the_seed():
    rng = random.Random(7)
    types = (DC20, DC40, HC40)
    params = Params(delta=0.05, alpha=0.8)
    for n in range(25):
        lines = []
        for j in range(rng.randint(1, 5)):
            lines.append(line(
                f"L{j}", qty=rng.randint(1, 30),
                L=round(rng.uniform(0.3, 2.4), 2), W=round(rng.uniform(0.3, 2.3), 2), H=round(rng.uniform(0.2, 2.5), 2),
                mass=round(rng.uniform(5, 900), 1), tippable=rng.random() < 0.4, tiers=rng.randint(1, 6),
                load=rng.choice([None, 0.0, round(rng.uniform(0, 2000), 1)]),
            ))
        inst = Instance(name="test", container_types=types, items=tuple(lines))
        try:
            sol, diag = solve(inst, params, time_limit=10.0, seed=1)
        except ValueError:
            continue  # a line that fits no container type (random dims); validate_instance would reject it
        result = check(inst, sol, params)
        assert result.ok, (n, result.violations[:5])
        again, _ = solve(inst, params, time_limit=10.0, seed=99)
        assert again.placements == sol.placements and again.containers == sol.containers
        assert diag["engine"] == "e1" and diag["columns"] >= 1
