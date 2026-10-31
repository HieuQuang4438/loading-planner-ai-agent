"""Tests for E2b's one-container core and its engine wrapper:
block sizes follow the space, tiers, load and mass; the floor fills before stacking; door, `delta` and
orientation follow E1, E2; every layout passes the independent checker, on hand-made and random lots."""
from __future__ import annotations

import random

import pytest

from src.checker import check
from src.engines.base import expand_pieces
from src.engines.e2b import pack_one, solve
from src.engines.e2b.pack import Config, PackStats
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, ItemLine, Params, Placement, Solution, UsedContainer
from tests.builders import PARAMS, instance, line, random_lot

RNG = random.Random(0)
DC20 = ContainerType(id="20DC", L=5.9, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=28000.0, cost=0.6)
ROOM = ContainerType(id="ROOM", L=4.0, W=2.0, H=3.0, door_w=2.0, door_h=3.0, max_mass=1e6, cost=1.0)
SHORT = ContainerType(id="SHORT", L=3.0, W=2.0, H=2.0, door_w=2.0, door_h=1.9, max_mass=3000.0, cost=1.0)
NO_GAP = Params(delta=0.0, alpha=0.8)


def _one(inst: Instance, ctype: ContainerType, params: Params = PARAMS, config: Config = Config()):
    stats = PackStats()
    placed = pack_one(expand_pieces(inst), ctype, params, RNG, config, stats)
    sol = Solution(inst.name, params, [UsedContainer(1, ctype.id)], [Placement(p.item, 1, p.x, p.y, p.z, p.o) for p in placed])
    return placed, stats, check(inst, sol, params)


def test_one_line_becomes_one_block_of_the_whole_space():
    inst = instance(line("A", qty=24, L=1.0, W=1.0, H=0.5, tiers=3), types=(ROOM,))
    placed, stats, result = _one(inst, ROOM, NO_GAP)
    assert result.ok, result.violations
    assert stats.blocks == [24]  # 4 x 2 x 3
    assert sorted({p.z for p in placed}) == [0.0, 0.5, 1.0]


def test_columns_are_delta_apart_and_layers_touch():
    inst = instance(line("A", qty=12, L=1.0, W=0.9, H=0.5, tiers=3), types=(ROOM,))
    placed, stats, result = _one(inst, ROOM, Params(delta=0.1, alpha=0.8))
    assert result.ok, result.violations
    assert stats.blocks == [12]  # 3 x 2 x 2
    assert sorted({round(p.x, 9) for p in placed}) == [0.0, 1.1, 2.2]
    assert sorted({round(p.y, 9) for p in placed}) == [0.0, 1.0]
    assert sorted({round(p.z, 9) for p in placed}) == [0.0, 0.5]


def test_layers_are_capped_by_tiers_and_by_load():
    inst = instance(line("A", qty=8, L=2.0, W=1.0, H=0.5, mass=10.0, tiers=2), types=(ROOM,))
    placed, stats, result = _one(inst, ROOM, NO_GAP)
    assert result.ok and len(placed) == 8 and max(p.z for p in placed) == 0.5
    inst = instance(line("A", qty=8, L=2.0, W=1.0, H=0.5, mass=10.0, tiers=9, load=10.0), types=(ROOM,))
    placed, stats, result = _one(inst, ROOM, NO_GAP)
    assert result.ok and len(placed) == 8 and max(p.z for p in placed) <= 0.5  # (nz - 1) * 10 <= 10: two layers


def test_single_layer_config_builds_flat_blocks_and_stacks_them_in_the_space_above():
    inst = instance(line("A", qty=24, L=1.0, W=1.0, H=0.5, tiers=3), types=(ROOM,))
    placed, stats, result = _one(inst, ROOM, NO_GAP, Config(nz_max=1))
    assert result.ok, result.violations
    assert stats.blocks == [8, 8, 8]
    assert sorted({p.z for p in placed}) == [0.0, 0.5, 1.0]


def test_floor_fills_before_stacking():
    ctype = ContainerType(id="C", L=3.0, W=1.0, H=2.0, door_w=1.0, door_h=2.0, max_mass=1e6, cost=1.0)
    inst = instance(line("A", qty=3, L=1.0, W=1.0, H=1.0, tiers=3), types=(ctype,))
    placed, _, result = _one(inst, ctype, NO_GAP)
    assert result.ok, result.violations
    assert sorted((p.x, p.z) for p in placed) == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]


def test_the_larger_measure_wins_the_space_and_area_differs_from_volume():
    # One space 2 x 1 x 2. A stacks two items in a 1.2 x 1 footprint (volume 2.4, base area 1.2); B is
    # a single flat item covering the floor of the space (base area 2.0, volume 0.4).
    ctype = ContainerType(id="C", L=2.0, W=1.0, H=2.0, door_w=1.0, door_h=2.0, max_mass=1e6, cost=1.0)
    inst = instance(
        line("A", qty=2, L=1.2, W=1.0, H=1.0, tiers=2),
        line("B", qty=1, L=2.0, W=1.0, H=0.2, tiers=1),
        types=(ctype,),
    )
    by_volume, _, r1 = _one(inst, ctype, NO_GAP, Config(measure="volume"))
    by_area, _, r2 = _one(inst, ctype, NO_GAP, Config(measure="area"))
    assert {v.constraint for v in r1.violations} <= {2} and {v.constraint for v in r2.violations} <= {2}
    first_volume = [p for p in by_volume if p.z == 0.0][0]
    first_area = [p for p in by_area if p.z == 0.0][0]
    assert first_volume.item.startswith("A") and first_area.item.startswith("B")


