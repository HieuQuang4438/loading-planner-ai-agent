"""Tests for E4's cached core calls, destroy and repair operators: the cache replays exactly what the core returns; destroy moves items to the pool; repair puts
every pooled item back into containers the core packed in full, and downgrades where it can."""
from __future__ import annotations

import random

import pytest

from src.checker import check
from src.engines import e1
from src.engines.base import Hints
from src.engines.e4.operators import (
    Context,
    Settings,
    Work,
    greedy,
    greedy_shuffle,
    random_containers,
    random_hints,
    random_items,
    worst,
)
from src.engines.e4.packer import Deadline, Packer
from src.engines.e4.state import from_solution, to_solution
from src.model import ContainerType, Params
from tests.builders import instance, line, random_lot

P = Params(delta=0.05, alpha=0.8)
FAR = 1e18


def _context(inst, settings: Settings = Settings(), seed: int = 1) -> Context:
    return Context(inst, Packer(inst, P, e1.pack_one, FAR), random.Random(seed), settings)


def _initial(inst, ctx):
    sol, _ = e1.solve(inst, P, 1e6, 1)
    return from_solution(inst, sol, ctx.packer.pieces)


def _all_items(inst) -> set[str]:
    return {i for ln in inst.items for i in ln.item_ids()}


def test_cache_replays_the_core_result_under_other_item_ids():
    inst = random_lot(3)
    ctx = _context(inst)
    ctype = inst.container_types[1]
    items_a = [f"L1#{n}" for n in (1, 2, 3)] + [f"L2#{n}" for n in (1, 2)]
    items_b = [f"L1#{n}" for n in (4, 5, 6)] + [f"L2#{n}" for n in (3, 4)]
    first = ctx.packer.pack(items_a, ctype)
    replay = ctx.packer.pack(items_b, ctype)
    direct = e1.pack_one([ctx.packer.pieces[i] for i in sorted(items_b, key=ctx.packer.sort_key)], ctype, P, random.Random(0))
    assert ctx.packer.calls == 1 and ctx.packer.hits == 1
    assert replay == direct
    assert [(p.x, p.y, p.z, p.o) for p in first] == [(p.x, p.y, p.z, p.o) for p in replay]


def test_hints_are_part_of_the_cache_key():
    inst = random_lot(3)
    ctx = _context(inst)
    items = sorted(_all_items(inst))[:10]
    ctx.packer.pack(items, inst.container_types[0])
    ctx.packer.pack(items, inst.container_types[0], Hints(turn=(("L1", True),)))
    assert ctx.packer.calls == 2


def test_packer_raises_deadline_before_calling_the_core():
    inst = random_lot(3)
    packer = Packer(inst, P, e1.pack_one, deadline=0.0)
    with pytest.raises(Deadline):
        packer.pack(["L1#1"], inst.container_types[0])
    assert packer.calls == 0


def test_worst_empties_the_emptiest_container():
    inst = random_lot(6)
    ctx = _context(inst, Settings(worst_determinism=1e9))
    boxes = _initial(inst, ctx)
    emptiest = min(boxes, key=lambda b: b.fill)
    work = Work(boxes=list(boxes), pool=[])
    worst(work, ctx)
    assert emptiest not in work.boxes and set(work.pool) == emptiest.items


def test_random_containers_empties_one_or_two():
    inst = random_lot(6)
    ctx = _context(inst)
    boxes = _initial(inst, ctx)
    work = Work(boxes=list(boxes), pool=[])
    random_containers(work, ctx)
    gone = [b for b in boxes if b not in work.boxes]
    assert 1 <= len(gone) <= 2
    assert set(work.pool) == set().union(*(b.items for b in gone))


def test_random_items_takes_a_share_and_marks_containers_dirty():
    inst = random_lot(6)
    ctx = _context(inst, Settings(destroy_share=0.3))
    boxes = [b.copy() for b in _initial(inst, ctx)]
    before = {id(b): b.items for b in boxes}
    work = Work(boxes=list(boxes), pool=[])
    random_items(work, ctx)
    dirty = [b for b in work.boxes if b.dirty]
    assert 1 <= len(dirty) + (len(boxes) - len(work.boxes)) <= 3
    for b in dirty:
        assert b.placements == () and b.items < before[id(b)]
    assert set(work.pool) | set().union(*(b.items for b in work.boxes)) == _all_items(inst)


@pytest.mark.parametrize("repair", [greedy, greedy_shuffle])
@pytest.mark.parametrize("destroy", [worst, random_containers, random_items])
def test_repair_puts_every_item_back_into_valid_containers(destroy, repair):
    inst = random_lot(8)
    ctx = _context(inst)
    work = Work(boxes=[b.copy() for b in _initial(inst, ctx)], pool=[])
    destroy(work, ctx)
    repair(work, ctx)
    assert work.pool == [] and not any(b.dirty for b in work.boxes)
    placed = [p.item for b in work.boxes for p in b.placements]
    assert sorted(placed) == sorted(_all_items(inst))
    assert all({p.item for p in b.placements} == b.items for b in work.boxes)
    result = check(inst, to_solution(inst, P, work.boxes), P)
    assert result.ok, result.violations[:3]


def test_repair_downgrades_a_repaired_container_to_a_cheaper_type():
    small = ContainerType(id="S", L=2.2, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=0.6)
    big = ContainerType(id="B", L=4.4, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
    inst = instance(line("A", qty=2), types=(small, big))
    ctx = _context(inst, Settings(destroy_share=0.5))
    in_big = ctx.box(big, ctx.packer.pack(["A#1", "A#2"], big), None)  # e.g. the fleet layer's pick
    work = Work(boxes=[in_big], pool=[])
    random_items(work, ctx)  # takes one cube out; repair puts it back, then the pair moves to S
    greedy(work, ctx)
    assert [b.type.id for b in work.boxes] == ["S"] and work.boxes[0].items == {"A#1", "A#2"}


def test_random_hints_cover_every_line_given():
    inst = random_lot(6)
    ctx = _context(inst)
    lines = {ln.id for ln in inst.items[:3]}
    hints = random_hints(lines, ctx)
    assert {ln for ln, _ in hints.order} == lines == {ln for ln, _ in hints.turn}
