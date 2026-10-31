"""Tests for E2's extreme points (src/engines/e2/points.py): Crainic's projections in the frame
widened by delta, residual space, and removal of covered or dead points."""
from __future__ import annotations

import numpy as np

from src.engines.base import Piece
from src.engines.e2.layout import Layout
from src.engines.e2.points import ExtremePoints
from src.model import ContainerType

CT = ContainerType(id="C", L=4.0, W=2.0, H=3.0, door_w=2.0, door_h=3.0, max_mass=1e6, cost=1.0)


def put(layout: Layout, points: ExtremePoints, L: float, W: float, H: float, x: float, y: float = 0.0, z: float = 0.0) -> None:
    p = Piece(f"P{layout.n}", L, W, H, 1.0, False, 99, None)
    s = layout.stacking(x, y, z, L, W, H, p)
    assert s is not None
    k = layout.add(p, "LWH", x, y, z, (L, W, H), s)
    points.after_place(layout, k)


def as_set(points: ExtremePoints) -> set[tuple[float, float, float]]:
    return {(round(float(x), 6), round(float(y), 6), round(float(z), 6)) for x, y, z in zip(points.x, points.y, points.z)}


def test_first_box_yields_three_points_widened_by_delta():
    layout, points = Layout(4, delta=0.1), ExtremePoints(CT, min_side=0.1, min_height=0.1)
    put(layout, points, 1.0, 0.8, 1.2, 0.0)
    assert as_set(points) == {(1.1, 0.0, 0.0), (0.0, 0.9, 0.0), (0.0, 0.0, 1.2)}
    i = int(np.flatnonzero((points.x == 1.1))[0])
    assert (points.rx[i], points.ry[i], points.rz[i]) == (4.0 - 1.1, 2.0, 3.0)
    j = int(np.flatnonzero(points.z == 1.2)[0])
    assert np.isclose(points.rz[j], 1.8) and points.rx[j] == 4.0


def test_points_slide_down_to_the_nearest_top_or_the_floor():
    layout, points = Layout(4, delta=0.0), ExtremePoints(CT, min_side=0.1, min_height=0.1)
    put(layout, points, 1.0, 2.0, 1.0, 0.0)  # A: full width
    put(layout, points, 0.6, 1.0, 1.0, 0.0, z=1.0)  # B on A
    got = as_set(points)
    assert (0.6, 0.0, 1.0) in got  # B's +x corner slides down onto A's top
    assert (0.0, 1.0, 1.0) in got  # B's +y corner, already on A's top
    put(layout, points, 1.0, 1.0, 0.5, 1.0)  # C on the floor beside A
    # C's +x corner (2.0, 0, 0) is on the floor; its top corner (1.0, 0, 0.5) slides along -x to
    # A's face at x = 1.0, which it already touches.
    assert {(2.0, 0.0, 0.0), (1.0, 0.0, 0.5)} <= as_set(points)


def test_points_behind_a_box_slide_back_to_its_face():
    layout, points = Layout(4, delta=0.0), ExtremePoints(CT, min_side=0.1, min_height=0.1)
    put(layout, points, 1.0, 1.0, 2.0, 0.0)  # tall A
    put(layout, points, 1.0, 1.0, 1.0, 1.0)  # B beside it, lower
    # B's top corner (1.0, 0, 1.0) against A's face stays; its +y corner (1.0, 1.0, 0) slides along
    # -x to the wall (nothing at y = 1.0 in the way).
    assert (1.0, 0.0, 1.0) in as_set(points)
    assert (0.0, 1.0, 0.0) in as_set(points)


def test_covered_points_are_removed_and_rays_are_cut():
    layout, points = Layout(4, delta=0.0), ExtremePoints(CT, min_side=0.1, min_height=0.1)
    put(layout, points, 1.0, 1.0, 1.0, 0.0)
    put(layout, points, 1.0, 1.0, 1.0, 0.0, y=1.0)  # covers (0, 1, 0)
    got = as_set(points)
    assert (0.0, 1.0, 0.0) not in got
    put(layout, points, 1.0, 1.0, 1.0, 3.0)  # a box further along x cuts that point's +x ray
    i = int(np.flatnonzero((points.x == 1.0) & (points.y == 0.0) & (points.z == 0.0))[0])
    assert np.isclose(points.rx[i], 2.0)


def test_points_too_small_for_any_piece_are_dropped():
    layout, points = Layout(4, delta=0.0), ExtremePoints(CT, min_side=0.5, min_height=0.5)
    put(layout, points, 3.7, 1.0, 2.8, 0.0)
    got = as_set(points)
    assert (3.7, 0.0, 0.0) not in got  # 0.3 m left along x
    assert (0.0, 0.0, 2.8) not in got  # 0.2 m left above
    assert (0.0, 1.0, 0.0) in got
