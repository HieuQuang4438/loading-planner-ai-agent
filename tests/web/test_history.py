"""Tests for the lots kept per user and their routes: documents read in the background by a mocked model,
points answered, revisions, what-if copies, delete with undo, and mode A runs. The documents are
data/probe (simulated)."""
from __future__ import annotations

import base64
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.llm.client import LLMError
from src.web.lotstore import MAX_DOCUMENT_BYTES
from tests.extract.probe_readings import BY_FILE, LABEL, PL, SPEC
from tests.web.support import JSON, ORIGIN, login, make_app

PROBE = Path(__file__).resolve().parents[2] / "data" / "probe"


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.busy: set[str] = set()  # files whose next reading fails as an overloaded model does

    def generate(self, name, parts, schema):
        self.calls += 1
        file = parts[0].text.removeprefix("Tên tệp: ")
        if file in self.busy:
            self.busy.discard(file)
            raise LLMError("Gemini đang quá tải, thử lại sau ít phút")
        return BY_FILE[file]


@pytest.fixture()
def app(tmp_path, monkeypatch):
    fake = FakeLLM()
    application, _ = make_app(tmp_path, monkeypatch, names=("alice", "bob"), llm=lambda: fake)
    application.state.fake = fake
    return application


def client(app, name="alice") -> TestClient:
    c = TestClient(app, base_url=ORIGIN, headers=JSON)
    assert login(c, name).status_code == 200
    return c


def files(*names):
    return {"files": [{"name": n, "data": base64.b64encode((PROBE / n).read_bytes()).decode()} for n in names]}


def read_lot(c, name="Lô xuất T11", docs=(PL, SPEC, LABEL)):
    lot = c.post("/api/lots", json={"name": name}).json()
    c.post(f"/api/lots/{lot['id']}/documents", json=files(*docs))
    return wait_read(c, lot["id"])


