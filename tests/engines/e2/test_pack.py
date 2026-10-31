"""Tests for E2's one-container core and its engine wrapper:
every layout passes the independent checker; the lowest point goes first and the better of the two
turn passes is kept; bridging and overhang are used when allowed; door, mass and delta respected;
deterministic."""
from __future__ import annotations

import random

from src.checker import check
from src.engines.base import Piece, expand_pieces
from src.engines.e2 import pack_one, solve
from src.engines.e2.layout import Layout
from src.engines.e2.pack import _best_spot
from src.engines.e2.points import ExtremePoints
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, Params
from tests.builders import PARAMS, instance, line, solution

RNG = random.Random(0)
DC20 = ContainerType(id="20DC", L=5.9, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=28000.0, cost=0.6)
DC40 = ContainerType(id="40DC", L=12.03, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=26700.0, cost=1.0)
HC40 = ContainerType(id="40HC", L=12.03, W=2.35, H=2.69, door_w=2.34, door_h=2.58, max_mass=26500.0, cost=1.05)
SHORT = ContainerType(id="SHORT", L=3.0, W=2.0, H=2.0, door_w=2.0, door_h=1.9, max_mass=1e4, cost=1.0)


def _check_one(inst: Instance, ctype: ContainerType, params: Params = PARAMS):
    placed = pack_one(expand_pieces(inst), ctype, params, RNG)
    sol = solution(*[p.__class__(p.item, 1, p.x, p.y, p.z, p.o) for p in placed], containers=((1, ctype.id),))
    return placed, check(inst, sol, params)


def test_one_container_layout_passes_the_checker_apart_from_unplaced_items():
    inst = instance(
        line("A", qty=6, L=1.8, W=1.2, H=0.6, mass=200.0, load=500.0, tiers=3),
        line("B", qty=8, L=1.0, W=0.8, H=0.5, mass=50.0, load=100.0, tiers=4),
        line("C", qty=10, L=0.6, W=0.5, H=0.4, mass=20.0, load=0.0, tiers=5),
        types=(SHORT,),
    )
    placed, result = _check_one(inst, SHORT)
    assert placed
    assert {v.constraint for v in result.violations} <= {2}
    assert any(p.z > 0 for p in placed)


def test_floor_fills_before_stacking():
    # Residual space ties the floor point (1, 0, 0) with the top point (0, 0, 1) and broke the tie by
    # x, stacking; the lowest point goes first.
    ctype = ContainerType(id="C", L=3.0, W=1.0, H=2.0, door_w=1.0, door_h=2.0, max_mass=1e6, cost=1.0)
    inst = instance(line("A", qty=3, L=1.0, W=1.0, H=1.0, tiers=3), types=(ctype,))
    placed, result = _check_one(inst, ctype, Params(delta=0.0, alpha=0.8))
    assert result.ok, result.violations
    assert sorted((p.x, p.z) for p in placed) == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]


def test_turned_pass_kept_when_it_carries_more():
    # B-one-line-2210's base: 1.6 m along x leaves room for 3
    # in a 20DC, turned (1.2 m along x) for 4. Neither way fits two across the 2.35 m width.
    inst = instance(line("A", qty=5, L=1.6, W=1.2, H=2.0, tiers=1), types=(DC20,))
    placed, result = _check_one(inst, DC20, Params(delta=0.05, alpha=0.8))
    assert {v.constraint for v in result.violations} <= {2}
    assert len(placed) == 4
    assert all(p.o == "WLH" for p in placed)


def test_unturned_pass_kept_when_it_carries_more():
    # 1.2 m along x fits 4 in a 5.0 m container, turned (1.6 m along x) only 3.
    ctype = ContainerType(id="C", L=5.0, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=1e6, cost=1.0)
    inst = instance(line("A", qty=5, L=1.2, W=1.6, H=2.0, tiers=1), types=(ctype,))
    placed, result = _check_one(inst, ctype, Params(delta=0.05, alpha=0.8))
    assert {v.constraint for v in result.violations} <= {2}
    assert len(placed) == 4
    assert all(p.o == "LWH" for p in placed)


def test_best_spot_bridges_two_tops_when_support_reaches_alpha():
    ctype = ContainerType(id="C", L=2.1, W=1.0, H=2.0, door_w=1.0, door_h=2.0, max_mass=1e6, cost=1.0)
    layout, points = Layout(3, delta=0.1), ExtremePoints(ctype, min_side=0.5, min_height=0.5)
    for x in (0.0, 1.1):
        p = Piece(f"S{x}", 1.0, 1.0, 1.0, 10.0, False, 5, None)
        k = layout.add(p, "LWH", x, 0.0, 0.0, (1.0, 1.0, 1.0), layout.stacking(x, 0.0, 0.0, 1.0, 1.0, 1.0, p))
        points.after_place(layout, k)
    top = Piece("T", 2.1, 1.0, 0.5, 10.0, False, 5, None)
    ways = [("LWH", 2.1, 1.0, 0.5)]
    spot = _best_spot(layout, points, top, ways, alpha=0.8)  # 2 / 2.1 = 0.952 supported
    assert spot is not None
    p, _, stacking = spot
    assert (points.x[p], points.z[p]) == (0.0, 1.0) and stacking.below == (0, 1)
    assert _best_spot(layout, points, top, ways, alpha=0.96) is None


