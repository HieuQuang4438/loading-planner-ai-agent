"""E2's orient mode: every allowed orientation is a way; off, the ways are as before."""
from __future__ import annotations

import random

from src.checker import check
from src.engines.base import expand_pieces
from src.engines.e2 import pack_one_orient, solve_orient
from src.engines.e2.pack import _ways
from src.model import ALL_ORIENTATIONS, UPRIGHT_ORIENTATIONS, ContainerType, is_tipped
from tests.builders import PARAMS, instance, line, random_lot, solution

LOW = ContainerType(id="LOW", L=10.0, W=2.1, H=1.9, door_w=2.1, door_h=1.9, max_mass=10000.0, cost=1.0)


def test_off_gives_the_base_way_and_its_turn_only():
    assert [w[0] for w in _ways(1.0, 0.6, 1.0, ALL_ORIENTATIONS, LOW)] == ["LWH", "WLH"]


def test_on_adds_every_allowed_orientation_with_its_turn():
    ways = _ways(1.0, 0.6, 1.0, ALL_ORIENTATIONS, LOW, True)
    assert {w[0] for w in ways} == set(ALL_ORIENTATIONS)
    assert ways[0][0] == "LWH"  # base way first
    assert {w[0] for w in _ways(1.0, 0.6, 1.0, UPRIGHT_ORIENTATIONS, LOW, True)} == {"LWH", "WLH"}
    four = ("LWH", "WLH", "LHW", "HLW")
    assert {w[0] for w in _ways(1.0, 0.6, 1.0, four, LOW, True)} == set(four)


def test_on_skips_ways_that_miss_the_door():
    narrow = ContainerType(id="D", L=10.0, W=2.1, H=1.9, door_w=0.9, door_h=1.9, max_mass=1e4, cost=1.0)
    ways = _ways(1.0, 0.6, 1.0, ALL_ORIENTATIONS, narrow, True)
    assert ways and all(b <= 0.9 + 1e-9 and c <= 1.9 + 1e-9 for _, _, b, c in ways)


def test_orient_layout_is_checker_valid():
    inst = random_lot(5)
    ctype = inst.container_types[1]
    placed = pack_one_orient(expand_pieces(inst), ctype, PARAMS, random.Random(0))
    assert placed
    sol = solution(*[p.__class__(p.item, 1, p.x, p.y, p.z, p.o) for p in placed], containers=((1, ctype.id),))
    result = check(inst, sol, PARAMS)
    assert not [v for v in result.violations if v.constraint != 2]  # items left out are not placed; nothing else wrong


def test_engine_is_checker_valid_and_tips_a_piece():
    inst = random_lot(5)
    sol, diag = solve_orient(inst, PARAMS, 1e5, 1)
    assert check(inst, sol, PARAMS).ok
    assert diag["engine"] == "e2-orient" and any(is_tipped(p.o) for p in sol.placements)


def test_orient_respects_a_restricted_set():
    inst = instance(
        line("A", qty=30, L=1.0, W=0.6, H=1.0, tippable=True, orientations=UPRIGHT_ORIENTATIONS), types=(LOW,)
    )
    placed = pack_one_orient(expand_pieces(inst), LOW, PARAMS, random.Random(0))
    assert placed and not any(is_tipped(p.o) for p in placed)