def test_block_shrinks_to_the_remaining_count():
    inst = instance(line("A", qty=5, L=1.0, W=1.0, H=1.0, tiers=1), types=(ROOM,))
    placed, stats, result = _one(inst, ROOM, NO_GAP)
    assert result.ok and len(placed) == 5 and sum(stats.blocks) == 5


def test_mass_limit_stops_the_block():
    ctype = ContainerType(id="C", L=6.0, W=2.0, H=1.0, door_w=2.0, door_h=1.0, max_mass=45.0, cost=1.0)
    inst = instance(line("A", qty=12, L=1.0, W=1.0, H=1.0, mass=10.0, tiers=1), types=(ctype,))
    placed, _, result = _one(inst, ctype, NO_GAP)
    assert len(placed) == 4 and {v.constraint for v in result.violations} <= {2}


def test_turns_only_where_the_door_allows_and_keeps_the_piece_upright():
    narrow = ContainerType(id="ND", L=6.0, W=2.35, H=2.39, door_w=2.0, door_h=2.28, max_mass=1e5, cost=1.0)
    inst = instance(line("A", qty=5, L=2.2, W=1.0, H=1.0, tiers=1), types=(narrow,))
    placed, _, result = _one(inst, narrow)
    assert {v.constraint for v in result.violations} <= {2}
    assert len(placed) == 4 and all(p.o == "LWH" for p in placed)
    inst = instance(line("A", qty=4, L=1.0, W=0.8, H=1.2, tippable=True), types=(DC20,))
    placed, _, result = _one(inst, DC20)
    assert result.ok and all(p.o in UPRIGHT_ORIENTATIONS for p in placed)


def test_too_tall_piece_is_tilted_and_a_piece_fitting_no_way_is_left_out():
    inst = instance(line("A", qty=3, L=1.0, W=0.9, H=2.3, tippable=True), types=(DC20,))
    placed, _, result = _one(inst, DC20)
    assert result.ok and len(placed) == 3 and all(p.o in ("LHW", "HLW") for p in placed)
    inst = instance(line("A", qty=1, L=1.0, W=1.0, H=2.3, tippable=False), types=(DC20,))
    assert pack_one(expand_pieces(inst), DC20, PARAMS, RNG) == []


def test_upper_blocks_stand_on_the_tops_below_with_enough_support():
    inst = instance(
        line("A", qty=2, L=1.5, W=2.0, H=1.0, mass=10.0, load=100.0, tiers=2),
        line("B", qty=2, L=1.0, W=1.0, H=1.0, mass=10.0, tiers=2),
        types=(SHORT,),
    )
    placed, _, result = _one(inst, SHORT, NO_GAP)
    assert {v.constraint for v in result.violations} <= {2}
    assert any(p.z > 0 for p in placed)


def test_deterministic():
    inst = random_lot(7)
    a = pack_one(expand_pieces(inst), DC20, PARAMS, random.Random(1))
    b = pack_one(expand_pieces(inst), DC20, PARAMS, random.Random(2))
    assert a == b


def test_bad_measure_is_rejected():
    with pytest.raises(ValueError):
        Config(measure="weight")


def _stress_lot(seed: int) -> Instance:
    rng = random.Random(seed)
    lines = []
    for n in range(rng.randint(1, 8)):
        lines.append(ItemLine(
            id=f"L{n + 1}", qty=rng.randint(1, 40),
            L=round(rng.uniform(0.3, 1.2), 2), W=round(rng.uniform(0.3, 1.0), 2), H=round(rng.uniform(0.2, 0.9), 2),
            mass=round(rng.uniform(5, 120), 1), tippable=rng.random() < 0.3, tiers=rng.randint(1, 5),
            load=rng.choice([None, 0.0, round(rng.uniform(20, 600), 1)]),
        ))
    return Instance(name=f"stress-{seed}", container_types=(SHORT,), items=tuple(lines))


@pytest.mark.parametrize("params", [Params(0.05, 0.8), Params(0.0, 0.8), Params(0.1, 0.5), Params(0.02, 1.0)])
@pytest.mark.parametrize("config", [Config(), Config(nz_max=1, measure="area")])
def test_random_lots_always_pass_the_checker(params, config):
    """Many random small lots: constraints 7 and 8 are where a per-block formula can go wrong, and the
    checker (which the engine never imports) is the arbiter. Unplaced items (constraint 2) are fine."""
    stacked = 0
    for seed in range(60):
        inst = _stress_lot(seed)
        placed, _, result = _one(inst, SHORT, params, config)
        assert {v.constraint for v in result.violations} <= {2}, (seed, result.violations[:3])
        stacked += sum(1 for p in placed if p.z > 1e-6)
    assert stacked > 0 or config.nz_max == 1


def test_random_pallet_lots_on_the_standard_containers_pass_the_checker():
    from tests.builders import STANDARD_CONTAINERS

    for seed in range(15):
        inst = random_lot(seed)
        for ctype in STANDARD_CONTAINERS:
            _, _, result = _one(inst, ctype)
            assert {v.constraint for v in result.violations} <= {2}, (seed, ctype.id, result.violations[:3])


def test_solve_is_valid_and_reports_the_blocks_of_the_solution():
    inst = random_lot(3, n_lines=5, max_qty=12)
    sol, diag = solve(inst, PARAMS, time_limit=30.0, seed=1)
    assert check(inst, sol, PARAMS).ok
    assert diag["engine"] == "e2b"
    assert diag["blocks"] * diag["mean_items_per_block"] == pytest.approx(inst.n_items, abs=0.01 * diag["blocks"])
    assert diag["single_item_blocks"] <= diag["blocks"] <= inst.n_items
    assert diag["pack_one_calls"] >= 1 and diag["blocks_all_calls"] >= diag["blocks"]
    assert diag["spaces_generated"] >= 1 and diag["spaces_peak"] >= 1 and diag["spaces_examined"] >= 1
