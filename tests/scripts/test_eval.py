"""Tests for the agent's eval (scripts/gen_eval.py, scripts/eval_agent.py): the set list covers every
trap, and the runner scores the probe right with a mocked model reading correctly, and flags a value read wrong."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fpdf")
pytest.importorskip("PIL")

from scripts import eval_agent, gen_eval  # noqa: E402
from scripts.gen_demo import TRAPS, generate, probe  # noqa: E402
from src.extract.documents import load  # noqa: E402
from src.extract.pipeline import extract  # noqa: E402
from src.lot.review import refresh  # noqa: E402
from tests.extract.probe_readings import BY_FILE  # noqa: E402


class Reader:
    """The correct reading of each probe document, by the file name the pipeline sends first."""

    def __init__(self, readings=BY_FILE):
        self.readings = readings

    def generate(self, name, parts, schema):
        return self.readings[parts[0].text.split(": ", 1)[1]]


@pytest.fixture(scope="module")
def probe_set(tmp_path_factory):
    folder = tmp_path_factory.mktemp("set-00")
    generate(probe(), folder)
    return folder


def test_every_trap_is_in_enough_sets_and_the_list_is_fixed():
    counts = gen_eval.check_coverage()
    assert set(counts) == set(TRAPS) and min(counts.values()) >= gen_eval.MIN_PER_TRAP
    assert [n for n, _, t in gen_eval.SETS if not t] == ["clean-21", "clean-22"] and len(gen_eval.SETS) == 23
    assert all(2 <= len(gen_eval.traps_for(s)) <= len(TRAPS) for s in gen_eval.VARIANTS)


def test_the_per_set_doc_matches_the_sets():
    body = gen_eval.DOC.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n---\n", 1)[1]
    assert body == gen_eval.describe(), "run: python -m scripts.gen_eval --doc"


def test_a_correct_reading_of_the_probe_catches_every_trap_and_invents_nothing(probe_set):
    s = eval_agent.run_set(Reader(), probe_set)
    assert s.wrong == [] and s.invented == [] and s.extra_points == [] and not s.missing_lines
    assert len(s.traps) == 8 and all(t["caught"] for t in s.traps)
    total = eval_agent.summary([s])
    assert total["traps_caught"] == total["traps"] == 8 and total["right"] + total["asked"] == total["stated_fields"]


def test_a_field_extracted_wrong_counts_as_wrong_and_invented(probe_set):
    key = json.loads((probe_set / "answers.json").read_text(encoding="utf-8"))
    for line in key["lines"]:
        if line["id"] == "SKU-C":
            line["mass"] = 19.0  # the key says otherwise than every document: the extracted 18 kg is now wrong
    lot = refresh(extract(Reader(), "x", [load(p.name, p.read_bytes()) for p in eval_agent.documents(probe_set)]).lot)
    s = eval_agent.score("set-00", lot, key)
    assert s.wrong == ["SKU-C.mass"] and "SKU-C.mass" in s.invented
    assert next(t for t in s.traps if t["trap"] == "missing_mass")["caught"] is False
