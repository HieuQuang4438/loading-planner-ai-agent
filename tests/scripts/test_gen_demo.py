"""Tests for the demo data script (scripts/gen_demo.py): the probe set it writes is the committed one, its answer key
agrees with the documents, and a seeded variant is reproducible."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fpdf")
pytest.importorskip("PIL")

from scripts.gen_demo import TRAPS, generate, probe, variant  # noqa: E402

PROBE = Path(__file__).resolve().parents[2] / "data" / "probe"


def test_the_probe_set_is_the_committed_one(tmp_path):
    generate(probe(), tmp_path)
    for name in ("packing_list.csv", "freight_rates.csv", "answers.json"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (PROBE / name).read_text(encoding="utf-8"), name
    assert (tmp_path / "handling_label_sku_c.png").exists()


def test_the_probe_answers_are_the_traps_of_its_readme():
    key = json.loads((PROBE / "answers.json").read_text(encoding="utf-8"))
    lines = {line["id"]: line for line in key["lines"]}
    assert [line["id"] for line in key["lines"]] == ["SKU-A", "SKU-B", "SKU-C", "SKU-D", "SKU-A-2"]
    assert lines["SKU-A"]["dims"]["H"] == lines["SKU-A-2"]["dims"]["H"] == 0.45  # trap 1: the spec's height
    assert lines["SKU-A"]["mass"] == 12.5 and lines["SKU-B"]["mass"] == 26.0  # trap 2, 3: gross
    assert lines["SKU-C"]["mass"] == 18.0  # trap 4
    assert lines["SKU-C"]["posture"] == "upright" and lines["SKU-C"]["stacking"] == {"kind": "limited", "tiers": 2}
    assert lines["SKU-D"]["unit"] == "pallet" and lines["SKU-D"]["qty"] == 10  # trap 6
    assert key["excluded"] == ["SKU-E"]  # trap 7
    assert "posture" not in lines["SKU-A"]["stated"]  # no document says: ask, do not fill
    assert {t["trap"] for t in key["traps"]} == set(TRAPS)


def test_a_variant_is_reproducible_and_its_traps_point_at_its_lines(tmp_path):
    generate(variant(7, TRAPS), tmp_path / "a")
    generate(variant(7, TRAPS), tmp_path / "b")
    a = (tmp_path / "a" / "answers.json").read_text(encoding="utf-8")
    assert a == (tmp_path / "b" / "answers.json").read_text(encoding="utf-8")
    key = json.loads(a)
    skus = {line["sku"] for line in key["lines"]} | set(key["excluded"])
    assert all(set(t["on"]) <= skus for t in key["traps"])


def test_traps_can_be_left_out(tmp_path):
    generate(variant(3, ("pallet",)), tmp_path)
    key = json.loads((tmp_path / "answers.json").read_text(encoding="utf-8"))
    assert [t["trap"] for t in key["traps"]] == ["pallet"]
    assert key["excluded"] == [] and not list(tmp_path.glob("handling_label_*.png"))
    header = (tmp_path / "packing_list.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "G.W" in header
