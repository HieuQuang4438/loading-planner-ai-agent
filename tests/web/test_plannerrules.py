"""The pure helpers of the app's screens (static/shared/plannerrules.js) run with `node`: values as the
screens write them, decimals typed either way, lot totals, the CSV packing plan and the comparison of two runs."""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
RULES_JS = Path(__file__).resolve().parents[2] / "src" / "web" / "static" / "shared" / "plannerrules.js"
DRIVER = """
import { pathToFileURL } from 'node:url';
const r = await import(pathToFileURL(process.argv[2]).href);
const input = JSON.parse(process.argv[3]);
console.log(JSON.stringify(r[input.fn](...input.args)));
"""


def call(tmp_path, fn, *args):
    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    done = subprocess.run([NODE, str(driver), str(RULES_JS), json.dumps({"fn": fn, "args": args})],
                          capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def field(value):
    return {"value": value, "status": "confirmed", "sources": []}


LINE = {"id": "SKU-A", "qty": field(200), "dims": field({"L": 0.6, "W": 0.4, "H": 0.5}), "mass": field(12.5)}


def test_values_are_written_as_the_screens_write_them(tmp_path):
    got = [call(tmp_path, "valueText", n, v, u) for n, v, u in [
        ("qty", 200, "carton"), ("qty", 10, "pallet"), ("dims", {"L": 0.6, "W": 0.4, "H": 0.45}, None),
        ("mass", 12.5, None), ("posture", "upright", None), ("stacking", {"kind": "limited", "tiers": 2}, None),
        ("stacking", {"kind": "none", "tiers": None}, None), ("fragile", True, None), ("mass", None, None)]]
    assert got == ["200 thùng", "10 pallet", "0,60 × 0,40 × 0,45", "12,5", "Chỉ đứng", "Tối đa 2 tầng", "Không chồng",
                   "Dễ vỡ", "Chưa có"]


def test_decimals_may_be_typed_with_a_comma_or_a_dot(tmp_path):
    assert [call(tmp_path, "parseDecimal", t) for t in ["12,5", "12.5", "2 300,00", "", "abc"]] == [12.5, 12.5, 2300, None, None]


def test_totals_count_only_the_fields_that_have_a_value(tmp_path):
    other = {**LINE, "id": "SKU-B", "qty": field(10), "mass": field(None)}
    got = call(tmp_path, "totals", {"lines": [LINE, other]})
    assert (got["lines"], got["pieces"], got["kg"]) == (2, 210, 2500) and round(got["m3"], 2) == 25.2


def view():
    """Two containers; the second is loaded in the replay order 3, 2 (indices into all placements)."""
    box = {"l": 0.6, "w": 0.4, "h": 0.5, "y": 0, "z": 0}
    return {
        "containers": [{"k": 1, "type": "40GP", "replay": [0], "cost": 2300, "volume": 0.12, "mass": 25, "L": 12, "W": 2.35, "H": 2.39},
                       {"k": 2, "type": "20GP", "replay": [2, 1], "cost": 1500, "volume": 0.24, "mass": 50, "L": 5.9, "W": 2.35, "H": 2.39}],
        "placements": [{"item": "SKU-A#1", "line": "SKU-A", "k": 1, "x": 0, **box},
                       {"item": "SKU-A-2#1", "line": "SKU-A-2", "k": 2, "x": 0, **box},
                       {"item": "SKU-A-2#2", "line": "SKU-A-2", "k": 2, "x": 0.65, **box}],
        "check": {"ok": True, "cost": 3800},
    }


def test_the_csv_plan_numbers_containers_from_one_in_loading_order_with_the_codes_as_written(tmp_path):
    text = call(tmp_path, "csvPlan", view(), {"SKU-A": "SKU-A", "SKU-A-2": "SKU-A"})
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:5] == ["container", "loai", "thu_tu_xep", "kien", "ma_hang"]
    assert [r[:5] for r in rows[1:]] == [["1", "40GP", "1", "SKU-A#1", "SKU-A"], ["2", "20GP", "1", "SKU-A-2#2", "SKU-A"],
                                         ["2", "20GP", "2", "SKU-A-2#1", "SKU-A"]]


