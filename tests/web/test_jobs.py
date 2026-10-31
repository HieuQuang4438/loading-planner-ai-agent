"""Tests for the web's job queue, lots from the client and error model (src.web.job_manager, src.web.api). Failing
jobs put the fake engines of
`tests.web.fake_engines` in place of e5 / e5-orient; every client is logged in."""
from __future__ import annotations

import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from src.bound import lower_bound
from src.engines import base, e1
from src.model import is_tipped
from src.web.job_manager import QUEUE_SIZE, JobManager
from src.web.lots import lot_from_client
from src.web.mode import SERVICE
from src.web.runstore import SqliteStore
from tests.web import fake_engines
from tests.web.support import logged_in, small_lot

QUICK = dataclasses.replace(SERVICE, time_range=(0.1, 600.0))  # lets a fake engine time out in under a second


def use(monkeypatch, fn) -> None:
    """Run `fn` whatever the orient flag picks."""
    monkeypatch.setitem(base._REGISTRY, "e5", fn)
    monkeypatch.setitem(base._REGISTRY, "e5-orient", fn)


@pytest.fixture()
def service(tmp_path, monkeypatch) -> TestClient:
    return logged_in(tmp_path, monkeypatch)


@pytest.fixture()
def quick(tmp_path, monkeypatch) -> TestClient:
    """The app with time limits down to 0.1 s."""
    monkeypatch.setattr("src.web.service.app.SERVICE", QUICK)
    return logged_in(tmp_path, monkeypatch)


def run(client: TestClient, **body) -> dict:
    started = client.post("/api/jobs", json=body)
    assert started.status_code == 202, started.json()
    return started.json()


