"""The pure rules of the lot editor: static/shared/lotrules.js is run with `node`.
The page wiring is checked on the source of the pages, as the form itself needs a DOM."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.builders import STANDARD_CONTAINERS

STATIC = Path(__file__).resolve().parents[2] / "src" / "web"
RULES_JS = STATIC / "static" / "shared" / "lotrules.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = """
import { pathToFileURL } from 'node:url';
const r = await import(pathToFileURL(process.argv[2]).href);
const a = JSON.parse(process.argv[3]);
console.log(JSON.stringify({ missing: a.ids.map((ids) => r.missingStandardTypes(ids).map((t) => t[0])),
  stack: a.stack.map((s) => r.stackingFields(s)), fromJson: a.items.map((i) => r.stackingFromJson(i)),
  posture: a.items.map((i) => r.postureFromJson(i)), fields: a.postures.map((p) => r.postureFields(p)),
  numbers: a.numbers.map((n) => r.numberOrRaw(n)), standard: r.STANDARD_TYPES,
  decimals: a.decimals.map((t) => r.readDecimal(t, 7)), shown: [0.05, 120, 0.8].map(r.inputText),
  local: r.localTotals(a.rows) }));
"""

IDS = [["20DC", "40DC", "40HC", "45HC"], ["20DC", "40DC"], ["45HC", "20DC"], [], [" 40DC ", "my-box"], ["40dc"]]
STACK = [  # the ticks and the texts behind them
    {"noStack": False, "loadText": "", "floorOnly": False, "tiersText": ""},
    {"noStack": True, "loadText": "130", "floorOnly": False, "tiersText": "3"},
    {"noStack": False, "loadText": "130,5", "floorOnly": True, "tiersText": "3"},
    {"noStack": True, "loadText": "", "floorOnly": True, "tiersText": ""},
    {"noStack": False, "loadText": " 50 ", "floorOnly": False, "tiersText": " 2 "},
    {"noStack": False, "loadText": "abc", "floorOnly": False, "tiersText": "1x"},
]
ITEMS = [
    {"load": 0, "tiers": 1},
    {"load": 0.0, "tiers": None},
    {"load": None, "tiers": 3},
    {"load": 130.1, "tiers": 2, "tippable": True},
    {"load": "abc", "tiers": 1},
    {"tippable": True, "orientations": ["LWH", "WLH", "LHW", "HLW"]},
    {"tippable": False, "orientations": ["LHW"]},
    {"orientations": ["LWH", "WLH"]},
    {"tippable": True, "orientations": None},
]
POSTURES = [
    {"tippable": False, "file": None}, {"tippable": True, "file": None},
    {"tippable": False, "file": {"tippable": True, "orientations": ["LWH", "WLH", "LHW", "HLW"]}},
    {"tippable": True, "file": {"orientations": ["LHW"]}},
]
NUMBERS = ["1", "1,5", " 2 ", "abc", "1e2", "-3", "0", "1,2,3"]
DECIMALS = ["0,05", "0.05", " 1 ", "", "  ", "abc", "1,2,3", "1 000"]
ROWS = [  # rows in order count, the others (blank, zero, text, a fraction of a piece) are left out
    {"qty": "10", "L": "1,2", "W": "1", "H": "0,5", "mass": "20"},
    {"qty": "2", "L": 1, "W": 1, "H": 1, "mass": 5.5},
    {"qty": "", "L": "1", "W": "1", "H": "1", "mass": "1"},
    {"qty": "3", "L": "x", "W": "1", "H": "1", "mass": "1"},
    {"qty": "2,5", "L": "1", "W": "1", "H": "1", "mass": "1"},
    {"qty": "1", "L": "1", "W": "1", "H": "1", "mass": "0"},
]


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict:
    driver = tmp_path_factory.mktemp("rules") / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    args = json.dumps({"ids": IDS, "stack": STACK, "items": ITEMS, "postures": POSTURES, "numbers": NUMBERS,
                       "decimals": DECIMALS, "rows": ROWS})
    done = subprocess.run([NODE, str(driver), str(RULES_JS), args], capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_missing_defaults_are_the_absent_ids_in_standard_order(out):
    assert out["missing"] == [
        [], ["40HC", "45HC"], ["40DC", "40HC"], ["20DC", "40DC", "40HC", "45HC"], ["20DC", "40HC", "45HC"],
        ["20DC", "40DC", "40HC", "45HC"]]


@needs_node
def test_standard_types_match_the_standard_cost_table(out):
    rows = {t[0]: t for t in out["standard"]}
    assert set(rows) == {c.id for c in STANDARD_CONTAINERS}
    for c in STANDARD_CONTAINERS:
        assert rows[c.id][1:] == pytest.approx([c.L, c.W, c.H, c.door_w, c.door_h, c.max_mass, c.cost])


@needs_node
def test_ticks_write_load_zero_and_tiers_one_and_blank_numbers_are_null(out):
    assert out["stack"] == [
        {"load": None, "tiers": None},                 # nothing ticked, blank: unlimited
        {"load": 0, "tiers": 3},                       # "Không được chồng": load 0, the text behind it is not sent
        {"load": 130.5, "tiers": 1},                   # "Chỉ nằm sàn": tiers 1; comma = decimal point
        {"load": 0, "tiers": 1},                       # both ticks
        {"load": 50, "tiers": 2},                      # numbers are trimmed
        {"load": "abc", "tiers": "1x"},                # not a number: the raw text, the server reports it
    ]


@needs_node
def test_lines_read_from_a_file_tick_load_zero_and_tiers_one(out):
    got = [(r["noStack"], r["loadText"], r["floorOnly"], r["tiersText"]) for r in out["fromJson"]]
    assert got == [
        (True, "", True, ""), (True, "", False, ""), (False, "", False, "3"), (False, "130.1", False, "2"),
        (False, "abc", True, ""), (False, "", False, ""), (False, "", False, ""), (False, "", False, ""), (False, "", False, "")]


@needs_node
def test_orientations_in_a_file_are_kept_as_they_came_and_the_rest_is_a_tick(out):
    assert out["posture"][3] == {"tippable": True, "file": None}
    assert out["posture"][0] == {"tippable": False, "file": None}
    assert out["posture"][5] == {"tippable": False, "file": {"orientations": ["LWH", "WLH", "LHW", "HLW"], "tippable": True}}
    assert out["posture"][6]["file"] == {"orientations": ["LHW"], "tippable": False}   # invalid sets are kept verbatim
    assert out["posture"][7]["file"] == {"orientations": ["LWH", "WLH"]}               # no `tippable` key: none invented
    assert out["posture"][8] == {"tippable": True, "file": None}                        # `orientations: null` is no list


@needs_node
def test_posture_fields_are_the_tick_or_the_file(out):
    assert out["fields"] == [
        {"tippable": False}, {"tippable": True},
        {"tippable": True, "orientations": ["LWH", "WLH", "LHW", "HLW"]}, {"orientations": ["LHW"]}]


@needs_node
def test_number_cells_read_comma_and_keep_junk_raw(out):
    assert out["numbers"] == [1, 1.5, 2, "abc", 100, -3, 0, "1,2,3"]





@needs_node
def test_decimal_boxes_read_comma_or_dot_blank_is_the_default_and_junk_is_nan(out):
    assert out["decimals"] == [0.05, 0.05, 1, 7, 7, None, None, None]   # NaN comes back as null in JSON
    assert out["shown"] == ["0,05", "120", "0,8"]


@needs_node
def test_local_totals_sum_only_the_rows_in_order(out):
    assert out["local"]["pieces"] == 12
    assert out["local"]["mass"] == pytest.approx(10 * 20 + 2 * 5.5)
    assert out["local"]["volume"] == pytest.approx(10 * 1.2 * 1 * 0.5 + 2)


TIME_DRIVER = """
import { pathToFileURL } from 'node:url';
const r = await import(pathToFileURL(process.argv[2]).href);
const a = JSON.parse(process.argv[3]);
console.log(JSON.stringify(a.cases.map((c) => r.timeDefault({ limits: a.limits, bound: c.bound, touched: c.touched }))));
"""
SIZE_LIMITS = [{"name": "small", "max_containers": 4, "seconds": 60}, {"name": "medium", "max_containers": 20, "seconds": 60},
               {"name": "large", "max_containers": None, "seconds": 120}]


@needs_node
def test_time_default_follows_the_size_until_the_person_edits_the_box(tmp_path):
    cases = [  # fleet of n containers (types split), touched?
        {"bound": {"fleet": {"40DC": 4}}, "touched": False},
        {"bound": {"fleet": {"40DC": 3, "20DC": 2}}, "touched": False},
        {"bound": {"fleet": {"40HC": 20}}, "touched": False},
        {"bound": {"fleet": {"40HC": 12, "20DC": 9}}, "touched": False},
        {"bound": {"fleet": {"40HC": 40}}, "touched": True},     # edited by hand: the line stays, the box is left alone
        {"bound": None, "touched": False},                        # lot not valid (yet): nothing to say
        {"bound": {"fleet": {}}, "touched": False},               # empty fleet counts as small
    ]
    driver = tmp_path / "time.mjs"
    driver.write_text(TIME_DRIVER, encoding="utf-8")
    done = subprocess.run([NODE, str(driver), str(RULES_JS), json.dumps({"limits": SIZE_LIMITS, "cases": cases})],
                          capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)

    assert [g["fill"] for g in got] == [60, 60, 60, 120, None, None, 60]
    assert got[0]["line"] == "Lô cỡ nhỏ (cận dưới 4 container): mặc định 60 s"
    assert got[2]["line"] == "Lô cỡ trung bình (cận dưới 20 container): mặc định 60 s"
    assert got[3]["line"] == "Lô cỡ lớn (cận dưới 21 container): mặc định 120 s"
    assert got[4] == {"line": "Lô cỡ lớn (cận dưới 40 container): mặc định 120 s", "seconds": 120, "fill": None}
    assert got[5] == {"line": None, "seconds": None, "fill": None}
