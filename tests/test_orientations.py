"""The per-line `orientations` field: validation, JSON, checker, bound, and old files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.bound import lower_bound
from src.checker import check
from src.formats import instance_from_dict, instance_to_dict, read_instance, write_instance
from src.model import ALL_ORIENTATIONS, UPRIGHT_ORIENTATIONS, is_tipped
from tests.builders import PARAMS, at, instance, line, solution

LYING = ("LHW", "HLW")


def test_default_set_follows_tippable():
    assert line("A").allowed == UPRIGHT_ORIENTATIONS
    assert line("A", tippable=True).allowed == ALL_ORIENTATIONS
    assert line("A", tippable=True).orientations is None


def test_explicit_set_is_kept_in_canonical_order_and_default_collapses_to_none():
    assert line("A", tippable=True, orientations=("HLW", "LHW", "WLH", "LWH")).orientations == ("LWH", "WLH", "LHW", "HLW")
    assert line("A", tippable=True, orientations=ALL_ORIENTATIONS).orientations is None
    assert line("A", orientations=("WLH", "LWH")).orientations is None
    assert line("A", tippable=True, orientations=UPRIGHT_ORIENTATIONS).allowed == UPRIGHT_ORIENTATIONS


@pytest.mark.parametrize("codes", [(), ("LWH", "XYZ"), ("LWH",), ("LHW",)])
def test_bad_sets_are_rejected(codes):
    with pytest.raises(ValueError):
        line("A", tippable=True, orientations=codes)


def test_tipped_code_needs_tippable():
    with pytest.raises(ValueError, match="tippable"):
        line("A", tippable=False, orientations=LYING)


def test_json_omits_the_key_when_default_and_round_trips_when_not(tmp_path: Path):
    plain = instance(line("A"), line("B", tippable=True))
    assert all("orientations" not in item for item in instance_to_dict(plain)["items"])
    restricted = instance(line("A", tippable=True, orientations=LYING), line("B", tippable=True))
    data = instance_to_dict(restricted)
    assert data["items"][0]["orientations"] == ["LHW", "HLW"]
    assert "orientations" not in data["items"][1]
    write_instance(tmp_path / "i.json", restricted)
    assert read_instance(tmp_path / "i.json") == restricted
    assert instance_from_dict(json.loads((tmp_path / "i.json").read_text(encoding="utf-8"))) == restricted


def test_old_files_without_the_key_load_and_write_back_identically(tmp_path: Path):
    inst = instance(line("A", qty=2, load=5.0), line("B", tippable=True))
    path = tmp_path / "i.json"
    write_instance(path, inst)
    before = path.read_bytes()
    write_instance(path, read_instance(path))
    assert path.read_bytes() == before


def test_checker_accepts_only_the_allowed_set():
    inst = instance(line("A", L=1.0, W=0.5, H=0.8, tippable=True, orientations=LYING))
    assert check(inst, solution(at("A#1", 0.0, o="LHW")), PARAMS).ok
    for code in ("LWH", "WLH", "WHL"):
        result = check(inst, solution(at("A#1", 0.0, o=code)), PARAMS)
        assert not result.ok
        assert any(v.constraint == 1 and "not allowed" in v.message for v in result.violations)


def test_bound_uses_the_allowed_set_for_the_floor():
    # 6 items L=4 W=1 H=0.5, tiers 1 on a 20 m2 floor: upright 4 m2 each, tipped 0.5 m2 each.
    kwargs = dict(qty=6, L=4.0, W=1.0, H=0.5, mass=1.0, tiers=1)
    free = instance(line("A", tippable=True, **kwargs))
    upright_only = instance(line("A", tippable=True, orientations=UPRIGHT_ORIENTATIONS, **kwargs))
    only_tipped = instance(line("A", tippable=True, orientations=LYING, **kwargs))
    assert lower_bound(free).rows["floor"].cost == 1.0
    assert lower_bound(upright_only).rows["floor"].cost == 2.0
    assert lower_bound(only_tipped).rows["floor"].cost == 1.0


def test_is_tipped():
    assert [is_tipped(c) for c in ALL_ORIENTATIONS] == [False, False, True, True, True, True]


# --- lie-down variant of the orient probe (step 2) -----------------------------------


def _lie(*lines):
    from scripts.probe import narrow_to_lying

    return narrow_to_lying(instance(*lines)).items


