"""The posture rule of the lot form: static/shared/orient.js is run with `node` on a
table of items, and the lines it writes are checked to be readable and solvable. The JS is the code the page uses."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from src.formats import instance_to_dict
from src.model import ALL_ORIENTATIONS, UPRIGHT_ORIENTATIONS
from src.web.lots import lot_from_client, lot_issues
from tests.builders import STANDARD_CONTAINERS

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

ORIENT_JS = Path(__file__).resolve().parents[2] / "src" / "web" / "static" / "shared" / "orient.js"

LEVELS = ("upright", "lying", "all")
ALL = list(ALL_ORIENTATIONS)
UP, W_UP, L_UP = ["LWH", "WLH"], ["LHW", "HLW"], ["WHL", "HWL"]   # the pairs, by the dimension pointing up

# name -> (L, W, H), kinds of the pairs H, W, L, codes per level, enabled levels
CASES = {
    "flat": ((1.2, 1.0, 0.3), ["đứng", "dựng cao", "dựng cao"],
             {"upright": UP, "lying": UP, "all": ALL}, {"upright": True, "lying": False, "all": True}),
    "tall": ((0.6, 0.5, 1.5), ["đứng", "nằm", "nằm"],
             {"upright": UP, "lying": ALL, "all": ALL}, {"upright": True, "lying": True, "all": False}),
    "middle": ((1.2, 0.5, 0.8), ["đứng", "nằm", "dựng cao"],
               {"upright": UP, "lying": UP + W_UP, "all": ALL}, {"upright": True, "lying": True, "all": True}),
    "w_equals_h": ((1.2, 0.8, 0.8), ["đứng", "lật", "dựng cao"],
                   {"upright": UP, "lying": UP, "all": ALL}, {"upright": True, "lying": False, "all": True}),
    "l_equals_h": ((0.8, 0.5, 0.8), ["đứng", "nằm", "lật"],
                   {"upright": UP, "lying": UP + W_UP, "all": ALL}, {"upright": True, "lying": True, "all": True}),
    "cube": ((0.5, 0.5, 0.5), ["đứng", "lật", "lật"],
             {"upright": UP, "lying": UP, "all": ALL}, {"upright": True, "lying": False, "all": True}),
}

DRIVER = """
import { pathToFileURL } from 'node:url';
const o = await import(pathToFileURL(process.argv[2]).href);
const out = {};
for (const [name, [L, W, H]] of Object.entries(JSON.parse(process.argv[3]))) {
  const dims = { L, W, H };
  const r = { kinds: o.UPS.map((u) => o.kindOf(u, dims)), codes: {}, enabled: {}, fields: {}, back: {}, custom: {} };
  for (const level of ['upright', 'lying', 'all']) {
    r.codes[level] = o.codesFor(level, null, dims);
    r.enabled[level] = o.levelEnabled(level, dims);
    r.fields[level] = o.fileFields(level, null, dims);
    r.back[level] = o.levelFromFile(r.fields[level].tippable, r.fields[level].orientations, dims);
  }
  for (const pairs of [['W'], ['H', 'W'], ['W', 'L'], ['H', 'W', 'L'], ['L']]) {
    const f = o.fileFields('custom', pairs, dims);
    r.custom[pairs.join('')] = { codes: o.codesFor('custom', pairs, dims), fields: f, back: o.levelFromFile(f.tippable, f.orientations, dims) };
  }
  out[name] = r;
}
out.__valid = [
  [true, undefined], [false, null], [true, ['LWH', 'WLH']], [false, ['LWH', 'WLH']], [true, ['LHW', 'HLW']],   // valid
  [true, []], [true, 'LWH'], [true, ['LWH']], [true, ['LWH', 'WLH', 'XYZ']], [false, ['LHW', 'HLW']], [true, ['LWH', 'LWH', 'WLH']],
].map(([t, c]) => o.orientationsValid(t, c));
out.__junk = [
  o.levelFromFile(true, 'LWH', null), o.levelFromFile(false, ['LWH'], null), o.levelFromFile(true, [], null),
  o.levelFromFile(true, ['LWH', 'WLH', 'XYZ'], null), o.levelFromFile(false, 7, null), o.levelFromFile(true, null, undefined),
];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict:
    driver = tmp_path_factory.mktemp("orient") / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    dims = json.dumps({name: case[0] for name, case in CASES.items()})
    done = subprocess.run([NODE, str(driver), str(ORIENT_JS), dims], capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("name", CASES)
def test_kinds_codes_and_enabled_levels(results, name):
    _, kinds, codes, enabled = CASES[name]
    assert results[name]["kinds"] == kinds
    assert results[name]["codes"] == codes
    assert results[name]["enabled"] == enabled


@pytest.mark.parametrize("name", CASES)
def test_file_fields_follow_the_default_rule(results, name):
    fields = results[name]["fields"]
    assert fields["upright"] == {"tippable": False}
    assert fields["all"] == {"tippable": True}
    codes = CASES[name][2]["lying"]
    assert fields["lying"] == ({"tippable": True} if codes == ALL else {"tippable": True, "orientations": codes})


@pytest.mark.parametrize("name", CASES)
def test_every_level_reads_back_with_its_codes(results, name):
    enabled = CASES[name][3]
    for level in LEVELS:
        back = results[name]["back"][level]
        # a level the form disables (same codes as the smaller one) reads back as the smaller level
        assert back["level"] == (level if enabled[level] else LEVELS[LEVELS.index(level) - 1]), (name, level)
        assert results[name]["codes"][back["level"]] == results[name]["codes"][level]


def test_custom_sets_round_trip_through_the_file_fields(results):
    only_lying = results["middle"]["custom"]["W"]
    assert only_lying["codes"] == W_UP
    assert only_lying["fields"] == {"tippable": True, "orientations": W_UP}
    assert only_lying["back"] == {"level": "custom", "pairs": ["W"]}
    assert results["middle"]["custom"]["HW"]["back"]["level"] == "lying"   # upright + the lying pair is "Được nằm" here
    assert results["flat"]["custom"]["HW"]["back"] == {"level": "custom", "pairs": ["H", "W"]}
    assert results["flat"]["custom"]["HWL"]["fields"] == {"tippable": True}   # all three pairs = the `tippable` default
    assert results["flat"]["custom"]["WL"]["fields"] == {"tippable": True, "orientations": W_UP + L_UP}
    assert results["flat"]["custom"]["L"]["codes"] == L_UP


def test_invalid_sets_are_told_apart_so_the_form_can_keep_them_raw(results):
    assert results["__valid"] == [True] * 5 + [False] * 6


def test_odd_input_never_throws_and_shows_as_custom(results):
    junk = results["__junk"]
    assert [j["level"] for j in junk] == ["custom"] * 5 + ["all"]
    assert junk[1]["pairs"] == [] and junk[3]["pairs"] == ["H"]


# ---- what the form writes is a lot the server reads and a solver can pack ---------------------------------------

def item(line_id: str, case: str, fields: dict, qty: int = 4) -> dict:
    length, width, height = CASES[case][0]
    return {"id": line_id, "qty": qty, "L": length, "W": width, "H": height, "mass": 20.0, "tiers": 3, "load": None, **fields}


def form_lot() -> dict:
    """One line per case, with the fields orient.js produced for it (the expected dicts of the table above)."""
    return {
        "name": "form-lot",
        "container_types": [asdict(t) for t in STANDARD_CONTAINERS],
        "items": [
            item("flat", "flat", {"tippable": True}),                                     # "Mọi tư thế"
            item("tall", "tall", {"tippable": True}),                                     # "Được nằm" = all six: no key
            item("middle", "middle", {"tippable": True, "orientations": UP + W_UP}),      # "Được nằm"
            item("weqh", "w_equals_h", {"tippable": False}),                              # "Chỉ đứng"
            item("leqh", "l_equals_h", {"tippable": True, "orientations": W_UP}),         # "Tùy chọn": only lying
            item("cube", "cube", {"tippable": True, "orientations": UP + L_UP}),          # "Tùy chọn": upright + L up
        ],
    }


def test_form_lot_is_read_by_the_server():
    lot = form_lot()

    assert lot_issues(lot) == []
    inst = lot_from_client(lot)
    assert {ln.id: ln.allowed for ln in inst.items} == {
        "flat": ALL_ORIENTATIONS, "tall": ALL_ORIENTATIONS, "middle": tuple(UP + W_UP),
        "weqh": UPRIGHT_ORIENTATIONS, "leqh": tuple(W_UP), "cube": tuple(UP + L_UP),
    }
    assert "orientations" not in instance_to_dict(inst)["items"][0]



def test_python_posture_kind_agrees_with_kind_of(tmp_path):
    from src.model import ItemLine
    from src.web.view import posture_kind

    names = {"nằm": "lying", "dựng cao": "edge", "lật": "tipped"}
    dims = [(1.2, 0.5, 0.8), (1.2, 0.8, 0.8), (0.8, 0.5, 0.8), (0.5, 0.5, 0.5), (1.2, 1.0, 0.3), (0.6, 0.5, 1.5), (1.0, 0.8 + 1e-10, 0.8)]
    driver = tmp_path / "kinds.mjs"
    driver.write_text("""
import { pathToFileURL } from 'node:url';
const o = await import(pathToFileURL(process.argv[2]).href);
const kinds = JSON.parse(process.argv[3]).map(([L, W, H]) => ['W', 'L'].map((u) => o.kindOf(u, { L, W, H })));
console.log(JSON.stringify(kinds));
""", encoding="utf-8")
    done = subprocess.run([NODE, str(driver), str(ORIENT_JS), json.dumps(dims)], capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    for (length, width, height), kinds in zip(dims, json.loads(done.stdout)):
        ln = ItemLine(id="X", qty=1, L=length, W=width, H=height, mass=1.0, tippable=True, tiers=1, load=None)
        assert [posture_kind("LHW", ln), posture_kind("WHL", ln)] == [names[k] for k in kinds], (length, width, height)
