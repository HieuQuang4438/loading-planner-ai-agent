"""Tests for E5's versions: `e5-v1` is `Settings()`, `e5-v2` adds milestone 4, `e5-v3` pace and the lean pool; the bare names
`e5` and `e5-orient` run the default version; runs record the version whatever name they were started under."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.checker import check
from src.engines import base
from src.engines.e5 import engine as e5_engine
from src.engines.e5.engine import DEFAULT_VERSION, MONO_FLAT_TEMPERATURE, VERSIONS, Settings, version_of
from src.model import Params
from tests.builders import random_lot

P = Params(delta=0.05, alpha=0.8)


def test_v1_is_the_old_default_and_v2_is_milestone_4():
    assert VERSIONS["e5-v1"] == Settings()
    v2 = VERSIONS["e5-v2"]
    assert (v2.initial_to_end, v2.alns_acceptance, v2.alns_flat_temperature, v2.trim_retries, v2.reuse_time) == (
        True, "flat", MONO_FLAT_TEMPERATURE, 5, True)
    assert DEFAULT_VERSION == "e5-v4"


def test_v3_is_v2_plus_pace_and_the_lean_pool():
    v3 = VERSIONS["e5-v3"]
    assert (v3.pace, v3.sparse_pool, v3.reduce_master, v3.master_columns) == (True, True, True, 20_000)
    assert v3 == replace(VERSIONS["e5-v2"], pace=True, sparse_pool=True, reduce_master=True, master_columns=20_000)
    assert not any((VERSIONS["e5-v2"].pace, VERSIONS["e5-v2"].sparse_pool, VERSIONS["e5-v2"].reduce_master))


def test_v4_is_v3_plus_the_stall_rule():
    v4 = VERSIONS["e5-v4"]
    assert (v4.alns_stall_min, v4.alns_stall_ratio) == (2000, 2.0)
    assert v4 == replace(VERSIONS["e5-v3"], alns_stall_min=2000, alns_stall_ratio=2.0)
    assert VERSIONS["e5-v3-stall"] == v4 and version_of(VERSIONS["e5-v3-stall"]) == "e5-v4"


def test_version_of_ignores_the_orientation_option_and_names_no_variant():
    assert version_of(Settings()) == "e5-v1"
    assert version_of(replace(VERSIONS["e5-v2"], orient_dense_core=True, e2_orient=True)) == "e5-v2"
    assert version_of(Settings(search="brkga")) is None
    assert version_of(replace(VERSIONS["e5-v2"], alns_flat_temperature=0.1)) is None


@pytest.mark.parametrize("name, version, orient", [("e5", "e5-v4", False), ("e5-orient", "e5-v4", True)])
def test_each_name_runs_its_version(name, version, orient, monkeypatch):
    seen = []
    monkeypatch.setattr(e5_engine, "solve", lambda inst, p, t, seed, s, start=None: seen.append(s) or (None, {}))
    base.get(name)(random_lot(2), P, 3.0, 1)
    (s,) = seen
    assert version_of(s) == version
    assert (s.orient_dense_core and s.e2_orient) is orient


def test_branch_variants_stay_on_v1():
    # e5-brkga, e5-knap, ... build on Settings() (v1), so moving the default does not change them.
    assert Settings(search="brkga") == replace(VERSIONS["e5-v1"], search="brkga")


@pytest.mark.parametrize("name, engine, version", [("e5", "e5-v4", "e5-v4")])
def test_runs_record_the_version(name, engine, version):
    inst = random_lot(2)
    sol, diag = base.get(name)(inst, P, 3.0, 1)
    assert check(inst, sol, P).ok
    assert (diag["engine"], diag["version"]) == (engine, version)
