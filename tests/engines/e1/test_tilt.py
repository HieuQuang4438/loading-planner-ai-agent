"""Tests for E1's tilt-first rule (probe; `src.engines.e1.orientation.tilt_first_orientation`):
a tippable piece lies on its lowest height when that is below `H`; otherwise the usual rule; layouts
pass the independent checker."""
from __future__ import annotations

import random

from src.checker import check
from src.engines.base import Piece, expand_pieces
from src.engines.e1 import pack_one, pack_one_tilt
from src.engines.e1.orientation import base_orientation, tilt_first_orientation
from src.model import ContainerType
from tests.builders import PARAMS, instance, line, solution

RNG = random.Random(0)
LOW = ContainerType(id="LOW", L=10.0, W=2.1, H=1.9, door_w=2.1, door_h=1.9, max_mass=10000.0, cost=1.0)


def _piece(L: float, W: float, H: float, tippable: bool = True) -> Piece:
    return Piece("A#1", L, W, H, 10.0, tippable, 5, None)


def test_lies_on_the_lowest_dim_below_h():
    assert tilt_first_orientation(_piece(1.0, 0.6, 1.0), LOW) in ("LHW", "HLW")  # W = 0.6 vertical
    assert base_orientation(_piece(1.0, 0.6, 1.0), LOW) in ("LWH", "WLH")


def test_keeps_the_usual_rule_when_tilting_is_not_lower_or_not_allowed():
    assert tilt_first_orientation(_piece(1.2, 1.1, 0.5), LOW) == base_orientation(_piece(1.2, 1.1, 0.5), LOW)
    assert tilt_first_orientation(_piece(1.0, 0.6, 1.0, False), LOW) in ("LWH", "WLH")


def test_tilted_layout_passes_the_checker_and_holds_more():
    inst = instance(line("A", qty=40, L=1.0, W=0.6, H=1.0, tippable=True), types=(LOW,))
    upright = pack_one(expand_pieces(inst), LOW, PARAMS, RNG)
    tilted = pack_one_tilt(expand_pieces(inst), LOW, PARAMS, RNG)
    assert len(tilted) > len(upright)
    sol = solution(*[p.__class__(p.item, 1, p.x, p.y, p.z, p.o) for p in tilted], containers=((1, "LOW"),))
    result = check(inst, sol, PARAMS)
    assert result.ok, result.violations[:3]
