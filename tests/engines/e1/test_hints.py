"""E1 core hints (option 2A; src.engines.base.Hints): without hints the engine's output is
byte-identical to the core before hints existed, pinned by hash on reproducible lots; with hints the
floor order and column turn follow them, and every layout still passes the checker."""
from __future__ import annotations

import hashlib
import random

import pytest

from src.checker import check
from src.engines.base import Hints, expand_pieces
from src.engines.e1 import pack_one, solve
from src.formats import dumps, solution_to_dict
from src.model import ContainerType, Params
from tests.builders import instance, line, random_lot, solution

RNG = random.Random(0)
P = Params(delta=0.05, alpha=0.8)
DC20 = ContainerType(id="20DC", L=5.9, W=2.35, H=2.39, door_w=2.34, door_h=2.28, max_mass=28000.0, cost=0.6)

# sha256 prefix of `solve(random_lot(seed), P, 1e6, 1)` computed on the core before hints were added.
BEFORE_HINTS = {
    1: "c7bcc1c79b047707",
    2: "0c8e7e1d78675420",
    3: "0bd47d4c4e5b7ffb",
    4: "491ed4b849539009",
    5: "5b5a1e150d2d4617",
    6: "e2acd741d80cb8b7",
}


def _digest(sol) -> str:
    d = solution_to_dict(sol)
    d.pop("meta")
    return hashlib.sha256(dumps(d).encode()).hexdigest()[:16]


@pytest.mark.parametrize("seed", sorted(BEFORE_HINTS))
def test_output_without_hints_is_unchanged(seed):
    sol, _ = solve(random_lot(seed), P, 1e6, 1)
    assert _digest(sol) == BEFORE_HINTS[seed]


@pytest.mark.parametrize("seed", [1, 4])
def test_empty_hints_equal_no_hints(seed):
    pieces = expand_pieces(random_lot(seed))
    assert pack_one(pieces, DC20, P, RNG, Hints()) == pack_one(pieces, DC20, P, RNG)


def _layout(inst, ctype, hints):
    placed = pack_one(expand_pieces(inst), ctype, P, RNG, hints)
    sol = solution(*[p.__class__(p.item, 1, p.x, p.y, p.z, p.o) for p in placed], containers=((1, ctype.id),))
    sol.params = P
    return placed, check(inst, sol, P)


def test_turn_hint_turns_the_column_when_it_fits():
    # 1.6 x 1.2 base: unhinted best-short-side-fit turns it (1.6 across); an unturned hint keeps L along x.
    inst = instance(line("A", qty=3, L=1.6, W=1.2, H=2.0, tiers=1), types=(DC20,))
    free, _ = _layout(inst, DC20, None)
    kept, result = _layout(inst, DC20, Hints(turn=(("A", False),)))
    assert {v.constraint for v in result.violations} <= {2}
    assert all(p.o == "LWH" for p in kept)
    turned, _ = _layout(inst, DC20, Hints(turn=(("A", True),)))
    assert all(p.o == "WLH" for p in turned)
    assert {p.o for p in free} <= {"LWH", "WLH"}


def test_order_hint_lays_the_keyed_line_first():
    inst = instance(
        line("BIG", qty=2, L=2.0, W=2.0, H=2.0, tiers=1),
        line("SMALL", qty=2, L=1.0, W=1.0, H=1.0, tiers=1),
        types=(DC20,),
    )
    default, _ = _layout(inst, DC20, None)
    hinted, result = _layout(inst, DC20, Hints(order=(("SMALL", 0.0), ("BIG", 1.0))))
    assert result.ok, result.violations
    first = min(hinted, key=lambda p: (p.x, p.y))
    assert first.item.startswith("SMALL")
    assert min(default, key=lambda p: (p.x, p.y)).item.startswith("BIG")


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_hints_still_give_checker_valid_layouts(seed):
    inst = random_lot(seed)
    rng = random.Random(seed)
    lines = [ln.id for ln in inst.items]
    hints = Hints(order=tuple((ln, rng.random()) for ln in lines), turn=tuple((ln, rng.random() < 0.5) for ln in lines))
    for ctype in inst.container_types:
        placed, result = _layout(inst, ctype, hints)
        assert {v.constraint for v in result.violations} <= {2}, (ctype.id, result.violations[:3])