def wait_done(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state["status"] not in ("queued", "running"):
            return state
        time.sleep(0.1)
    raise AssertionError("job still queued or running")


def assert_error(response, status: int, code: str) -> dict:
    body = response.json()
    assert response.status_code == status, body
    assert body["code"] == code and isinstance(body["message"], str) and isinstance(body["details"], list)
    return body


# --- error codes ---------------------------------------------------------------------------------


def test_invalid_input_names_the_line_and_field(service):
    lot = small_lot()
    lot["items"][0]["qty"] = 0
    lot["items"][1]["L"] = "wide"
    body = assert_error(service.post("/api/jobs", json={"lot": lot}), 422, "invalid_input")

    by_field = {(d["line"], d["field"]) for d in body["details"]}
    assert (lot["items"][1]["id"], "L") in by_field
    assert assert_error(service.post("/api/jobs", json={}), 422, "invalid_input")["details"][0]["field"] == "lot"


def test_validate_reports_problems_without_running(service):
    ok = service.post("/api/lots/validate", json=small_lot()).json()
    assert ok["ok"] is True and ok["details"] == [] and ok["bound"]["cost"] > 0 and ok["summary"]["items"] == 20
    lot = small_lot()
    lot["items"][0]["H"] = 9.0  # taller than any container
    checked = service.post("/api/lots/validate", json=lot).json()

    assert checked["ok"] is False
    assert checked["details"][0]["line"] == lot["items"][0]["id"]
    assert service.get("/api/runs").json() == []


def test_not_found_has_the_error_body(service):
    assert_error(service.get("/api/jobs/nope"), 404, "not_found")
    assert_error(service.get("/api/saved/nope"), 404, "not_found")


def test_queue_full(service, monkeypatch):
    use(monkeypatch, fake_engines.sleeper)
    jobs = [run(service, lot=small_lot(), time_limit=30.0) for _ in range(QUEUE_SIZE + 1)]
    assert [j["position"] for j in jobs[1:]] == list(range(1, QUEUE_SIZE + 1))

    assert_error(service.post("/api/jobs", json={"lot": small_lot(), "time_limit": 30.0}), 503, "queue_full")
    for job in reversed(jobs):
        service.post(f"/api/jobs/{job['id']}/stop")


# The crasher gets a long limit: a slow `spawn` start-up must not turn its crash into a timeout.
@pytest.mark.parametrize(("engine", "time_limit", "code"),
                         [(fake_engines.sleeper, 0.4, "timeout"), (fake_engines.crasher, 30.0, "engine_error")])
def test_failed_jobs_say_why(quick, monkeypatch, engine, time_limit, code):
    use(monkeypatch, engine)
    state = wait_done(quick, run(quick, lot=small_lot(), time_limit=time_limit)["id"])

    assert (state["status"], state["code"]) == ("failed", code)
    assert quick.get(f"/api/jobs/{state['id']}/result").status_code == 404


def test_invalid_solution_is_never_handed_out(service, monkeypatch):
    use(monkeypatch, fake_engines.stacker)
    state = wait_done(service, run(service, lot=small_lot(), time_limit=10.0)["id"])

    assert (state["status"], state["code"]) == ("failed", "invalid_solution")
    assert_error(service.get(f"/api/jobs/{state['id']}/result"), 404, "not_found")


# --- queue ---------------------------------------------------------------------------------------


def test_jobs_run_one_at_a_time_in_order(quick, monkeypatch):
    use(monkeypatch, fake_engines.sleeper)
    first = run(quick, lot=small_lot(), time_limit=0.4)
    second = run(quick, lot=small_lot(), time_limit=5.0)
    assert (second["status"], second["position"]) == ("queued", 1)

    assert wait_done(quick, first["id"])["code"] == "timeout"
    assert wait_done(quick, second["id"])["code"] == "timeout"


def test_stop_a_queued_and_a_running_job(service, monkeypatch):
    use(monkeypatch, fake_engines.sleeper)
    running = run(service, lot=small_lot(), time_limit=30.0)
    queued = run(service, lot=small_lot(), time_limit=10.0)

    stopped = service.post(f"/api/jobs/{queued['id']}/stop").json()
    assert (stopped["status"], stopped["position"], stopped["saved"]) == ("stopped", None, None)
    assert service.post(f"/api/jobs/{running['id']}/stop").json()["status"] == "stopped"
    assert wait_done(service, running["id"])["saved"] is None
    assert service.get("/api/runs").json() == []


# --- lots from the client ------------------------------------------------------------------------


def test_client_lot_runs_is_kept_with_its_lot_and_costs_and_reopens(service, monkeypatch):
    use(monkeypatch, e1.solve)  # fast; the store does not care which engine ran
    lot = small_lot()
    lot["container_types"][0]["cost"] = 1234.5  # the costs come with the lot, not from a table on the server
    state = wait_done(service, run(service, lot=lot, time_limit=10.0, orient=False)["id"])
    assert state["status"] == "done" and state["orient"] is False

    assert service.get(f"/api/jobs/{state['id']}/lot.json").json()["container_types"][0]["cost"] == 1234.5
    assert len(service.get(f"/api/jobs/{state['id']}/solution.json").json()["placements"]) == 20
    result = service.get(f"/api/jobs/{state['id']}/result").json()
    assert result["run"]["cost_table"][0] == {"id": lot["container_types"][0]["id"], "cost": 1234.5}
    assert service.get(f"/api/runs/{state['id']}").json()["check"]["ok"] is True


def test_the_flag_picks_the_engine_and_fixes_the_seed(tmp_path):
    jobs = JobManager(SqliteStore(tmp_path / "app.db"), SERVICE)
    job = jobs.start("e1", small_lot(), seed=7, time_limit=10.0, orient=True)
    jobs.stop(job.id)

    assert (job.engine, job.seed, job.orient) == ("e5-orient", 1, True)


def test_a_missing_orient_is_true():
    """A request without `orient` runs `e5-orient`; an explicit `false` still runs `e5`."""
    from src.web.api import RunRequest, request_orient

    missing = RunRequest(lot=small_lot())
    assert missing.orient is None
    assert request_orient(missing) is True
    assert request_orient(RunRequest(lot=small_lot(), orient=False)) is False
    assert request_orient(RunRequest(lot=small_lot(), orient=True)) is True


def test_a_job_without_orient_runs_the_orient_engine(service):
    job = run(service, lot=small_lot(), time_limit=10.0)
    assert job["orient"] is True
    service.post(f"/api/jobs/{job['id']}/stop")


def lot_with_fleet(n: int) -> dict:
    """The small lot with its quantities scaled until the lower-bound fleet has at least `n` containers."""
    lot = small_lot()
    for factor in range(1, 400):
        scaled = {**lot, "items": [{**i, "qty": i["qty"] * factor} for i in lot["items"]]}
        if sum(lower_bound(lot_from_client(scaled)).fleet.values()) >= n:
            return scaled
    raise AssertionError(f"no lot with a fleet of {n}")


def test_time_limit_left_out_follows_the_lot_size(service):
    small, large = small_lot(), lot_with_fleet(21)
    assert sum(lower_bound(lot_from_client(small)).fleet.values()) <= 20
    for lot, expected in ((small, 60.0), (large, 120.0)):
        state = run(service, lot=lot)
        service.post(f"/api/jobs/{state['id']}/stop")
        assert state["time_limit"] == expected
    state = run(service, lot=large, time_limit=30.0)  # a limit in the request wins
    service.post(f"/api/jobs/{state['id']}/stop")
    assert state["time_limit"] == 30.0


@pytest.mark.parametrize("time_limit", [5.0, 601.0])
def test_time_limit_range(service, time_limit):
    assert_error(service.post("/api/jobs", json={"lot": small_lot(), "time_limit": time_limit}), 422, "invalid_input")


def test_client_lot_size_limit(service, monkeypatch):
    monkeypatch.setattr("src.web.lots.MAX_CLIENT_ITEMS", 10)
    body = assert_error(service.post("/api/jobs", json={"lot": small_lot()}), 422, "invalid_input")
    assert "at most 10" in body["details"][0]["message"]


@pytest.mark.parametrize("orient", [False, True])
def test_the_run_reports_the_flag_and_the_tipped_pieces(service, orient):
    lot = small_lot()
    for entry in lot["items"]:
        entry["tippable"] = True
    state = wait_done(service, run(service, lot=lot, time_limit=10.0, orient=orient)["id"])
    assert state["status"] == "done" and state["orient"] is orient

    result = service.get(f"/api/jobs/{state['id']}/result").json()
    tipped = result["tipped"]
    assert result["run"]["orient"] is orient
    assert tipped["total"] == tipped["lying"] + tipped["edge"] + tipped["tipped"]
    assert tipped["total"] == sum(1 for p in result["placements"] if is_tipped(p["o"]))
    # No `total > 0` assertion: whether E5 / E5-orient tip a piece of this lot depends on the packing it finds.