def test_overhang_lets_two_near_equal_bases_stack():
    # T-2012's case: bases 1 mm apart each way, so neither
    # fits inside the other's top; E1 cannot stack them, E2 overhangs by 1 mm.
    tiny = ContainerType(id="T", L=1.3, W=1.1, H=2.0, door_w=1.1, door_h=2.0, max_mass=1e4, cost=1.0)
    inst = instance(
        line("A", L=1.209, W=1.007, H=0.9, mass=100.0, load=0.0),
        line("B", L=1.208, W=1.008, H=0.9, mass=100.0, load=100.0),
        types=(tiny,),
    )
    placed, result = _check_one(inst, tiny)
    assert result.ok, result.violations
    assert len(placed) == 2
    sol, diag = solve(inst, PARAMS, time_limit=10.0, seed=1)
    assert len(sol.containers) == 1 and diag["overhanging_items"] == 1 and diag["bridged_items"] == 0


def test_upright_piece_is_never_tilted_even_if_tippable():
    inst = instance(line("A", qty=4, L=1.0, W=0.8, H=1.2, tippable=True), types=(DC20,))
    placed, result = _check_one(inst, DC20)
    assert result.ok, result.violations
    assert all(p.o in UPRIGHT_ORIENTATIONS for p in placed)


def test_piece_too_tall_for_the_door_is_tilted_onto_its_lowest_feasible_side():
    inst = instance(line("A", qty=3, L=1.0, W=0.9, H=2.3, tippable=True), types=(DC20,))
    placed, result = _check_one(inst, DC20)
    assert result.ok, result.violations
    assert len(placed) == 3
    assert all(p.o in ("LHW", "HLW") for p in placed)


def test_piece_that_fits_no_way_is_left_out():
    inst = instance(line("A", qty=1, L=1.0, W=1.0, H=2.3, tippable=False), types=(DC20,))
    assert pack_one(expand_pieces(inst), DC20, PARAMS, RNG) == []


def test_a_piece_only_turns_where_it_still_passes_the_door():
    narrow_door = ContainerType(id="ND", L=6.0, W=2.35, H=2.39, door_w=2.0, door_h=2.28, max_mass=1e5, cost=1.0)
    # 2.2 m long: through the door only with L along x. Turned, a fifth would fit the interior.
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


def test_delta_separates_pieces_side_by_side_but_not_stacked():
    params = Params(delta=0.2, alpha=0.8)
    inst = instance(line("A", qty=12, L=0.9, W=0.9, H=0.9, tiers=2), types=(SHORT,))
    placed, result = _check_one(inst, SHORT, params)
    assert {v.constraint for v in result.violations} <= {2}
    assert any(p.z > 0 for p in placed)
    floor = [(p.x, p.y) for p in placed if p.z == 0]
    for i, a in enumerate(floor):
        for b in floor[i + 1:]:
            assert abs(a[0] - b[0]) >= 1.1 - 1e-9 or abs(a[1] - b[1]) >= 1.1 - 1e-9


def test_solve_is_checker_valid_on_random_small_lots_and_ignores_the_seed():
    rng = random.Random(7)
    types = (DC20, DC40, HC40)
    bridged = 0
    for n in range(25):
        params = Params(delta=rng.choice([0.0, 0.05]), alpha=rng.choice([0.5, 0.8, 1.0]))
        lines = []
        for j in range(rng.randint(1, 5)):
            lines.append(line(
                f"L{j}", qty=rng.randint(1, 30),
                L=round(rng.uniform(0.3, 2.4), 2), W=round(rng.uniform(0.3, 2.3), 2), H=round(rng.uniform(0.2, 1.5), 2),
                mass=round(rng.uniform(5, 900), 1), tippable=rng.random() < 0.4, tiers=rng.randint(1, 6),
                load=rng.choice([None, 0.0, round(rng.uniform(0, 2000), 1)]),
            ))
        inst = Instance(name="test", container_types=types, items=tuple(lines))
        try:
            sol, diag = solve(inst, params, time_limit=10.0, seed=1)
        except ValueError:
            continue  # a line that fits no container type (random dims); validate_instance would reject it
        result = check(inst, sol, params)
        assert result.ok, (n, params, result.violations[:5])
        again, _ = solve(inst, params, time_limit=10.0, seed=99)
        assert again.placements == sol.placements and again.containers == sol.containers
        assert diag["engine"] == "e2"
        bridged += diag["bridged_items"]
    assert bridged > 0  # the random lots do exercise bridging
