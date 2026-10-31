"""Tests for E5's surplus removal: only items with
nothing resting on them go, highest first, over repeated sweeps; the repack fallback replaces a
container only when the core places everything; results pass the independent checker."""
from __future__ import annotations

import pytest

from src.checker import check
from src.engines.e5.pool import Pool
from src.engines.e5.trim import Loaded, TrimFailed, to_solution, trim
from src.model import Placement
from tests.builders import BOX, PARAMS, instance, line


def test_removes_the_top_item_of_a_stack():
    inst = instance(line("A", qty=2), line("B", qty=1))
    box = Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH"), ("A", 0.0, 0.0, 1.0, "LWH"), ("A", 2.0, 0.0, 0.0, "LWH"),
                       ("B", 4.0, 0.0, 0.0, "LWH")])
    out = trim(inst, [box])
    boxes, removed = out.boxes, out.removed
    assert removed == 1
    assert ("A", 0.0, 0.0, 1.0, "LWH") not in boxes[0].slots  # the highest free-topped one
    assert check(inst, to_solution(inst, PARAMS, boxes), PARAMS).ok


def test_drops_a_container_left_empty():
    inst = instance(line("A", qty=1))
    out = trim(inst, [Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH")]), Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH")])])
    boxes, removed = out.boxes, out.removed
    assert removed == 1 and len(boxes) == 1


def test_pool_keeps_one_column_per_type_and_count_vector():
    inst = instance(line("A", qty=3), line("B", qty=2))
    pool = Pool(inst)
    a = pool.add(BOX, [Placement("A#1", 0, 0, 0, 0, "LWH"), Placement("B#1", 0, 2, 0, 0, "LWH")], "x")
    b = pool.add(BOX, [Placement("B#2", 0, 0, 0, 0, "LWH"), Placement("A#3", 0, 3, 0, 0, "LWH")], "y")
    c = pool.add(BOX, [Placement("A#1", 0, 0, 0, 0, "LWH")], "y")
    assert a == b != c and len(pool) == 2
    assert pool.columns[a].counts == (1, 1) and pool.columns[a].source == "x"
    assert pool.add(BOX, [], "z") is None


def test_removing_a_top_item_frees_the_one_below():
    inst = instance(line("A", qty=1))
    box = Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH"), ("A", 0.0, 0.0, 1.0, "LWH"), ("A", 0.0, 0.0, 2.0, "LWH")])
    out = trim(inst, [box])
    boxes, removed = out.boxes, out.removed
    assert removed == 2 and boxes[0].slots == [("A", 0.0, 0.0, 0.0, "LWH")]


def test_a_later_line_s_removal_frees_an_earlier_line_s_item():
    # A (first line) is only surplus under a surplus B: the second sweep takes A once B is off.
    inst = instance(line("A", qty=1), line("B", qty=1))
    box = Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH"), ("B", 0.0, 0.0, 1.0, "LWH"), ("A", 2.0, 0.0, 0.0, "LWH"),
                       ("B", 2.0, 0.0, 1.0, "LWH")])
    out = trim(inst, [box])
    assert out.removed == 2 and out.repacked == 0
    assert check(inst, to_solution(inst, PARAMS, out.boxes), PARAMS).ok


def test_repack_fallback_replaces_a_container_only_when_the_core_places_everything():
    inst = instance(line("A", qty=1), line("B", qty=2))
    box = Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH"), ("B", 0.0, 0.0, 1.0, "LWH"), ("A", 2.0, 0.0, 0.0, "LWH"),
                       ("B", 2.0, 0.0, 1.0, "LWH")])
    calls = []

    def repack(ctype, lines):
        calls.append(sorted(lines))
        return [("A", 0.0, 0.0, 0.0, "LWH"), ("B", 2.0, 0.0, 0.0, "LWH"), ("B", 4.0, 0.0, 0.0, "LWH")]

    out = trim(inst, [box], repack)
    assert calls == [["A", "B", "B"]] and out.repacked == 1 and out.removed == 1
    assert check(inst, to_solution(inst, PARAMS, out.boxes), PARAMS).ok
    # Without a repack that places everything, the surplus A under a needed B is not removable.
    with pytest.raises(TrimFailed):
        trim(inst, [box], lambda ctype, lines: None)
    with pytest.raises(TrimFailed):
        trim(inst, [box])


def test_trim_failure_tells_the_line_its_surplus_and_what_is_left():
    # E5 caps that line's cover at qty + (surplus - left) and solves the master again.
    inst = instance(line("A", qty=1), line("B", qty=1))
    box = Loaded(BOX, [("A", 0.0, 0.0, 0.0, "LWH"), ("A", 0.0, 0.0, 1.0, "LWH"), ("B", 0.0, 0.0, 2.0, "LWH")])
    with pytest.raises(TrimFailed) as info:
        trim(inst, [box])
    assert (info.value.line, info.value.surplus, info.value.left) == ("A", 1, 1)
