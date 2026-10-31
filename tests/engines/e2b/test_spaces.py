"""Tests for E2b's maximal spaces: the cut into up to six
pieces, dropping pieces too small or contained in another space, and the lowest-corner order."""
from __future__ import annotations

import random

import numpy as np

from src.engines.e2b.spaces import Spaces


def _rows(spaces: Spaces) -> set[tuple[float, ...]]:
    return {tuple(round(float(v), 9) for v in row) for row in spaces.a}


def _spaces(dx: float = 4.0, dy: float = 3.0, dz: float = 2.0, small: float = 0.0) -> Spaces:
    return Spaces(dx, dy, dz, small, small, small)


def test_a_block_in_the_corner_leaves_three_maximal_spaces():
    spaces = _spaces()
    spaces.cut((0, 0, 0, 1, 1, 1))
    assert _rows(spaces) == {(1, 0, 0, 4, 3, 2), (0, 1, 0, 4, 3, 2), (0, 0, 1, 4, 3, 2)}


def test_a_block_in_the_middle_leaves_six_spaces_that_overlap():
    spaces = _spaces()
    spaces.cut((1, 1, 0.5, 2, 2, 1.5))
    assert _rows(spaces) == {
        (0, 0, 0, 1, 3, 2), (2, 0, 0, 4, 3, 2), (0, 0, 0, 4, 1, 2),
        (0, 2, 0, 4, 3, 2), (0, 0, 0, 4, 3, 0.5), (0, 0, 1.5, 4, 3, 2),
    }


def test_spaces_the_block_does_not_touch_are_kept_and_touching_faces_do_not_cut():
    spaces = _spaces()
    spaces.cut((0, 0, 0, 1, 1, 1))
    before = _rows(spaces)
    spaces.cut((0, 0, 1, 1, 1, 2))  # sits on the first block: cuts only the space above it
    assert (1, 0, 0, 4, 3, 2) in before and (1, 0, 0, 4, 3, 2) in _rows(spaces)
    spaces.cut((3, 2, 0, 4, 3, 1))
    assert (0, 0, 0, 1, 1, 1) not in _rows(spaces)


def test_pieces_smaller_than_any_item_are_dropped():
    spaces = Spaces(4.0, 3.0, 2.0, 0.5, 0.5, 0.5)
    spaces.cut((0.3, 0, 0, 4, 3, 2))  # leaves a 0.3 wide strip on the left
    assert len(spaces) == 0


def test_a_space_contained_in_another_is_dropped_and_equal_ones_appear_once():
    spaces = _spaces()
    spaces.cut((0, 0, 0, 1, 1, 1))
    spaces.cut((0, 0, 1, 1, 1, 2))
    rows = _rows(spaces)
    for r in rows:
        for o in rows:
            assert r == o or not all(o[i] <= r[i] for i in range(3)) or not all(o[i + 3] >= r[i + 3] for i in range(3))
    assert len(rows) == len(spaces)


def test_lowest_is_smallest_z_then_x_then_y():
    spaces = _spaces()
    spaces.a = np.array([[1.0, 0.0, 1.0, 2, 2, 2], [2.0, 0.0, 0.0, 3, 2, 1], [0.0, 1.0, 0.0, 1, 2, 1], [0.0, 0.5, 0.0, 1, 2, 1]])
    assert spaces.lowest() == 3
    spaces.drop(3)
    assert spaces.lowest() == 2


def test_random_cuts_keep_exactly_the_free_volume_as_a_union_of_spaces():
    rng = random.Random(3)
    spaces = _spaces(3.0, 3.0, 3.0)
    boxes = []
    for _ in range(12):
        x, y, z = (rng.uniform(0, 2.4) for _ in range(3))
        box = (x, y, z, x + rng.uniform(0.2, 0.6), y + rng.uniform(0.2, 0.6), z + rng.uniform(0.2, 0.6))
        boxes.append(box)
        spaces.cut(box)
    for _ in range(3000):
        p = [rng.uniform(0, 3) for _ in range(3)]
        in_box = any(all(b[i] < p[i] < b[i + 3] for i in range(3)) for b in boxes)
        in_space = any(all(s[i] <= p[i] <= s[i + 3] for i in range(3)) for s in spaces.a)
        if in_box:
            assert not any(all(s[i] < p[i] < s[i + 3] for i in range(3)) for s in spaces.a)
        else:
            assert in_space
    rows = [tuple(s) for s in spaces.a]
    for i, r in enumerate(rows):
        for j, o in enumerate(rows):
            if i != j:
                assert not (all(o[k] <= r[k] + 1e-9 for k in range(3)) and all(o[k + 3] >= r[k + 3] - 1e-9 for k in range(3)))
