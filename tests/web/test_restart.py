"""Solve again from an earlier run (`from_job`): the run brings its own lot and settings,
belongs to its owner, and only an engine that takes a `start` accepts it. Runs are kept in `app.db`."""
from __future__ import annotations

import dataclasses

import pytest

from src.engines import base, e1, e5
from src.web.errors import BadRequest
from src.web.job_manager import JobManager
from src.web.mode import SERVICE
from src.web.runstore import SqliteStore
from tests.web import fake_engines
from tests.web.test_jobs import assert_error, run, use, wait_done
from tests.web.test_runstore import HEADERS, Setup


@pytest.fixture()
def both(tmp_path, monkeypatch) -> Setup:
    use(monkeypatch, e1.solve)  # the first run is fast, whichever engine
    return Setup(tmp_path, monkeypatch)


def make_startable(monkeypatch, name: str = "e5") -> None:
    names = {name, f"{name}-orient"}   # the first run had the flag on, so its restart runs the orient engine
    for each in names:
        monkeypatch.setitem(base._REGISTRY, each, fake_engines.restartable)
    monkeypatch.setattr(base, "_STARTABLE", base._STARTABLE | names)


def again(setup: Setup, job_id: str, **body) -> dict:
    return wait_done(setup.client, run(setup.client, from_job=job_id, time_limit=10.0, **body)["id"])


def test_the_new_run_takes_the_lot_and_settings_of_the_old_one_and_its_solution(both, monkeypatch):
    first = both.finish(delta=0.07, alpha=0.65)
    make_startable(monkeypatch)
    state = again(both, first["id"], delta=0.5, alpha=0.1)  # the client's own values are ignored
    assert state["status"] == "done", state
    assert state["id"] != first["id"]
    view = both.client.get(f"/api/jobs/{state['id']}/result").json()
    diag = view["run"]["diagnostics"]
    assert diag["got_start"] is True and (diag["delta"], diag["alpha"]) == (0.07, 0.65)
    assert view["run"]["delta"] == 0.07 and view["run"]["alpha"] == 0.65
    assert view["check"]["ok"] is True
    assert view["check"]["cost"] == both.client.get(f"/api/jobs/{first['id']}/result").json()["check"]["cost"]
    assert both.client.get(f"/api/jobs/{state['id']}/lot.json").json() == \
        both.client.get(f"/api/jobs/{first['id']}/lot.json").json()


def test_the_new_run_remembers_where_it_started(both, monkeypatch):
    first = both.finish()
    make_startable(monkeypatch)
    state = again(both, first["id"])
    assert state["status"] == "done"
    saved = both.client.get(both.path(state["id"])).json()
    assert saved["check"]["ok"] is True


def test_a_start_is_not_asked_for_without_from_job(both, monkeypatch):
    make_startable(monkeypatch)
    state = both.finish()
    diag = both.client.get(f"/api/jobs/{state['id']}/result").json()["run"]["diagnostics"]
    assert diag["got_start"] is False


def test_an_unknown_job_is_404(both, monkeypatch):
    make_startable(monkeypatch)
    for bad in ("000000000000", "x", "../.."):
        assert_error(both.client.post("/api/jobs", json={"from_job": bad, "time_limit": 10.0}, headers=HEADERS),
                     404, "not_found")


def test_another_users_run_is_a_404(tmp_path, monkeypatch):
    use(monkeypatch, e1.solve)
    setup = Setup(tmp_path, monkeypatch)
    first = setup.finish()
    make_startable(monkeypatch)
    res = setup.other.post("/api/jobs", json={"from_job": first["id"], "time_limit": 10.0}, headers=HEADERS)
    assert_error(res, 404, "not_found")


def test_an_engine_without_start_is_refused(both, monkeypatch):
    first = both.finish()
    monkeypatch.setattr(base, "_STARTABLE", base._STARTABLE - {"e5", "e5-orient"})
    assert_error(both.client.post("/api/jobs", json={"from_job": first["id"], "time_limit": 10.0}, headers=HEADERS),
                 422, "invalid_input")


def test_a_request_without_a_lot_or_from_job_is_refused(both):
    assert_error(both.client.post("/api/jobs", json={"time_limit": 10.0}, headers=HEADERS), 422, "invalid_input")


def test_a_manager_without_restart_refuses_it(tmp_path):
    mode = dataclasses.replace(SERVICE, restart=False)
    jobs = JobManager(SqliteStore(tmp_path / "app.db"), mode)
    with pytest.raises(BadRequest, match="giải lại"):
        jobs.start("e5", None, from_job="0123456789ab")


def test_solving_again_with_the_real_engine_costs_no_more(both, monkeypatch, tmp_path):
    first = both.finish()
    use(monkeypatch, e5.solve)
    state = wait_done(both.client, run(both.client, from_job=first["id"], time_limit=10.0)["id"], timeout=120.0)
    assert state["status"] == "done", state
    old = both.client.get(f"/api/jobs/{first['id']}/result").json()
    new = both.client.get(f"/api/jobs/{state['id']}/result").json()
    assert new["check"]["ok"] is True
    assert new["check"]["cost"] <= old["check"]["cost"] + 1e-9
    assert new["run"]["diagnostics"]["start"] == "used"
