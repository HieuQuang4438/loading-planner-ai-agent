"""Tests for the run store (src.web.runstore): runs in `app.db`, each owned by a user. Failing jobs use the fake engines
of `tests.web.fake_engines`."""
from __future__ import annotations

import dataclasses
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.engines import e1
from src.formats import read_instance
from src.web import db as webdb
from src.web import users
from src.web.job_manager import Job, JobManager
from src.web.mode import SERVICE
from src.web.runstore import KEEP_DAYS, Outcome, SqliteStore
from tests.web import fake_engines
from tests.web.support import JSON as HEADERS
from tests.web.support import ORIGIN, PASSWORD, login, make_app, sample_path, small_lot
from tests.web.test_jobs import assert_error, run, use, wait_done


class Setup:
    """The app and its clients, one per user."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path, self.monkeypatch = tmp_path, monkeypatch
        self.db_path = tmp_path / "app.db"
        make_app(tmp_path, monkeypatch, names=("alice", "bob"))
        self.start()

    def start(self) -> None:
        """(Re)make the app, as a restart does; the clients are new, so the users log in again."""
        _, _ = make_app(self.tmp_path, self.monkeypatch, seed=False)
        from src.web.service.app import create_app

        app = create_app()
        self.client = TestClient(app, base_url=ORIGIN, headers=HEADERS)
        self.other = TestClient(app, base_url=ORIGIN, headers=HEADERS)
        for client, name in ((self.client, "alice"), (self.other, "bob")):
            assert login(client, name).status_code == 200

    def path(self, job_id: str) -> str:
        return f"/api/runs/{job_id}"

    def finish(self, **body) -> dict:
        state = wait_done(self.client, run(self.client, lot=small_lot(), time_limit=10.0, **body)["id"])
        assert state["status"] == "done"
        return state


@pytest.fixture()
def sqlite(tmp_path, monkeypatch) -> Setup:
    use(monkeypatch, e1.solve)  # fast; the store does not care which engine ran
    return Setup(tmp_path, monkeypatch)


both = sqlite  # the store the tests below run on


# --- reopening gives what the run gave ----------------------------------------------


def test_reopened_run_gives_the_same_view_lot_and_solution(both):
    state = both.finish()
    live = both.client.get(f"/api/jobs/{state['id']}/result").json()
    reopened = both.client.get(both.path(state["id"]))
    assert reopened.status_code == 200
    body = reopened.json()
    assert body.keys() == live.keys()
    for key in live.keys() - {"run"}:
        assert body[key] == live[key], key
    # the same run info down to the diagnostics; only where it was opened from differs
    assert {**body["run"], "source": ""} == {**live["run"], "source": ""}
    assert "mở lại" in body["run"]["source"]
    assert both.client.get(f"{both.path(state['id'])}/lot.json").json() == \
        both.client.get(f"/api/jobs/{state['id']}/lot.json").json()
    assert both.client.get(f"{both.path(state['id'])}/solution.json").json() == \
        both.client.get(f"/api/jobs/{state['id']}/solution.json").json()


def test_a_restart_keeps_the_run_but_not_the_job(both):
    state = both.finish()
    both.start()
    assert_error(both.client.get(f"/api/jobs/{state['id']}"), 404, "not_found")
    assert both.client.get(both.path(state["id"])).json()["check"]["ok"] is True
    assert both.client.get(f"{both.path(state['id'])}/solution.json").status_code == 200


def test_a_failed_job_has_nothing_to_reopen(both):
    use(both.monkeypatch, fake_engines.crasher)
    state = wait_done(both.client, run(both.client, lot=small_lot(), time_limit=10.0)["id"])
    assert state["status"] == "failed"
    assert_error(both.client.get(both.path(state["id"])), 404, "not_found")

    use(both.monkeypatch, fake_engines.stacker)
    state = wait_done(both.client, run(both.client, lot=small_lot(), time_limit=10.0)["id"])
    assert state["code"] == "invalid_solution"
    for suffix in ("", "/lot.json", "/solution.json"):
        assert_error(both.client.get(f"{both.path(state['id'])}{suffix}"), 404, "not_found")
    assert_error(both.client.get(f"/api/jobs/{state['id']}/result"), 404, "not_found")


def test_an_unknown_id_is_404(both):
    both.finish()
    for suffix in ("", "/lot.json", "/solution.json"):
        assert_error(both.client.get(f"{both.path('000000000000')}{suffix}"), 404, "not_found")


# --- SQLite: runs belong to users -----------------------------------------------------------------


def rows(db_path: Path, sql: str = "SELECT * FROM runs ORDER BY created_at") -> list[sqlite3.Row]:
    conn = webdb.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_a_row_holds_the_run_in_the_documented_columns(sqlite):
    state = sqlite.finish()
    (row,) = rows(sqlite.db_path)
    assert row["job_id"] == state["id"] and row["lot_name"] == "sample-small"
    assert (row["status"], row["code"]) == ("done", None) and row["cost"] > 0
    assert row["user_id"] == rows(sqlite.db_path, "SELECT id FROM users WHERE name = 'alice'")[0]["id"]
    assert all(row[c] for c in ("settings", "lot", "result", "solution", "created_at"))


def test_another_users_run_is_a_404_everywhere(sqlite):
    state = sqlite.finish()
    job = state["id"]
    missing = sqlite.other.get("/api/runs/000000000000")
    for suffix in ("", "/lot.json", "/solution.json"):
        res = sqlite.other.get(f"/api/runs/{job}{suffix}")
        assert_error(res, 404, "not_found")
        assert res.json()["message"].replace("000000000000", job) == missing.json()["message"].replace("000000000000", job)
    res = sqlite.other.delete(f"/api/runs/{job}", headers=HEADERS)
    assert_error(res, 404, "not_found")
    assert sqlite.other.get("/api/runs").json() == []
    assert sqlite.client.get(f"/api/runs/{job}").status_code == 200  # still there for its owner


def test_another_users_job_is_a_404_while_it_runs_and_after(sqlite):
    use(sqlite.monkeypatch, fake_engines.sleeper)
    job = run(sqlite.client, lot=small_lot(), time_limit=10.0)["id"]
    try:
        while sqlite.client.get(f"/api/jobs/{job}").json()["status"] != "running":
            time.sleep(0.05)
        for method, path in (("GET", ""), ("GET", "/result"), ("GET", "/lot.json"), ("GET", "/solution.json"),
                             ("POST", "/stop")):
            res = sqlite.other.request(method, f"/api/jobs/{job}{path}", headers=HEADERS)
            assert_error(res, 404, "not_found")
        assert sqlite.client.get(f"/api/jobs/{job}").json()["status"] == "running"  # bob's stop did nothing
    finally:
        sqlite.client.post(f"/api/jobs/{job}/stop", headers=HEADERS)
    wait_done(sqlite.client, job)

    use(sqlite.monkeypatch, e1.solve)
    done = sqlite.finish()["id"]
    for path in ("", "/result", "/lot.json", "/solution.json"):
        assert_error(sqlite.other.get(f"/api/jobs/{done}{path}"), 404, "not_found")
    assert sqlite.client.get(f"/api/jobs/{done}/result").status_code == 200


def test_the_list_is_the_users_own_newest_first_with_failed_runs(sqlite):
    first = sqlite.finish()["id"]
    use(sqlite.monkeypatch, fake_engines.crasher)
    failed = wait_done(sqlite.client, run(sqlite.client, lot=small_lot(), time_limit=10.0)["id"])["id"]
    use(sqlite.monkeypatch, fake_engines.stacker)
    invalid = wait_done(sqlite.client, run(sqlite.client, lot=small_lot(), time_limit=10.0)["id"])["id"]
    listed = sqlite.client.get("/api/runs").json()
    assert [r["job_id"] for r in listed] == [invalid, failed, first]
    assert set(listed[0]) == {"job_id", "lot_name", "created_at", "status", "code", "cost", "lot_id", "mode", "containers",
                                "placed", "total"}
    assert [(r["status"], r["code"]) for r in listed] == [
        ("failed", "invalid_solution"), ("failed", "engine_error"), ("done", None)]
    assert listed[2]["cost"] > 0 and listed[1]["cost"] is None
    assert listed[2]["placed"] == listed[2]["total"] > 0 and listed[1]["placed"] is None  # pieces in the plan
    assert sqlite.other.get("/api/runs").json() == []


def test_a_run_is_deleted_by_its_owner_only(sqlite):
    job = sqlite.finish()["id"]
    assert sqlite.client.delete(f"/api/runs/{job}", headers=HEADERS).json() == {"ok": True}
    assert_error(sqlite.client.get(f"/api/runs/{job}"), 404, "not_found")
    assert sqlite.client.get("/api/runs").json() == []
    assert_error(sqlite.client.delete(f"/api/runs/{job}", headers=HEADERS), 404, "not_found")


def test_deleting_a_user_deletes_their_runs(sqlite):
    sqlite.finish()
    conn = webdb.connect(sqlite.db_path)
    conn.execute("DELETE FROM users WHERE name = 'alice'")
    conn.close()
    assert rows(sqlite.db_path) == []


# --- SQLite: temp directories, hand stops, purge, concurrency ---------------------------------------


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    """A JobManager on a SqliteStore, a `tmp` dir for the engine's files and no time floor, so a kill takes 1.5 s."""
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    db_path = tmp_path / "app.db"
    conn = webdb.connect(db_path)
    webdb.migrate(conn)
    users.add_user(conn, "alice", PASSWORD)
    conn.close()
    mode = dataclasses.replace(SERVICE, time_range=(0.1, 600.0))
    jobs = JobManager(SqliteStore(db_path), mode)
    return jobs, db_path, tmp, monkeypatch