def test_two_runs_compare_metric_by_metric_and_name_what_differs_in_their_inputs(tmp_path):
    a, b = view(), view()
    b["containers"] = b["containers"][:1]
    b["check"]["cost"] = 2300
    lot_a = {"items": [{"id": "SKU-A", "qty": 1}, {"id": "SKU-A-2", "qty": 2}],
             "container_types": [{"id": "40GP", "cost": 2300}, {"id": "20GP", "cost": 1500}]}
    lot_b = {"items": [{"id": "SKU-A", "qty": 1}], "container_types": [{"id": "40GP", "cost": 2000}]}
    got = call(tmp_path, "runCompare", a, b, lot_a, lot_b)
    rows = {r["label"]: r for r in got["rows"]}
    assert rows["Tổng cước"]["delta"].startswith("−") and rows["Container"]["delta"] == "−1 × 20GP"
    assert got["changes"] == ["SKU-A-2: 2 → 0, không có trong lần B", "Cước 40GP: 2 300,00 USD → 2 000,00 USD",
                              "20GP: không dùng ở lần B"]


def test_two_runs_into_containers_at_hand_compare_pieces_placed_not_freight(tmp_path):
    a, b = view(), view()
    a["fill"] = {"fleet": {"40GP": 1, "20GP": 1}, "priority": ["SKU-A", "SKU-A-2"], "partial": True, "placed": 3, "total": 5}
    b["fill"] = {"fleet": {"40GP": 2, "20GP": 0}, "priority": ["SKU-A-2", "SKU-A"], "partial": False, "placed": 5, "total": 5}
    lot = {"items": [{"id": "SKU-A", "qty": 1}], "container_types": [{"id": "40GP", "cost": 2300}]}
    got = call(tmp_path, "runCompare", a, b, lot, {**lot, "container_types": []}, ["3", "4"])
    rows = {r["label"]: r for r in got["rows"]}
    assert "Tổng cước" not in rows and "Số kiện" not in rows
    assert (rows["Hàng đã xếp"]["a"], rows["Hàng đã xếp"]["b"], rows["Hàng đã xếp"]["delta"]) == ("3 / 5 kiện", "5 / 5 kiện", "+2 kiện")
    assert got["changes"] == ["Container có sẵn: 1 × 40GP, 1 × 20GP → 2 × 40GP", "Thứ tự ưu tiên: SKU-A, SKU-A-2 → SKU-A-2, SKU-A",
                              "Cho xếp một phần mã hàng: có → không"]


def test_the_lists_name_a_run_by_its_number_and_what_it_came_to(tmp_path):
    runs = [{"job_id": "j3", "status": "done", "mode": "b", "cost": 1500, "placed": 17, "total": 71, "containers": ["20GP"]},
            {"job_id": "j2", "status": "failed", "mode": "a", "cost": None, "containers": []},
            {"job_id": "j1", "status": "done", "mode": "a", "cost": 4600, "placed": 71, "total": 71, "containers": ["40GP", "40GP"]}]
    assert [call(tmp_path, "runOutcome", r) for r in runs] == ["17 / 71 kiện · 1 × 20GP", "Lỗi", "4 600,00 USD · 2 × 40GP"]
    assert call(tmp_path, "runNumbers", runs) == {"j3": 3, "j2": 2, "j1": 1}
    assert [r["job_id"] for r in call(tmp_path, "comparable", runs, "j1")] == ["j1"]  # not the failed one, not mode B


def test_the_solving_clock_waits_runs_and_settles_past_the_chosen_time(tmp_path):
    queued = call(tmp_path, "solveClock", {"status": "queued", "position": 2, "time_limit": 60})
    running = call(tmp_path, "solveClock", {"status": "running", "elapsed": 30.6, "time_limit": 60, "hard_limit": 75})
    over = call(tmp_path, "solveClock", {"status": "running", "elapsed": 64, "time_limit": 60, "hard_limit": 75})
    assert (queued["kind"], queued["clock"], queued["pct"]) == ("queued", "Thứ 2", 0)
    assert (running["clock"], running["small"], running["pct"]) == ("0:30", "/ 1:00", 51)
    assert over["kind"] == "over" and over["pct"] == 100 and "0:11" in over["note"]
