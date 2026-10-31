"""E1's dense orientation rule: the allowed orientation with the most pieces per m2 of floor."""
from __future__ import annotations

import random

from src.checker import check
from src.engines import base, e1, e2
from src.engines.base import Piece, expand_pieces
from src.engines.e1 import pack_one_orient_dense
from src.engines.e1.orientation import base_orientation, dense_orientation
from src.model import ContainerType, is_tipped
from tests.builders import PARAMS, instance, line, random_lot, solution

LOW = ContainerType(id="LOW", L=10.0, W=2.1, H=1.9, door_w=2.1, door_h=1.9, max_mass=10000.0, cost=1.0)
DELTA = 0.1


def _piece(L, W, H, tiers=5, load=None, mass=10.0, tippable=True, orientations=None) -> Piece:
    return Piece("A#1", L, W, H, mass, tippable, tiers, load, orientations)


def _dense(piece: Piece) -> str:
    code = dense_orientation(piece, LOW, DELTA)
    assert code is not None
    return code


def test_registered():
    assert "e5-orient" in base.names()  # E1 and E2 with orientations are its cores, not registered here


def test_lies_down_when_it_stacks_more_per_floor():
    # Upright 1 high on 0.77 m2 (1.30 per m2); lying on W = 0.6 three high on 1.21 m2 (2.48 per m2).
    piece = _piece(1.0, 0.6, 1.0)
    code = _dense(piece)
    assert is_tipped(code) and piece.dims(code)[2] == 0.6


def test_stands_on_edge_when_tiers_are_short_and_the_footprint_shrinks():
    # Board 1 x 1 x 0.2, 2 tiers: upright 2 / 1.21 = 1.65; on edge 1 / (1.1 * 0.3) = 3.03.
    piece = _piece(1.0, 1.0, 0.2, tiers=2)
    code = _dense(piece)
    assert is_tipped(code) and piece.dims(code)[2] == 1.0


def test_upright_wins_a_tie():
    assert _dense(_piece(1.0, 1.0, 1.0, tiers=1)) == "LWH"
    rigid = _piece(1.0, 0.6, 1.0, tippable=False)
    assert _dense(rigid) == base_orientation(rigid, LOW)


def test_load_and_tiers_limit_the_pieces_counted():
    assert is_tipped(_dense(_piece(1.0, 0.6, 1.0, load=10.0)))  # one piece may sit on it: n = 2 lying
    assert not is_tipped(_dense(_piece(1.0, 0.6, 1.0, load=0.0)))  # nothing on it: n = 1 either way
    assert not is_tipped(_dense(_piece(1.0, 0.6, 1.0, tiers=1)))


def test_only_allowed_codes_are_used():
    assert _dense(_piece(1.0, 0.6, 1.0, orientations=("LWH", "WLH"))) in ("LWH", "WLH")
    assert _dense(_piece(1.0, 0.6, 1.0, orientations=("LHW", "HLW"))) in ("LHW", "HLW")
    assert _dense(_piece(1.0, 0.6, 1.0, orientations=("WHL", "HWL"))) in ("WHL", "HWL")


def test_none_when_no_allowed_orientation_fits():
    short = ContainerType(id="T", L=1.5, W=1.5, H=1.9, door_w=1.5, door_h=1.9, max_mass=1e4, cost=1.0)
    assert dense_orientation(_piece(2.0, 1.8, 1.0, orientations=("LWH", "WLH")), short, DELTA) is None


def test_dense_layout_holds_more_and_passes_the_checker():
    inst = instance(line("A", qty=40, L=1.0, W=0.6, H=1.0, tippable=True), types=(LOW,))
    placed = pack_one_orient_dense(expand_pieces(inst), LOW, PARAMS, random.Random(0))
    assert len(placed) > 27
    sol = solution(*[p.__class__(p.item, 1, p.x, p.y, p.z, p.o) for p in placed], containers=((1, "LOW"),))
    assert check(inst, sol, PARAMS).ok


def test_engines_are_checker_valid_and_able_to_tip():
    inst = random_lot(5)
    for name, solve in (("e1-orient-dense", e1.solve_orient_dense), ("e2-orient", e2.solve_orient)):
        sol, _ = solve(inst, PARAMS, 1e5, 1)
        assert check(inst, sol, PARAMS).ok, name
        assert any(is_tipped(p.o) for p in sol.placements), name


