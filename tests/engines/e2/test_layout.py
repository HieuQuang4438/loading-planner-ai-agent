"""Tests for E2's exact incremental checks (src/engines/e2/layout.py): collision with the delta gap,
support share, and the load/tier consequences of bridged boxes and boxes slid under an overhang.
Every accept/reject is cross-checked against the independent checker."""
from __future__ import annotations

import numpy as np

from src.checker import check
from src.engines.base import Piece
from src.engines.e2.layout import Layout
from src.model import Params, Placement
from tests.builders import instance, line, solution

BOX = 1.0


def piece(item: str, L: float = BOX, W: float = BOX, H: float = BOX, mass: float = 10.0, tiers: int = 5, load: float | None = None) -> Piece:
    return Piece(item, L, W, H, mass, False, tiers, load)


def put(layout: Layout, p: Piece, x: float, y: float = 0.0, z: float = 0.0) -> int:
    s = layout.stacking(x, y, z, p.L, p.W, p.H, p)
    assert s is not None, p.item
    return layout.add(p, "LWH", x, y, z, (p.L, p.W, p.H), s)


def checker_ok(pieces_at: list[tuple[Piece, float, float, float]], params: Params) -> set[int]:
    """Violated constraints when the given boxes, one line each, are checked as one container."""
    lines = [line(p.item, L=p.L, W=p.W, H=p.H, mass=p.mass, tiers=p.tiers, load=p.load) for p, *_ in pieces_at]
    placements = [Placement(f"{p.item}#1", 1, x, y, z, "LWH") for p, x, y, z in pieces_at]
    sol = solution(*placements)
    sol.params = params
    return {v.constraint for v in check(instance(*lines), sol, params).violations}


def one(layout: Layout, fn, x: float, y: float, z: float, a: float, b: float, *rest) -> bool:
    return bool(fn(np.array([x]), np.array([y]), np.array([z]), np.array([a]), np.array([b]), *rest)[0])


def test_delta_gap_is_required_beside_but_not_on_top():
    layout = Layout(4, delta=0.1)
    put(layout, piece("A"), 0.0)
    assert not one(layout, layout.collision_free, 1.05, 0.0, 0.0, 1.0, 1.0, 1.0)  # 0.05 < delta beside
    assert one(layout, layout.collision_free, 1.1, 0.0, 0.0, 1.0, 1.0, 1.0)  # exactly delta
    assert one(layout, layout.collision_free, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)  # stacked: may touch
    assert not one(layout, layout.collision_free, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0)  # overlap


def test_bridge_is_accepted_at_alpha_and_rejected_below():
    params = Params(delta=0.1, alpha=0.8)
    layout = Layout(4, delta=0.1)
    a, b = piece("A"), piece("B")
    put(layout, a, 0.0)
    put(layout, b, 1.1)
    # 2.1 m wide over two 1 m tops: 2/2.1 = 0.952 supported.
    assert one(layout, layout.supported, 0.0, 0.0, 1.0, 2.1, 1.0, 0.8, 10.0)
    assert not one(layout, layout.supported, 0.0, 0.0, 1.0, 2.1, 1.0, 0.96, 10.0)
    # Overhanging past the far end: 2/2.6 = 0.769 < 0.8.
    assert not one(layout, layout.supported, 0.0, 0.0, 1.0, 2.6, 1.0, 0.8, 10.0)
    assert checker_ok([(a, 0, 0, 0), (b, 1.1, 0, 0), (piece("C", L=2.1, H=0.5), 0, 0, 1)], params) == set()
    assert checker_ok([(a, 0, 0, 0), (b, 1.1, 0, 0), (piece("C", L=2.6, H=0.5), 0, 0, 1)], params) == {7}


def test_load_propagates_through_a_bridged_box_in_full():
    params = Params(delta=0.1, alpha=0.8)
    layout = Layout(4, delta=0.1)
    a, b = piece("A", load=100.0), piece("B", load=100.0)
    c = piece("C", L=2.1, H=0.5, mass=60.0)
    put(layout, a, 0.0)
    put(layout, b, 1.1)
    put(layout, c, 0.0, z=1.0)
    heavy, light = piece("D", H=0.5, mass=50.0), piece("D", H=0.5, mass=40.0)
    assert layout.stacking(0.0, 0.0, 1.5, 1.0, 1.0, 0.5, heavy) is None  # 60 + 50 > 100 on A and on B
    assert layout.stacking(0.0, 0.0, 1.5, 1.0, 1.0, 0.5, light) is not None
    assert checker_ok([(a, 0, 0, 0), (b, 1.1, 0, 0), (c, 0, 0, 1), (heavy, 0, 0, 1.5)], params) == {8}
    assert checker_ok([(a, 0, 0, 0), (b, 1.1, 0, 0), (c, 0, 0, 1), (light, 0, 0, 1.5)], params) == set()
    put(layout, light, 0.0, z=1.5)
    assert layout.load_left[0] == layout.load_left[1] == 0.0
    assert layout.up[0] == layout.up[1] == 3