def wait_read(c, lot_id, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = c.get(f"/api/lots/{lot_id}").json()
        if body["documents"] and all(d["status"] in ("read", "failed") for d in body["documents"]):
            if len(body["lot"]["lines"]) or any(d["status"] == "failed" for d in body["documents"]):
                return body
        time.sleep(0.05)
    raise AssertionError("documents not read in time")


def answer_all(c, body):
    while open_ := [p for p in body["lot"]["points"] if p["resolved_at"] is None]:
        r = c.post(f"/api/lots/{body['id']}/points/{open_[0]['id']}", json={"rev": body["rev"], "choice": 0})
        assert r.status_code == 200, r.json()
        body = r.json()
    r = c.post(f"/api/lots/{body['id']}/confirm", json={"rev": body["rev"]})
    assert r.status_code == 200, r.json()
    return r.json()


# --- lots and documents --------------------------------------------------------------------------------------------


def test_documents_are_read_merged_and_their_points_found(app):
    c = client(app)
    body = read_lot(c)
    assert [d["status"] for d in body["documents"]] == ["read"] * 3 and app.state.fake.calls == 3
    assert [line["id"] for line in body["lot"]["lines"]] == ["SKU-A", "SKU-B", "SKU-C", "SKU-D", "SKU-A-2"]
    assert len(body["lot"]["points"]) == 7 and body["lot"]["excluded"][0]["sku"] == "SKU-E"
    listed = c.get("/api/lots").json()
    assert [(x["name"], x["documents"], x["open_points"], x["last_run"]) for x in listed] == [("Lô xuất T11", 3, 7, None)]


def test_an_unsupported_or_too_large_file_is_refused_at_once(app):
    c = client(app)
    lot = c.post("/api/lots", json={"name": "x"}).json()
    bad = {"files": [{"name": "notes.docx", "data": base64.b64encode(b"x").decode()}]}
    assert c.post(f"/api/lots/{lot['id']}/documents", json=bad).status_code == 422
    big = {"files": [{"name": "big.csv", "data": base64.b64encode(b"a" * (MAX_DOCUMENT_BYTES + 1)).decode()}]}
    assert c.post(f"/api/lots/{lot['id']}/documents", json=big).status_code == 422
    assert c.get(f"/api/lots/{lot['id']}").json()["documents"] == []


def test_a_document_added_later_keeps_what_was_confirmed(app):
    c = client(app)
    body = answer_all(c, read_lot(c, docs=(PL, SPEC)))
    c.post(f"/api/lots/{body['id']}/documents", json=files(LABEL))
    end = time.monotonic() + 20
    while (again := c.get(f"/api/lots/{body['id']}").json())["rev"] == body["rev"] and time.monotonic() < end:
        time.sleep(0.05)
    c_mass = next(x for x in again["lot"]["lines"] if x["id"] == "SKU-C")["mass"]
    assert c_mass["status"] == "confirmed" and len(c_mass["sources"]) == 2


def test_a_failed_document_leaves_nothing_out_and_is_read_again_on_request(app):
    c = client(app)
    app.state.fake.busy = {PL}
    body = read_lot(c)
    failed = next(d for d in body["documents"] if d["name"] == PL)
    assert failed["status"] == "failed" and failed["error"].startswith("Gemini đang quá tải")
    assert body["lot"]["lines"] == [] and body["lot"]["excluded"] == []  # no packing list read: nothing left out
    assert body["settled"] is True
    read = next(d for d in body["documents"] if d["status"] == "read")
    assert c.post(f"/api/lots/{body['id']}/documents/{read['id']}/read", json={}).status_code == 409  # only a failed one
    r = c.post(f"/api/lots/{body['id']}/documents/{failed['id']}/read", json={})
    assert r.status_code == 202
    body = wait_read(c, body["id"])
    assert all(d["status"] == "read" for d in body["documents"]) and body["lot"]["lines"] and body["settled"]


def test_another_users_lot_is_not_found(app):
    body = read_lot(client(app))
    bob = client(app, "bob")
    assert bob.get(f"/api/lots/{body['id']}").status_code == 404
    assert bob.get("/api/lots").json() == []
    assert bob.post(f"/api/lots/{body['id']}/points/1", json={"rev": body["rev"], "choice": 0}).status_code == 404


# --- answers and revisions -----------------------------------------------------------------------------------------


def test_an_answer_on_an_old_revision_is_a_conflict(app):
    c = client(app)
    body = read_lot(c)
    first = c.post(f"/api/lots/{body['id']}/points/1", json={"rev": body["rev"], "choice": 0})
    assert first.status_code == 200 and first.json()["rev"] == body["rev"] + 1
    late = c.post(f"/api/lots/{body['id']}/points/2", json={"rev": body["rev"], "choice": 0})
    assert late.status_code == 409 and late.json()["code"] == "conflict"


def test_an_answer_names_its_user_and_a_bad_one_is_refused(app):
    c = client(app)
    body = read_lot(c)
    bad = c.post(f"/api/lots/{body['id']}/points/4", json={"rev": body["rev"], "values": {"SKU-B.mass": -1}})
    assert bad.status_code == 422 and "không hợp lệ" in bad.json()["message"]
    ok = c.post(f"/api/lots/{body['id']}/points/4", json={"rev": body["rev"], "choice": 0}).json()
    b_mass = next(x for x in ok["lot"]["lines"] if x["id"] == "SKU-B")["mass"]
    assert (b_mass["value"], b_mass["confirmed_by"]) == (26.0, "alice")


def test_a_document_removed_takes_what_it_gave_with_it(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    label = next(d for d in body["documents"] if d["name"] == LABEL)
    r = c.delete(f"/api/lots/{body['id']}/documents/{label['id']}")
    assert r.status_code == 200
    after = r.json()
    assert [d["name"] for d in after["documents"]] == [PL, SPEC]
    sources = {s["file"] for x in after["lot"]["lines"] for n in ("qty", "dims", "mass", "posture", "stacking", "fragile")
               for s in x[n]["sources"]}
    assert LABEL not in sources
    c_marks = next(x for x in after["lot"]["lines"] if x["id"] == "SKU-C")["posture"]
    assert c_marks["status"] != "confirmed"  # confirmed on the label: asked again
    assert c.delete(f"/api/lots/{body['id']}/documents/{label['id']}").status_code == 404


def test_a_dropped_row_comes_back_from_the_documents_when_its_point_is_answered_again(app):
    c = client(app)
    body = read_lot(c)
    ids = [x["id"] for x in body["lot"]["lines"]]
    dropped = c.post(f"/api/lots/{body['id']}/points/1", json={"rev": body["rev"], "choice": 2}).json()
    assert "SKU-A-2" not in [x["id"] for x in dropped["lot"]["lines"]]
    kept = c.post(f"/api/lots/{body['id']}/points/1", json={"rev": dropped["rev"], "choice": 0})
    assert kept.status_code == 200 and [x["id"] for x in kept.json()["lot"]["lines"]] == ids


def test_the_lot_is_confirmed_only_once_no_point_is_open(app):
    c = client(app)
    body = read_lot(c)
    r = c.post(f"/api/lots/{body['id']}/confirm", json={"rev": body["rev"]})
    assert r.status_code == 409 and r.json()["code"] == "not_ready" and r.json()["details"]


# --- what-if copies and delete ------------------------------------------------------------------------------------


def test_a_copy_is_its_own_lot_in_the_same_family_and_not_listed(app):
    c = client(app)
    body = read_lot(c)
    copy = c.post("/api/lots", json={"name": "Lô xuất T11 (bỏ SKU-B)", "parent_id": body["id"],
                                     "note": "theo yêu cầu trong chat"}).json()
    assert copy["parent_id"] == body["id"] and copy["lot"]["lines"] == body["lot"]["lines"]
    assert [f["id"] for f in copy["family"]] == [body["id"], copy["id"]]
    assert [x["id"] for x in c.get("/api/lots").json()] == [body["id"]]


def test_a_deleted_lot_can_be_restored(app):
    c = client(app)
    lot = c.post("/api/lots", json={"name": "x"}).json()
    assert c.delete(f"/api/lots/{lot['id']}").status_code == 200
    assert c.get(f"/api/lots/{lot['id']}").status_code == 404 and c.get("/api/lots").json() == []
    assert c.post(f"/api/lots/{lot['id']}/restore", json={}).status_code == 200
    assert [x["id"] for x in c.get("/api/lots").json()] == [lot["id"]]


def test_a_lot_is_renamed_on_its_revision_only_by_its_owner(app):
    c = client(app)
    lot = c.post("/api/lots", json={"name": "x"}).json()
    r = c.patch(f"/api/lots/{lot['id']}", json={"rev": lot["rev"], "name": "  Lô T12  "})
    assert r.status_code == 200 and r.json()["name"] == "Lô T12" and r.json()["lot"]["name"] == "Lô T12"
    assert [x["name"] for x in c.get("/api/lots").json()] == ["Lô T12"]
    assert c.patch(f"/api/lots/{lot['id']}", json={"rev": lot["rev"], "name": "y"}).status_code == 409
    assert c.patch(f"/api/lots/{lot['id']}", json={"rev": r.json()["rev"], "name": "   "}).status_code == 422
    bob = client(app, "bob")
    assert bob.patch(f"/api/lots/{lot['id']}", json={"rev": r.json()["rev"], "name": "z"}).status_code == 404


# --- mode A --------------------------------------------------------------------------------------------------


def test_a_lot_not_confirmed_does_not_run(app):
    c = client(app)
    body = read_lot(c)
    r = c.post(f"/api/lots/{body['id']}/runs", json={"mode": "a"})
    assert r.status_code == 409 and r.json()["code"] == "not_ready"
    assert c.post(f"/api/lots/{body['id']}/runs", json={"mode": "b"}).status_code == 422  # no fleet
    r = c.post(f"/api/lots/{body['id']}/runs", json={"mode": "b", "fill": {"fleet": {"40HC": 1}}})
    assert r.status_code == 409 and r.json()["code"] == "not_ready"


def test_a_confirmed_lot_runs_in_mode_a_and_its_run_is_kept_with_the_lot(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    job = c.post(f"/api/lots/{body['id']}/runs", json={"mode": "a", "time_limit": 10}).json()
    end = time.monotonic() + 90
    while (state := c.get(f"/api/jobs/{job['id']}").json())["status"] in ("queued", "running"):
        assert time.monotonic() < end
        time.sleep(0.2)
    assert state["status"] == "done", state
    result = c.get(f"/api/jobs/{job['id']}/result").json()
    assert result["check"]["ok"]
    runs = c.get(f"/api/lots/{body['id']}").json()["runs"]
    assert [(r["job_id"], r["mode"], r["lot_id"]) for r in runs] == [(job["id"], "a", body["id"])]
    assert runs[0]["containers"] and c.get("/api/lots").json()[0]["last_run"]["job_id"] == job["id"]
    assert runs[0]["placed"] == runs[0]["total"] == len(result["placements"])


def test_mode_a_compares_with_the_bound_and_the_single_type_baselines(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    out = c.post(f"/api/lots/{body['id']}/compare", json={}).json()
    assert out["bound"]["cost"] == 2500.0
    assert [b["type"] for b in out["baselines"]] == ["20GP", "40GP", "40HC"] and all(b["ok"] for b in out["baselines"])
    assert out["cheapest_single"]["type"] == "40GP" and out["cheapest_single"]["cost"] == 4600.0
    assert c.get("/api/plan/containers").json()["simulated"] is True


def done(c, job_id):
    end = time.monotonic() + 90
    while (state := c.get(f"/api/jobs/{job_id}").json())["status"] in ("queued", "running"):
        assert time.monotonic() < end
        time.sleep(0.2)
    assert state["status"] == "done", state


def test_a_run_is_compared_with_its_own_lot_and_says_when_the_lot_changed_since(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    job = c.post(f"/api/lots/{body['id']}/runs", json={"mode": "a", "time_limit": 10}).json()
    done(c, job["id"])
    before = c.post(f"/api/runs/{job['id']}/compare", json={}).json()
    assert before["lot_changed"] is False
    costs = lambda out: (out["bound"], [(b["type"], b["containers"], b["cost"]) for b in out["baselines"]])  # noqa: E731
    assert costs(before) == costs(c.post(f"/api/lots/{body['id']}/compare", json={}).json())
    lot = c.get(f"/api/lots/{body['id']}").json()
    line = lot["lot"]["lines"][0]
    edited = c.post(f"/api/lots/{body['id']}/lines/{line['id']}", json={"rev": lot["rev"], "values": {"qty": line["qty"]["value"] * 3}})
    assert edited.status_code == 200, edited.json()
    after = c.post(f"/api/runs/{job['id']}/compare", json={}).json()
    assert after["lot_changed"] is True
    assert costs(after) == costs(before)  # the run's lot, not the lot now
    assert c.post(f"/api/lots/{body['id']}/compare", json={}).json()["bound"] != before["bound"]  # the lot now
    assert c.post("/api/runs/nope/compare", json={}).status_code == 404


def test_a_run_takes_the_advanced_settings_and_the_baseline_packs_with_them(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    lid = body["id"]
    for bad in ({"delta": -0.1}, {"alpha": 1.5}):
        assert c.post(f"/api/lots/{lid}/runs", json={"mode": "a", "time_limit": 10, **bad}).status_code == 422
    job = c.post(f"/api/lots/{lid}/runs", json={"mode": "a", "time_limit": 10, "delta": 0.1, "alpha": 1, "orient": False}).json()
    state = c.get(f"/api/jobs/{job['id']}").json()
    assert state["orient"] is False  # no line may tip in the probe: off whatever is asked
    c.post(f"/api/jobs/{job['id']}/stop", json={})
    out = c.post(f"/api/lots/{lid}/compare", json={"delta": 0.1, "alpha": 1}).json()
    assert (out["settings"]["delta"], out["settings"]["alpha"]) == (0.1, 1)


# --- mode B --------------------------------------------------------------------------------------------------


def test_mode_b_packs_the_containers_at_hand_by_priority_and_reports_what_is_left(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    priority = ["SKU-D", "SKU-B", "SKU-C", "SKU-A", "SKU-A-2"]
    fill = {"fleet": {"40HC": 1}, "priority": priority, "partial": True}
    job = c.post(f"/api/lots/{body['id']}/runs", json={"mode": "b", "time_limit": 10, "fill": fill}).json()
    end = time.monotonic() + 90
    while (state := c.get(f"/api/jobs/{job['id']}").json())["status"] in ("queued", "running"):
        assert time.monotonic() < end
        time.sleep(0.2)
    assert state["status"] == "done", state
    result = c.get(f"/api/jobs/{job['id']}/result").json()
    assert result["check"]["ok"] and len(result["containers"]) == 1
    out = result["fill"]
    assert [x["id"] for x in out["lines"]] == priority and 0 < out["placed"] < out["total"] == 380
    base = c.post(f"/api/lots/{body['id']}/compare", json={"mode": "b", "fill": fill}).json()
    assert base["ok"] and base["containers"] == 1
    own = c.post(f"/api/runs/{job['id']}/compare", json={}).json()
    assert own.pop("lot_changed") is False and own["lines"] == base["lines"]
    placed = [x["placed"] for x in out["lines"]]
    assert placed >= [x["placed"] for x in base["lines"]]  # lexicographic: never behind the baseline
    runs = c.get(f"/api/lots/{body['id']}").json()["runs"]
    assert [(r["job_id"], r["mode"]) for r in runs] == [(job["id"], "b")]
    assert (runs[0]["placed"], runs[0]["total"]) == (out["placed"], 380)  # the lists say pieces, not a cost
    assert c.get(f"/api/runs/{job['id']}").json()["fill"] == out  # reopened from the account


def test_mode_b_refuses_a_fleet_or_priority_that_does_not_fit_the_lot(app):
    c = client(app)
    body = answer_all(c, read_lot(c))
    for fill in ({"fleet": {"45HC": 1}}, {"fleet": {"40HC": 0}}, {"fleet": {"40HC": 1}, "priority": ["SKU-A"]}):
        r = c.post(f"/api/lots/{body['id']}/runs", json={"mode": "b", "fill": fill})
        assert r.status_code == 422, fill


# --- rows edited, added, taken out ------------------------------------------------------------------------------


def test_rows_are_edited_added_taken_out_and_put_back_and_kept_when_a_document_is_added(app):
    c = client(app)
    body = read_lot(c, docs=(PL, SPEC))
    lid = body["id"]
    new = {"qty": 10, "dims": {"L": 1.0, "W": 0.8, "H": 0.6}, "mass": 40, "posture": "upright",
           "stacking": {"kind": "free"}, "fragile": False}
    r = c.post(f"/api/lots/{lid}/lines", json={"rev": body["rev"], "sku": "SKU-Z", "values": new})
    assert r.status_code == 201 and r.json()["lot"]["lines"][-1]["id"] == "SKU-Z"
    r = c.post(f"/api/lots/{lid}/lines/SKU-Z", json={"rev": r.json()["rev"], "values": {"qty": 12}})
    assert r.json()["lot"]["lines"][-1]["qty"]["value"] == 12
    bad = c.post(f"/api/lots/{lid}/lines/SKU-B", json={"rev": r.json()["rev"], "values": {"mass": 30}})
    assert bad.status_code == 422 and "câu hỏi H" in bad.json()["message"]  # SKU-B's mass is asked at a point
    r = c.post(f"/api/lots/{lid}/lines/SKU-B/drop", json={"rev": r.json()["rev"]})
    assert "SKU-B" not in [x["id"] for x in r.json()["lot"]["lines"]]
    c.post(f"/api/lots/{lid}/documents", json=files(LABEL))  # merged again: SKU-Z kept, SKU-B still out
    end = time.monotonic() + 20
    while time.monotonic() < end:
        after = c.get(f"/api/lots/{lid}").json()
        if all(d["status"] == "read" for d in after["documents"]) and any(
                s["file"] == LABEL for x in after["lot"]["lines"] for s in x["posture"]["sources"]):
            break
        time.sleep(0.05)
    ids = [x["id"] for x in after["lot"]["lines"]]
    assert "SKU-Z" in ids and "SKU-B" not in ids
    back = c.post(f"/api/lots/{lid}/lines/SKU-B/restore", json={"rev": after["rev"]})
    assert back.status_code == 200 and "SKU-B" in [x["id"] for x in back.json()["lot"]["lines"]]
