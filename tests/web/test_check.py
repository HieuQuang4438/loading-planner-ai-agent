"""Tests of `POST /api/check`, the checker as a service for the manual packing page:
a solution made by hand is judged by `src.checker`; nothing is stored and no job is created."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.web.support import sample_path
from src.checker import check
from src.engines import e1
from src.formats import instance_to_dict, read_instance, solution_from_dict, solution_to_dict
from src.model import Params
from src.web.api import MAX_CHECK_VIOLATIONS
from tests.web.support import logged_in

PARAMS = Params(delta=0.05, alpha=0.8)


@pytest.fixture(scope="module")
def lot() -> dict:
    return instance_to_dict(read_instance(sample_path("sample-small")))


@pytest.fixture(scope="module")
def solved(lot: dict) -> dict:
    """A valid solution of the lot, made by the E1 engine in-process."""
    instance = read_instance(sample_path("sample-small"))
    solution, _ = e1.solve(instance, PARAMS, 3.0, 1)
    assert check(instance, solution, PARAMS).ok
    return solution_to_dict(solution)


@pytest.fixture()
def service(tmp_path: Path, monkeypatch) -> TestClient:
    return logged_in(tmp_path, monkeypatch)


def post(client: TestClient, lot: dict, solution: dict, **extra):
    return client.post("/api/check", json={"lot": lot, "solution": solution, "delta": 0.05, "alpha": 0.8, **extra})


def test_valid_solution_has_no_violations_and_a_cost(service, lot, solved):
    r = post(service, lot, solved)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["check"]["ok"] is True and body["violations"] == [] and body["violations_truncated"] is False
    expected = check(read_instance(sample_path("sample-small")), solution_from_dict(solved), PARAMS).cost
    assert body["check"]["cost"] == expected
    assert body["bound"]["cost"] <= expected
    assert len(body["placements"]) == 20 and body["containers"], "the payload of the viewer"
    assert body["params"] == {"delta": 0.05, "alpha": 0.8}


def test_missing_piece_is_a_constraint_2_violation_naming_it(service, lot, solved):
    sol = copy.deepcopy(solved)
    gone = sol["placements"].pop(3)["item"]
    body = post(service, lot, sol).json()
    assert body["check"]["ok"] is False
    assert [(v["constraint"], v["items"]) for v in body["violations"]] == [(2, [gone])]
    assert body["violations"][0]["message"] == f"{gone}: not placed"


def test_overlapping_pieces_name_both_items(service, lot, solved):
    sol = copy.deepcopy(solved)
    a, b = sol["placements"][0], sol["placements"][1]
    b.update(k=a["k"], x=a["x"], y=a["y"], z=a["z"])
    body = post(service, lot, sol).json()
    overlaps = [v for v in body["violations"] if v["constraint"] == 5]
    assert any(set(v["items"]) == {a["item"], b["item"]} for v in overlaps)
    assert all(len(v["items"]) == 2 for v in overlaps)


def test_violations_are_not_trimmed_like_the_views_list(service, lot):
    """All 20 pieces unplaced and one open container: 20 violations, in the full list."""
    sol = {"instance": "sample-small", "params": {"delta": 0.05, "alpha": 0.8},
           "containers": [{"k": 1, "type": "40DC"}], "placements": [], "meta": {}}
    body = post(service, lot, sol).json()
    assert len(body["violations"]) == body["check"]["n_violations"] == 20
    assert MAX_CHECK_VIOLATIONS >= 2000


def test_empty_containers_are_allowed(service, lot, solved):
    sol = copy.deepcopy(solved)
    sol["containers"].append({"k": 99, "type": "20DC"})
    body = post(service, lot, sol).json()
    assert body["check"]["ok"] is True
    empty = next(c for c in body["containers"] if c["k"] == 99)
    assert empty["replay"] == [] and empty["L"] == 5.9
    assert body["check"]["cost"] == post(service, lot, solved).json()["check"]["cost"] + 0.6


def test_no_container_at_all_is_not_a_crash(service, lot):
    sol = {"instance": "sample-small", "params": {"delta": 0.05, "alpha": 0.8}, "containers": [], "placements": []}
    body = post(service, lot, sol).json()
    assert body["containers"] == [] and body["check"]["cost"] == 0
    assert len(body["violations"]) == 20


def test_params_come_from_the_request_not_the_solution(service, lot, solved):
    sol = copy.deepcopy(solved)
    sol["params"] = {"delta": 0.0, "alpha": 0.0}
    assert post(service, lot, sol, delta=0.5).json()["params"]["delta"] == 0.5


def test_a_disallowed_orientation_is_a_checker_violation(service, lot, solved):
    sol = copy.deepcopy(solved)
    sol["placements"][0]["o"] = "LHW"   # L1 is upright only
    body = post(service, lot, sol).json()
    assert any(v["constraint"] == 1 and v["items"] == [sol["placements"][0]["item"]] for v in body["violations"])


def test_bad_lot_is_422_with_the_error_body(service, lot, solved):
    bad = copy.deepcopy(lot)
    bad["items"][0]["qty"] = 0
    r = post(service, bad, solved)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "invalid_input" and body["details"] and body["details"][0]["line"] == "L1"


@pytest.mark.parametrize("mutate", [
    lambda s: s["placements"][0].update(item="ZZ#1"),
    lambda s: s["placements"][0].update(o="XYZ"),
    lambda s: s["placements"][0].update(x="left"),
    lambda s: s["containers"][0].update(type="99DC"),
    lambda s: s["placements"][0].pop("z"),
    lambda s: s.pop("placements"),
    lambda s: s.update(containers="oops"),
])
def test_bad_solution_is_422_never_a_crash(service, lot, solved, mutate):
    sol = copy.deepcopy(solved)
    mutate(sol)
    r = post(service, lot, sol)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "invalid_input"


@pytest.mark.parametrize("extra", [{"delta": -1}, {"alpha": 1.5}, {"alpha": -0.1}])
def test_bad_params_are_422(service, lot, solved, extra):
    assert post(service, lot, solved, **extra).status_code == 422


def test_missing_fields_are_422(service, lot):
    r = service.post("/api/check", json={"lot": lot})
    assert r.status_code == 422 and r.json()["code"] == "invalid_input"


def test_writes_nothing_and_creates_no_job(service, lot, solved):
    assert post(service, lot, solved).status_code == 200
    assert post(service, lot, {**solved, "placements": []}).status_code == 200
    assert service.get("/api/runs").json() == [], "no run kept"
    assert service.get("/api/jobs/anything").status_code == 404


def violation_of(body: dict, constraint: int, item: str) -> dict:
    return next(v for v in body["violations"] if v["constraint"] == constraint and item in v["items"])


def test_every_violation_carries_params(service, lot, solved):
    sol = copy.deepcopy(solved)
    sol["placements"].pop(3)
    sol["placements"][0]["x"] = -1.0
    body = post(service, lot, sol).json()
    assert body["violations"] and all(isinstance(v["params"], dict) for v in body["violations"])


def test_outside_container_params_give_the_box_and_the_container(service, lot, solved):
    sol = copy.deepcopy(solved)
    first = sol["placements"][0]
    first["x"] = -1.0
    v = violation_of(post(service, lot, sol).json(), 4, first["item"])
    type_id = next(u["type"] for u in sol["containers"] if u["k"] == first["k"])
    ctype = next(c for c in lot["container_types"] if c["id"] == type_id)
    assert v["params"]["box"]["x"] == -1.0 and v["params"]["box"]["l"] > 0
    assert v["params"]["container"] == {"type": type_id, "L": ctype["L"], "W": ctype["W"], "H": ctype["H"]}


def test_support_params_give_the_share_and_alpha(service, lot, solved):
    sol = copy.deepcopy(solved)
    first = sol["placements"][0]
    first["z"] = 0.5  # hovering: nothing under it
    p = violation_of(post(service, lot, sol, alpha=0.9).json(), 7, first["item"])["params"]
    assert p["alpha"] == 0.9 and p["supported"] < 0.9
    assert p["supported_area"] < p["base_area"] and p["base_area"] > 0


def test_unplaced_item_params_say_unplaced(service, lot, solved):
    sol = copy.deepcopy(solved)
    gone = sol["placements"].pop(3)["item"]
    assert violation_of(post(service, lot, sol).json(), 2, gone)["params"] == {"reason": "unplaced"}


def test_overlap_params_say_overlap_and_delta(service, lot, solved):
    sol = copy.deepcopy(solved)
    a, b = sol["placements"][0], sol["placements"][1]
    b.update(k=a["k"], x=a["x"], y=a["y"], z=a["z"])
    v = next(v for v in post(service, lot, sol).json()["violations"]
             if v["constraint"] == 5 and set(v["items"]) == {a["item"], b["item"]})
    assert v["params"] == {"kind": "overlap", "delta": 0.05}


def test_mass_params(service, lot, solved):
    heavy = copy.deepcopy(lot)
    total = sum(i["qty"] * i["mass"] for i in lot["items"])
    limit = max(i["mass"] for i in lot["items"]) + 1  # every piece still fits one container alone
    for t in heavy["container_types"]:
        t["max_mass"] = limit
    v = next(v for v in post(service, heavy, solved).json()["violations"] if v["constraint"] == 6)
    assert v["params"]["max_mass"] == limit and v["params"]["mass"] == pytest.approx(total) and v["params"]["type"]
