"""Tests for E2b's per-block checks of constraints 7 and 8,
each also confirmed against the independent checker."""
from __future__ import annotations

from src.checker import check
from src.engines.e2b.container import INF, Container, Shape
from src.model import ContainerType, ItemLine, Params, Placement, Solution, UsedContainer
from tests.builders import instance, line

DELTA = 0.1
PARAMS = Params(delta=DELTA, alpha=0.8)
TALL = ContainerType(id="TALL", L=10.0, W=5.0, H=10.0, door_w=5.0, door_h=9.5, max_mass=1e6, cost=1.0)


def _shape(nx=1, ny=1, nz=1, a=1.0, b=1.0, c=1.0, mass=10.0, tiers=5, load=INF) -> Shape:
    return Shape(nx, ny, nz, a, b, c, a + DELTA, b + DELTA, mass, tiers, load)


def _put(container: Container, shape: Shape, x: float, y: float, z: float):
    near = container.near(z, x, x + shape.nx * shape.px, y, y + shape.ny * shape.py) if z > 1e-6 else []
    plan = container.try_place(shape, x, y, z, near)
    if plan is not None:
        container.commit(plan)
    return plan


def _verdict(container: Container, lines: list[ItemLine], ids: list[str]) -> list[int]:
    """Constraints the checker finds broken for the container's blocks; `ids[i]` is the line of block i."""
    placements = []
    counts: dict[str, int] = {}
    for block, line_id in zip(container.blocks, ids):
        s = block.shape
        for layer in range(s.nz):
            for j in range(s.ny):
                for i in range(s.nx):
                    counts[line_id] = counts.get(line_id, 0) + 1
                    placements.append(Placement(
                        f"{line_id}#{counts[line_id]}", 1, block.x0 + i * s.px, block.y0 + j * s.py, block.z0 + layer * s.c, "LWH"
                    ))
    inst = instance(*lines, types=(TALL,))
    sol = Solution(inst.name, PARAMS, [UsedContainer(1, TALL.id)], placements)
    return sorted({v.constraint for v in check(inst, sol, PARAMS).violations})


def test_support_of_every_bottom_item_must_reach_alpha():
    c = Container(DELTA, 0.8)
    assert _put(c, _shape(), 0.0, 0.0, 0.0)
    top = _shape()
    c2 = Container(DELTA, 0.8)
    _put(c2, _shape(), 0.0, 0.0, 0.0)
    assert _put(c2, top, 0.21, 0.0, 1.0) is None  # 0.79 supported
    assert _put(c2, top, 0.19, 0.0, 1.0) is not None  # 0.81 supported


def test_a_wide_block_needs_every_bottom_item_supported_not_the_average():
    c = Container(DELTA, 0.8)
    _put(c, _shape(), 0.0, 0.0, 0.0)  # one column under a block of two
    two = _shape(nx=2)
    assert _put(c, two, 0.0, 0.0, 1.0) is None  # item 1 has nothing under it


def test_support_adds_up_over_several_blocks_at_the_same_height():
    c = Container(DELTA, 0.8)
    _put(c, _shape(), 0.0, 0.0, 0.0)
    _put(c, _shape(), 1.1, 0.0, 0.0)
    bridge = _shape(a=1.3)
    assert _put(c, bridge, 0.4, 0.0, 1.0)  # 0.7 on the first block + 0.2 on the second, of 1.3


def test_tiers_of_the_weakest_block_bound_the_whole_stack():
    c = Container(DELTA, 0.8)
    assert _put(c, _shape(tiers=2), 0.0, 0.0, 0.0)
    assert _put(c, _shape(tiers=5), 0.0, 0.0, 1.0)
    assert _put(c, _shape(tiers=5), 0.0, 0.0, 2.0) is None  # the bottom block would carry a stack of 3
    c = Container(DELTA, 0.8)
    _put(c, _shape(nz=2, tiers=3), 0.0, 0.0, 0.0)
    assert _put(c, _shape(nz=2, tiers=5), 0.0, 0.0, 2.0) is None  # 4 high over a block that takes 3
    assert _put(c, _shape(nz=1, tiers=5), 0.0, 0.0, 2.0)


def test_tiers_at_the_boundary_agree_with_the_checker():
    c = Container(DELTA, 0.8)
    _put(c, _shape(nz=3, tiers=3), 0.0, 0.0, 0.0)
    assert _verdict(c, [line("A", qty=3, tiers=3)], ["A"]) == []
    assert _put(c, _shape(tiers=5), 0.0, 0.0, 3.0) is None


def test_load_counts_the_mass_of_everything_above_not_only_the_next_block():
    c = Container(DELTA, 0.8)
    _put(c, _shape(load=25.0), 0.0, 0.0, 0.0)
    assert _put(c, _shape(), 0.0, 0.0, 1.0)
    assert _put(c, _shape(), 0.0, 0.0, 2.0)  # 20 kg above the bottom block, 25 allowed
    assert _put(c, _shape(), 0.0, 0.0, 3.0) is None  # 30 kg above it, though the block below carries only 10


def test_load_of_a_column_is_only_the_mass_over_that_column():
    c = Container(DELTA, 0.8)
    _put(c, _shape(nx=2, load=15.0), 0.0, 0.0, 0.0)
    assert _put(c, _shape(), 0.0, 0.0, 1.0)  # over column 0
    assert _put(c, _shape(), 1.1, 0.0, 1.0)  # over column 1: each column carries 10 kg
    assert _put(c, _shape(), 0.0, 0.0, 2.0) is None  # column 0 would carry 20 kg


def test_load_inside_a_block_counts_its_own_upper_layers():
    c = Container(DELTA, 0.8)
    _put(c, _shape(nz=2, load=15.0), 0.0, 0.0, 0.0)  # the bottom item carries 10 kg of its own block
    assert _put(c, _shape(), 0.0, 0.0, 2.0) is None  # +10 kg = 20 > 15
    c = Container(DELTA, 0.8)
    _put(c, _shape(nz=2, load=25.0), 0.0, 0.0, 0.0)
    assert _put(c, _shape(), 0.0, 0.0, 2.0)


def test_load_agrees_with_the_checker_at_the_boundary():
    lines = [line("A", qty=1, mass=10.0, load=20.0), line("B", qty=2, mass=10.0)]
    c = Container(DELTA, 0.8)
    _put(c, _shape(load=20.0), 0.0, 0.0, 0.0)
    _put(c, _shape(), 0.0, 0.0, 1.0)
    _put(c, _shape(), 0.0, 0.0, 2.0)
    assert _verdict(c, lines, ["A", "B", "B"]) == []
    assert _put(c, _shape(), 0.0, 0.0, 3.0) is None


def test_a_block_on_the_floor_needs_no_support_and_is_not_below_anything():
    c = Container(DELTA, 0.8)
    plan = _put(c, _shape(nx=3, ny=2, nz=2), 0.0, 0.0, 0.0)
    assert plan is not None and plan.links == []
    assert c.mass == 10.0 * 12
