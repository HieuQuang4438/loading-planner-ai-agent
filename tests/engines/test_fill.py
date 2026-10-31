"""Tests for mode B's engine (src.engines.fill; ADR-0002): the containers at hand, most pieces lexicographically by
priority, checked as the lot of the pieces it places."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.checker import check
from src.engines import e1, fill
from src.formats import instance_from_dict, instance_to_dict
from src.model import ContainerType, Instance, ItemLine, Params
from src.plan import mode_b

PARAMS = Params(delta=0.05, alpha=0.8)
C20 = ContainerType("20GP", 5.898, 2.352, 2.393, 2.34, 2.28, 28000, 1500)
C40 = ContainerType("40HC", 12.032, 2.352, 2.698, 2.34, 2.58, 26500, 2500)


def lot(fleet, priority=None, partial=True, big=40, small=200):
    lines = (ItemLine("BIG", big, 1.2, 1.0, 1.5, 160.0, False, 1, 0.0),
             ItemLine("BOX", small, 0.6, 0.4, 0.45, 12.5, False, 5, None))
    meta = {fill.META_KEY: {"fleet": fleet, "priority": priority or ["BOX", "BIG"], "partial": partial}}
    return Instance("t", (C20, C40), lines, meta)


@pytest.mark.parametrize("partial", [True, False])
def test_a_plan_passes_the_checker_as_the_lot_it_places_and_keeps_to_the_fleet(partial):
    instance = lot({"20GP": 1, "40HC": 1}, partial=partial)
    solution, diag = fill.solve(instance, PARAMS, 4.0, 1)
    assert check(fill.placed_instance(instance, solution), solution, PARAMS).ok
    assert not fill.fleet_excess(instance, solution) and len(solution.containers) <= 2
    if not partial:
        assert all(n in (0, line.qty) for line, n in ((x, diag["placed"][x.id]) for x in instance.items))


def test_the_first_line_by_priority_goes_in_before_the_rest():
    instance = lot({"20GP": 1}, priority=["BIG", "BOX"])
    solution, diag = fill.solve(instance, PARAMS, 4.0, 1)
    assert list(diag["placed"]) == ["BIG", "BOX"] and diag["placed"]["BIG"] > 0
    base = fill.placed_counts(fill.sequential(instance, fill.spec_of(instance), PARAMS, e1.pack_one))
    assert [diag["placed"][x] for x in ("BIG", "BOX")] >= [base.get(x, 0) for x in ("BIG", "BOX")]


def test_the_baseline_passes_the_checker_when_lines_go_in_only_in_part():
    # the smoke test's what-if lot: 1 x 40HC takes 47 of 50 SKU-C and 7 of 10 SKU-D, the rest goes on
    rows = [("SKU-A", 200, 0.6, 0.4, 0.5, 12.5, 5), ("SKU-C", 50, 0.5, 0.5, 0.6, 18.0, 2), ("SKU-D", 10, 1.2, 1.0, 1.5, 160.0, None),
            ("SKU-A-2", 40, 0.6, 0.4, 0.45, 12.5, 5), ("SKU-AA", 3, 1.0, 1.0, 1.0, 10.0, None)]
    data = {"name": "smoke", "container_types": instance_to_dict(lot({"40HC": 1}))["container_types"],
            "meta": {fill.META_KEY: {"fleet": {"40HC": 1}, "priority": [r[0] for r in rows], "partial": True}},
            "items": [{"id": i, "qty": q, "L": a, "W": b, "H": c, "mass": m, "tippable": False, "tiers": t, "load": None}
                      for i, q, a, b, c, m, t in rows]}
    out = mode_b.baseline(instance_from_dict(data), PARAMS)
    assert out["ok"] and 0 < out["placed"] < out["total"]
    assert any(0 < x["placed"] < row[1] for x, row in zip(out["lines"], rows))


def test_a_lot_that_fits_goes_in_whole():
    instance = lot({"40HC": 2}, big=4, small=20)
    _, diag = fill.solve(instance, PARAMS, 3.0, 1)
    assert diag["placed"] == {"BOX": 20, "BIG": 4}


def test_settings_that_do_not_fit_the_lot_are_refused():
    for meta in ({"fleet": {"45HC": 1}}, {"fleet": {"20GP": 0}}, {"fleet": {"20GP": 1}, "priority": ["BOX"]}, None):
        with pytest.raises(ValueError):
            fill.spec_of(replace(lot({"20GP": 1}), meta={fill.META_KEY: meta} if meta else {}))


def test_lexicographic_weights_are_cut_into_masters_that_stay_exact():
    assert fill.lex_chunks(["a", "b"], {"a": 10, "b": 10}) == [["a", "b"]]
    chunks = fill.lex_chunks(list("abcdefghij"), dict.fromkeys("abcdefghij", 300))
    assert [x for c in chunks for x in c] == list("abcdefghij") and len(chunks) > 1
