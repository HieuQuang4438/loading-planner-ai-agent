"""Tests for the maxrects (best-short-side-fit) floor packer used by E1."""
from __future__ import annotations

import random

from src.engines.e1.maxrects import MaxRects

EPS = 1e-9


def _disjoint(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax + aw <= bx + EPS or bx + bw <= ax + EPS or ay + ah <= by + EPS or by + bh <= ay + EPS


def test_random_rectangles_never_overlap_and_stay_inside():
    rng = random.Random(3)
    for _ in range(20):
        width, height = rng.uniform(3, 12), rng.uniform(2, 3)
        packer = MaxRects(width, height)
        for _ in range(60):
            packer.insert(rng.uniform(0.2, 1.8), rng.uniform(0.2, 1.8))
        used = packer.used
        assert used
        for i, (x, y, w, h) in enumerate(used):
            assert x >= -EPS and y >= -EPS and x + w <= width + EPS and y + h <= height + EPS
            assert all(_disjoint(used[i], other) for other in used[i + 1:])


def test_fills_a_floor_exactly_tiled_by_equal_rectangles():
    packer = MaxRects(4.0, 2.0)
    spots = [packer.insert(1.0, 1.0) for _ in range(8)]
    assert all(s is not None for s in spots)
    assert packer.insert(1.0, 1.0) is None


def test_turns_a_rectangle_when_only_the_turned_way_fits():
    packer = MaxRects(3.0, 1.0)
    assert packer.insert(1.0, 3.0) == (0.0, 0.0, True)


def test_respects_a_forbidden_turn():
    packer = MaxRects(3.0, 1.0)
    assert packer.insert(1.0, 3.0, turned=False) is None
    assert packer.insert(3.0, 1.0, plain=False) is None


def test_best_short_side_fit_prefers_the_tighter_free_rectangle():
    packer = MaxRects(10.0, 2.0)
    packer.insert(2.0, 1.0, turned=False)  # leaves a 10 x 1 strip above and an 8 x 2 block to the right
    assert packer.insert(3.0, 1.0) == (0.0, 1.0, False)  # the strip fits its 1.0 side exactly
