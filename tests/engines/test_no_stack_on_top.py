"""a piece no one may load (`load = 0`) but allowed in a stack (`tiers = 2`) may still sit on
top of another piece. Each core that builds stacks must use that when it is the only way to fit."""
from __future__ import annotations

import random

import pytest

from src.checker import check
from src.engines import e1, e2, e2b
from src.engines.base import expand_pieces
from src.model import ContainerType, Placement
from tests.builders import PARAMS, instance, line, solution

ONE_SPOT = ContainerType(id="ONE", L=1.1, W=1.1, H=2.0, door_w=1.1, door_h=2.0, max_mass=1000.0, cost=1.0)


@pytest.mark.parametrize("pack_one", [e1.pack_one, e2.pack_one, e2b.pack_one], ids=["e1", "e2", "e2b"])
def test_load_zero_piece_sits_on_top_when_tiers_allow(pack_one):
    inst = instance(
        line("A", L=1.0, W=1.0, H=1.0, mass=50.0, tiers=5),
        line("B", L=1.0, W=1.0, H=0.9, mass=20.0, tiers=2, load=0.0),
        types=(ONE_SPOT,),
    )
    placed = pack_one(expand_pieces(inst), ONE_SPOT, PARAMS, random.Random(0))
    assert {p.item for p in placed} == {"A#1", "B#1"}
    on_top = next(p for p in placed if p.item == "B#1")
    assert on_top.z > 0
    sol = solution(*[Placement(p.item, 1, p.x, p.y, p.z, p.o) for p in placed], containers=((1, "ONE"),))
    result = check(inst, sol, PARAMS)
    assert result.ok, result.violations[:3]


@pytest.mark.parametrize("pack_one", [e1.pack_one, e2.pack_one, e2b.pack_one], ids=["e1", "e2", "e2b"])
def test_tiers_one_piece_stays_on_the_floor(pack_one):
    inst = instance(
        line("A", L=1.0, W=1.0, H=1.0, mass=50.0, tiers=5),
        line("B", L=1.0, W=1.0, H=0.9, mass=20.0, tiers=1, load=0.0),
        types=(ONE_SPOT,),
    )
    placed = pack_one(expand_pieces(inst), ONE_SPOT, PARAMS, random.Random(0))
    assert len(placed) == 1
