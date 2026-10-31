"""Tests for the per-container load in the web payload (src.web.view.build_view)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from tests.web.support import sample_path
from src.checker import check
from src.engines import e1, e2, e5
from src.formats import read_instance
from src.model import Instance, Params
from src.web.view import build_view
from tests.builders import at, instance, line, solution

ENGINE_TIME_LIMIT = 2.0
DEFAULTS = Params(delta=0.05, alpha=0.8)
RUN = {"engine": "test", "seed": 1}

# e1 and e2 are E5's cores, not registered engines here (src/engines/__init__.py)
SOLVERS = {"e1": e1.solve, "e2": e2.solve, "e5": e5.solve}
SAMPLE_NAMES = ("sample-small", "sample-mixed")


def _with_max_mass(inst: Instance, type_id: str, max_mass: float) -> Instance:
    types = tuple(replace(t, max_mass=max_mass) if t.id == type_id else t for t in inst.container_types)
    return replace(inst, container_types=types)


def test_load_counts_mass_and_volume_per_line():
    inst = instance(line("A", qty=2, L=1.0, W=1.0, H=1.0, mass=10.0), line("B", qty=1, L=2.0, W=1.0, H=0.5, mass=4.0))
    sol = solution(at("A#1", 0.0), at("B#1", 1.0), at("A#2", 0.0, z=1.0))

    c = build_view(inst, sol, RUN)["containers"][0]

    assert c["mass"] == pytest.approx(24.0)
    assert c["volume"] == pytest.approx(3.0)
    assert c["lines"] == [{"id": "A", "qty": 2, "mass": 20.0}, {"id": "B", "qty": 1, "mass": 4.0}]
    ctype = inst.container_types[0]
    assert c["max_mass"] == ctype.max_mass and c["cost"] == ctype.cost
    assert c["mass_ratio"] == pytest.approx(24.0 / ctype.max_mass)
    assert c["volume_ratio"] == pytest.approx(3.0 / ctype.volume)


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_container_mass_is_the_mass_the_checker_weighs(name):
    inst = read_instance(sample_path(name))
    sol, _ = SOLVERS["e1"](inst, DEFAULTS, ENGINE_TIME_LIMIT, 1)
    view = build_view(inst, sol, RUN, DEFAULTS)
    assert view["check"]["ok"]

    for c in view["containers"]:
        assert sum(line["qty"] for line in c["lines"]) == len(c["replay"])
        assert sum(view["placements"][i]["mass"] for i in c["replay"]) == pytest.approx(c["mass"])
        # constraint 6 trips just below the shown mass and not just above it
        below = check(_with_max_mass(inst, c["type"], c["mass"] - 0.5), sol, DEFAULTS)
        above = check(_with_max_mass(inst, c["type"], c["mass"] + 0.5), sol, DEFAULTS)
        assert any(v.constraint == 6 and v.k == c["k"] for v in below.violations)
        assert not any(v.constraint == 6 and v.k == c["k"] for v in above.violations)


# --- constraint 7/8 measures per piece -------------------------------------------------------

def _stacking_lot():
    inst = instance(
        line("A", qty=3, H=0.5, load=15.0, tiers=2),  # A#1..A#3 stacked: over load and over tiers
        line("B", qty=2, H=0.5),
        line("C", qty=1, H=0.5),  # half on B#2: under alpha
    )
    sol = solution(
        at("A#1", 0.0), at("A#2", 0.0, z=0.5), at("A#3", 0.0, z=1.0),
        at("B#1", 2.0), at("B#2", 4.0), at("C#1", 4.5, z=0.5),
    )
    return inst, sol


def test_pieces_carry_the_checker_load_stack_and_support():
    inst, sol = _stacking_lot()
    view = build_view(inst, sol, RUN, DEFAULTS)
    p = {q["item"]: q for q in view["placements"]}

    assert (p["A#1"]["on_top"], p["A#2"]["on_top"], p["A#3"]["on_top"]) == (20.0, 10.0, 0.0)
    assert [p[f"A#{n}"]["stack"] for n in (1, 2, 3)] == [3, 3, 3]
    assert p["A#1"]["supported"] is None and p["A#2"]["supported"] == pytest.approx(1.0)
    assert p["C#1"]["supported"] == pytest.approx(0.5)
    assert [i for i, q in p.items() if q["free_top"]] == ["A#3", "B#1", "C#1"]
    # A#3 is out of tiers; B#1 and C#1 have a tier, no load limit and 1.5 / 1.0 m above them (lowest piece 0.5 m)
    assert view["min_item_height"] == pytest.approx(0.5)
    assert view["containers"][0]["free_tops"] == 2


def _flagged(view, alpha):
    lines = {line["id"]: line for line in view["lines"]}
    out = set()
    for q in view["placements"]:
        line = lines[q["line"]]
        if line["load"] is not None and q["on_top"] > line["load"] + 1e-6:
            out.add((8, q["item"]))
        if q["stack"] > line["tiers"]:
            out.add((8, q["item"]))
        if q["supported"] is not None and q["supported"] * q["l"] * q["w"] < alpha * q["l"] * q["w"] - 1e-9:
            out.add((7, q["item"]))
    return out


def _engine_case(name, engine):
    inst = read_instance(sample_path(name))
    sol, _ = SOLVERS[engine](inst, DEFAULTS, ENGINE_TIME_LIMIT, 1)
    return inst, sol


@pytest.mark.parametrize("case", ["hand"] + [f"{n}|{e}" for n in SAMPLE_NAMES for e in ("e1", "e5")])
def test_limits_shown_as_exceeded_are_exactly_the_checker_violations_7_and_8(case):
    inst, sol = _stacking_lot() if case == "hand" else _engine_case(*case.split("|"))
    view = build_view(inst, sol, RUN, DEFAULTS)
    from_checker = {(v.constraint, i) for v in check(inst, sol, DEFAULTS).violations if v.constraint in (7, 8) for i in v.items}

    assert _flagged(view, DEFAULTS.alpha) == from_checker
    if case == "hand":
        assert from_checker == {(8, "A#1"), (8, "A#2"), (8, "A#3"), (7, "C#1")}


def test_tipped_counts_every_kind_and_skips_upright():
    # U is upright; L=1.0 W=0.6 H=0.8 gives lying (W up, 0.6 < H), edge (L up, 1.0 > H); E has W == H: tipped
    inst = instance(line("U", L=1.0, W=1.0, H=1.0), line("A", L=1.0, W=0.6, H=0.8, tippable=True),
                    line("E", L=1.0, W=0.8, H=0.8, tippable=True))
    sol = solution(at("U#1", 0.0), at("A#1", 1.0, o="LHW"), at("A#2", 2.0, o="WLH"), at("A#3", 3.0, o="HWL"),
                   at("E#1", 4.0, o="LHW"), at("E#2", 5.0, o="HLW"))

    assert build_view(inst, sol, RUN)["tipped"] == {"total": 4, "lying": 1, "edge": 1, "tipped": 2}
