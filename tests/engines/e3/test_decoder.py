"""Tests for E3's decoder: a chromosome decodes to one
result; order keys become dense ranks, so the same permutation hits the core cache; container-type
keys pick among the types the remaining pieces fit, cheapest first; the last container downgrades;
the seeded chromosome reproduces the given types."""
from __future__ import annotations

import random

from src.checker import check
from src.engines import e1
from src.engines.e3.decoder import Decoder
from src.engines.e4.packer import Packer
from src.engines.e4.state import to_solution
from src.model import ContainerType, Params
from tests.builders import instance, line, random_lot

P = Params(delta=0.05, alpha=0.8)
FAR = 1e18

SMALL = ContainerType(id="S", L=2.2, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=0.6)
BIG = ContainerType(id="B", L=4.4, W=1.0, H=1.0, door_w=1.0, door_h=1.0, max_mass=1000.0, cost=1.0)
TALL = ContainerType(id="T", L=4.4, W=1.0, H=2.0, door_w=1.0, door_h=2.0, max_mass=1000.0, cost=1.2)


def _decoder(inst, slots: int = 4) -> Decoder:
    return Decoder(inst, Packer(inst, P, e1.pack_one, FAR), slots)


def _layout(boxes):
    return [(b.type.id, sorted((p.item, p.x, p.y, p.z, p.o) for p in b.placements)) for b in boxes]


def test_chromosome_layout():
    inst = random_lot(3)
    dec = _decoder(inst, slots=5)
    assert dec.length == 2 * len(inst.items) + 5
    assert len(dec.random(random.Random(1))) == dec.length


def test_same_chromosome_same_decode():
    inst = random_lot(4)
    chrom = _decoder(inst).random(random.Random(3))
    assert _layout(_decoder(inst).decode(list(chrom))) == _layout(_decoder(inst).decode(list(chrom)))


def test_decode_places_every_item_once_and_passes_the_checker():
    for seed in (1, 5, 8):
        inst = random_lot(seed)
        boxes = _decoder(inst).decode(_decoder(inst).random(random.Random(seed)))
        placed = [p.item for b in boxes for p in b.placements]
        assert sorted(placed) == sorted(i for ln in inst.items for i in ln.item_ids())
        result = check(inst, to_solution(inst, P, boxes), P)
        assert result.ok, result.violations[:3]


def test_order_keys_become_dense_ranks():
    inst = random_lot(3)
    dec = _decoder(inst)
    chrom = dec.random(random.Random(1))
    chrom[0:6] = [0.9, 0.1, 0.3, 0.7, 0.9, 0.4]  # lines 0, 1, 2: order 0.9, 0.3, 0.9; turns F, T, F
    hints = dec.hints(chrom, [0, 1, 2])
    assert hints.order == (("L1", 1.0), ("L2", 0.0), ("L3", 1.0))
    assert hints.turn == (("L1", False), ("L2", True), ("L3", False))


def test_same_permutation_gives_same_hints_and_hits_the_cache():
    inst = random_lot(3)
    dec = _decoder(inst)
    a = dec.random(random.Random(1))
    b = list(a)
    for i in range(len(inst.items)):  # squash order keys monotonically: same permutation
        b[2 * i] = a[2 * i] / 2
    present = list(range(len(inst.items)))
    assert dec.hints(a, present) == dec.hints(b, present)
    dec.decode(a)
    calls = dec.packer.calls
    dec.decode(b)
    assert dec.packer.calls == calls and dec.packer.hits > 0


def test_type_key_picks_among_fitting_types_cheapest_first():
    inst = instance(line("A", qty=2), types=(BIG, SMALL))
    dec = _decoder(inst, slots=1)
    low = [0.5, 0.25, 0.1]  # one line (order, turn), one slot
    high = [0.5, 0.25, 0.9]
    assert [b.type.id for b in dec.decode(low)] == ["S"]
    # BIG holds both cubes, then the last-container downgrade moves them to SMALL, which also does
    assert [b.type.id for b in dec.decode(high)] == ["S"]


def test_types_no_remaining_piece_fits_are_not_candidates():
    # Tall items only fit T; the cubes fit all three. Once the cubes are placed, T is the only candidate.
    inst = instance(line("A", qty=2), line("H", qty=1, H=1.8), types=(SMALL, BIG, TALL))
    dec = _decoder(inst, slots=2)
    chrom = [0.5, 0.25, 0.5, 0.25, 0.0, 0.0]  # slot 0 -> SMALL (cubes), slot 1 -> the only candidate
    boxes = dec.decode(chrom)
    assert [b.type.id for b in boxes] == ["S", "T"]
    assert boxes[1].items == {"H#1"}


def test_slots_are_reused_cyclically():
    inst = instance(line("A", qty=6, L=2.0), types=(SMALL,))  # one per container
    boxes = _decoder(inst, slots=2).decode([0.5, 0.25, 0.3, 0.7])
    assert len(boxes) == 6


def test_seeded_chromosome_forces_the_given_types():
    inst = random_lot(6)
    sol, _ = e1.solve(inst, P, 1e6, 1)
    types = [c.type for c in sol.containers]
    dec = _decoder(inst, slots=len(types) + 2)
    chrom, boxes = dec.seeded(types, random.Random(1))
    got = [b.type.id for b in boxes]
    n = min(len(got), len(types)) - 1  # the last decoded container may downgrade
    assert n > 0 and got[:n] == types[:n]
    assert all(chrom[2 * i] == 0.5 and chrom[2 * i + 1] < 0.5 for i in range(len(inst.items)))
    assert _layout(dec.decode(list(chrom))) == _layout(boxes)