def finished(jobs: JobManager, job: Job, timeout: float = 60.0) -> Job:
    end = time.monotonic() + timeout
    while job.status in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.05)
    assert job.status not in ("queued", "running")
    return job


def test_the_temp_dir_is_empty_after_a_done_failed_invalid_and_killed_job(manager):
    jobs, db_path, tmp, monkeypatch = manager
    expected = {e1.solve: ("done", None), fake_engines.crasher: ("failed", "engine_error"),
                fake_engines.stacker: ("failed", "invalid_solution"), fake_engines.sleeper: ("failed", "timeout")}
    for engine, outcome in expected.items():
        use(monkeypatch, engine)
        job = finished(jobs, jobs.start("e5", small_lot(), time_limit=1.0, owner=1, orient=False))
        assert (job.status, job.code) == outcome, engine
        assert list(tmp.iterdir()) == [], engine
    stored = {r["job_id"]: (r["status"], r["code"]) for r in rows(db_path)}
    assert len(stored) == 4 and set(stored.values()) == set(expected.values())
    killed = next(r for r in rows(db_path) if r["code"] == "timeout")
    assert killed["solution"] is None and killed["cost"] is None  # nothing to hand out


def test_a_hand_stopped_job_leaves_no_row_and_no_temp_dir(manager):
    jobs, db_path, tmp, monkeypatch = manager
    use(monkeypatch, fake_engines.sleeper)
    running = jobs.start("e5", small_lot(), time_limit=30.0, owner=1)
    queued = jobs.start("e5", small_lot(), time_limit=1.0, owner=1)
    while running.status != "running" or not any(tmp.iterdir()):
        time.sleep(0.05)
    jobs.stop(queued.id, 1)
    jobs.stop(running.id, 1)
    deadline = time.monotonic() + 30
    while any(tmp.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert list(tmp.iterdir()) == []
    assert (running.status, queued.status, running.saved) == ("stopped", "stopped", None)
    time.sleep(0.3)
    assert rows(db_path) == []


def test_a_store_that_cannot_write_fails_the_job_and_still_cleans_up(manager, monkeypatch):
    jobs, db_path, tmp, _ = manager
    use(monkeypatch, e1.solve)

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("src.web.runstore.connect", broken)
    job = finished(jobs, jobs.start("e5", small_lot(), time_limit=1.0, owner=1))
    assert (job.status, job.code) == ("failed", "engine_error") and "không lưu được" in job.error
    assert job.view is None and list(tmp.iterdir()) == []


def make_store(tmp_path: Path, now: datetime, keep_days: int = KEEP_DAYS) -> tuple[SqliteStore, Path]:
    db_path = tmp_path / "app.db"
    conn = webdb.connect(db_path)
    webdb.migrate(conn)
    if not conn.execute("SELECT 1 FROM users").fetchall():
        users.add_user(conn, "alice", PASSWORD)
    conn.close()
    return SqliteStore(db_path, keep_days, lambda: now), db_path


def insert_run(db_path: Path, job_id: str, created_at: datetime) -> None:
    conn = webdb.connect(db_path)
    conn.execute(
        "INSERT INTO runs (job_id, user_id, created_at, lot_name, status, settings, lot, result)"
        " VALUES (?, 1, ?, 'x', 'done', '{}', '{}', '{}')", (job_id, created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
    conn.close()


def test_runs_older_than_the_keep_days_are_purged_at_start_and_after_each_write(tmp_path):
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    store, db_path = make_store(tmp_path, now)
    insert_run(db_path, "old000000001", now - timedelta(days=KEEP_DAYS, minutes=1))
    insert_run(db_path, "new000000001", now - timedelta(days=KEEP_DAYS - 1))
    SqliteStore(db_path, KEEP_DAYS, lambda: now)  # a new app purges once
    assert [r["job_id"] for r in rows(db_path)] == ["new000000001"]

    insert_run(db_path, "old000000002", now - timedelta(days=45))
    job = Job("w00000000001", "e5", "client:x", 1, 1.0, 0.05, 0.8, _instance(), owner=1)
    space = store.begin(job, {})
    store.finish(job, space, None, Outcome("failed", "engine_error", "boom"))  # a write purges too
    assert sorted(r["job_id"] for r in rows(db_path)) == ["new000000001", "w00000000001"]
    assert not space.dir.exists()


def _instance():
    return read_instance(sample_path("sample-small"))


def test_planner_run_days_sets_the_keep_time(tmp_path, monkeypatch):
    setup = Setup(tmp_path, monkeypatch)
    insert_run(setup.db_path, "old000000003", datetime.now(timezone.utc) - timedelta(days=3))
    monkeypatch.setenv("PLANNER_RUN_DAYS", "7")
    setup.start()
    assert len(rows(setup.db_path)) == 1
    monkeypatch.setenv("PLANNER_RUN_DAYS", "2")
    setup.start()
    assert rows(setup.db_path) == []


def test_reading_works_while_the_worker_writes(tmp_path):
    now = datetime.now(timezone.utc)
    store, db_path = make_store(tmp_path, now)
    errors: list[BaseException] = []

    def write() -> None:
        try:
            for n in range(40):
                job = Job(f"{n:012x}", "e5", "client:x", 1, 1.0, 0.05, 0.8, _instance(), owner=1)
                store.finish(job, store.begin(job, {}), None, Outcome("failed", "engine_error", "boom"))
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            errors.append(exc)

    writer = threading.Thread(target=write)
    writer.start()
    seen = 0
    while writer.is_alive():
        seen = max(seen, len(store.list_runs(1)))
    writer.join()
    assert errors == [] and len(store.list_runs(1)) == 40 and seen <= 40