def test_tiers_count_the_longest_chain_through_a_bridged_box():
    params = Params(delta=0.1, alpha=0.8)
    layout = Layout(4, delta=0.1)
    a, b = piece("A", tiers=2), piece("B", tiers=5)
    c = piece("C", L=2.1, H=0.5)
    put(layout, a, 0.0)
    put(layout, b, 1.1)
    put(layout, c, 0.0, z=1.0)
    d = piece("D", H=0.5)
    assert layout.stacking(1.1, 0.0, 1.5, 1.0, 1.0, 0.5, d) is None  # A - C - D: 3 > tiers_A = 2
    assert checker_ok([(a, 0, 0, 0), (b, 1.1, 0, 0), (c, 0, 0, 1), (d, 1.1, 0, 1.5)], params) == {8}


def test_box_slid_under_an_overhang_carries_what_rests_on_it():
    params = Params(delta=0.0, alpha=0.6)
    layout = Layout(4, delta=0.0)
    a = piece("A", load=100.0)
    c = piece("C", L=1.5, mass=30.0)  # 1/1.5 = 0.67 supported by A alone
    put(layout, a, 0.0)
    put(layout, c, 0.0, z=1.0)
    weak, strong = piece("B", load=20.0, tiers=5), piece("B", load=30.0, tiers=5)
    assert layout.stacking(1.0, 0.0, 0.0, 1.0, 1.0, 1.0, weak) is None  # C's 30 kg would rest on B
    assert checker_ok([(a, 0, 0, 0), (c, 0, 0, 1), (weak, 1.0, 0, 0)], params) == {8}
    s = layout.stacking(1.0, 0.0, 0.0, 1.0, 1.0, 1.0, strong)
    assert s is not None and s.above == (1,)
    assert checker_ok([(a, 0, 0, 0), (c, 0, 0, 1), (strong, 1.0, 0, 0)], params) == set()
    k = layout.add(strong, "LWH", 1.0, 0.0, 0.0, (1.0, 1.0, 1.0), s)
    assert layout.load_left[k] == 0.0 and layout.below[1] == [0, k] and layout.up[k] == 2


def test_tiers_of_the_boxes_above_grow_when_a_box_is_slid_under():
    params = Params(delta=0.0, alpha=0.6)
    layout = Layout(4, delta=0.0)
    a, c, e = piece("A"), piece("C", L=1.5, H=0.5, tiers=2), piece("E", H=0.5)
    put(layout, a, 0.0)
    put(layout, c, 0.0, z=1.0)  # rests on A only: a 2-tier chain, C's limit
    put(layout, e, 1.0)  # beside A, top at 0.5
    f = piece("F", L=0.4, H=0.5)  # on E, under C's overhang: E - F - C would be 3 > tiers_C = 2
    assert layout.stacking(1.0, 0.0, 0.5, 0.4, 1.0, 0.5, f) is None
    assert checker_ok([(a, 0, 0, 0), (c, 0, 0, 1), (e, 1.0, 0, 0), (f, 1.0, 0, 0.5)], params) == {8}


def test_support_prefilter_rejects_a_top_that_cannot_carry_the_piece():
    layout = Layout(4, delta=0.0)
    put(layout, piece("A", load=5.0, tiers=2), 0.0)
    assert not one(layout, layout.supported, 0.0, 0.0, 1.0, 1.0, 1.0, 0.8, 10.0)  # 10 kg > load 5
    assert one(layout, layout.supported, 0.0, 0.0, 1.0, 1.0, 1.0, 0.8, 5.0)
    put(layout, piece("B", H=0.5, mass=5.0), 0.0, z=1.0)  # A - B: A's 2 tiers used up
    assert layout.room[0] == 1 and layout.spare[0] == 0.0
    # The prefilter looks at direct supporters only: B has room, so the chain check catches A.
    assert one(layout, layout.supported, 0.0, 0.0, 1.5, 1.0, 1.0, 0.8, 0.0)
    assert layout.stacking(0.0, 0.0, 1.5, 1.0, 1.0, 0.4, piece("C", H=0.4, mass=0.0)) is None
