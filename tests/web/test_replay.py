"""Tests for the replay order (src.web.replay)."""
from __future__ import annotations


import pytest

from tests.web.support import sample_path
from src.checker import check
from src.engines import e1, e2, e5
from src.formats import read_instance
from src.model import Params
from src.web.replay import ENGINE_ORDER, REBUILT_ORDER, boxes_of, replay_orders, supporters, supporters_first
from tests.builders import at, instance, line, solution

ENGINE_TIME_LIMIT = 2.0
DEFAULTS = Params(delta=0.05, alpha=0.8)

# e1 and e2 are E5's cores, not registered engines here (src/engines/__init__.py)
SOLVERS = {"e1": e1.solve, "e2": e2.solve, "e5": e5.solve}
SAMPLE_NAMES = ("sample-small", "sample-mixed")


def _rests_valid(inst, sol, order) -> bool:
    boxes = boxes_of(inst, sol)
    for k, replay in order.items():
        members = list(replay.indices)
        if not supporters_first(boxes, members, supporters(boxes, members)):
            return False
        if sorted(members) != sorted(i for i, p in enumerate(sol.placements) if p.k == k):
            return False
    return True


def test_engine_order_is_kept_when_supporters_come_first():
    inst = instance(line("A", qty=2, L=1.0, W=1.0, H=1.0, mass=1.0))
    sol = solution(at("A#1", 0.0, z=0.0), at("A#2", 0.0, z=1.0))

    order = replay_orders(inst, sol)

    assert order[1].source == ENGINE_ORDER
    assert order[1].indices == (0, 1)


def test_supported_piece_listed_before_its_supporter_is_rebuilt_bottom_up():
    inst = instance(line("A", qty=2, L=1.0, W=1.0, H=1.0, mass=1.0))
    sol = solution(at("A#1", 0.0, z=1.0), at("A#2", 0.0, z=0.0))  # the upper piece is listed first

    order = replay_orders(inst, sol)

    assert order[1].source == REBUILT_ORDER
    assert order[1].indices == (1, 0)
    assert _rests_valid(inst, sol, order)


def test_rebuilt_order_sorts_by_z_then_x_then_y():
    inst = instance(line("A", qty=4, L=1.0, W=1.0, H=1.0, mass=1.0))
    sol = solution(
        at("A#1", 0.0, y=0.0, z=1.0), at("A#2", 3.0, y=0.0), at("A#3", 0.0, y=1.0), at("A#4", 0.0, y=0.0),
    )

    order = replay_orders(inst, sol)

    assert order[1].source == REBUILT_ORDER
    assert order[1].indices == (3, 2, 1, 0)  # z=0: (x0,y0), (x0,y1), (x3,y0); then z=1


def test_each_container_gets_its_own_order():
    inst = instance(line("A", qty=3, L=1.0, W=1.0, H=1.0, mass=1.0))
    sol = solution(
        at("A#1", 0.0, z=1.0, k=1), at("A#2", 0.0, z=0.0, k=1), at("A#3", 0.0, z=0.0, k=2),
        containers=((1, "BOX"), (2, "BOX")),
    )

    order = replay_orders(inst, sol)

    assert order[1].source == REBUILT_ORDER
    assert order[2].source == ENGINE_ORDER and order[2].indices == (2,)


@pytest.mark.parametrize("engine", ["e1", "e2", "e5"])
@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_engine_solutions_on_sample_lots_replay_with_supporters_first(engine, name):
    inst = read_instance(sample_path(name))
    sol, _ = SOLVERS[engine](inst, DEFAULTS, ENGINE_TIME_LIMIT, 1)
    assert check(inst, sol, DEFAULTS).ok

    order = replay_orders(inst, sol)

    assert set(order) == {used.k for used in sol.containers}
    assert _rests_valid(inst, sol, order)
