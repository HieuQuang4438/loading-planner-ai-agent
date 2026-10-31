"""Memory guard of the engine jobs (src.web.memguard, JobManager). The `/proc` readers
run on fake file contents; the kill runs a real child process and needs Linux (`/proc/<pid>/status`)."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pytest

from tests.web.support import sample_path
from src.engines import base, e1
from src.formats import instance_to_dict, read_instance
from src.web import db as webdb
from src.web import memguard, users
from src.web.job_manager import Job, JobManager
from src.web.runstore import SqliteStore
from tests.web import fake_engines

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="needs /proc/<pid>/status")
MEMINFO = "MemTotal:        8000000 kB\nMemFree:         1000000 kB\n"  # 7812.5 MB
MB = 1024**2


def put(tmp_path: Path, name: str, text: str | None) -> Path:
    path = tmp_path / name
    if text is not None:
        path.write_text(text, encoding="ascii")
    return path


def limits(tmp_path: Path, meminfo: str | None = MEMINFO, v2: str | None = None, v1: str | None = None):
    return {"meminfo": put(tmp_path, "meminfo", meminfo), "cgroup2": put(tmp_path, "max", v2),
            "cgroup1": put(tmp_path, "limit", v1)}


# --- threshold -----------------------------------------------------------------------------------


def test_default_is_75_percent_of_the_cgroup_v2_limit(tmp_path):
    assert memguard.default_limit_mb(**limits(tmp_path, v2=f"{7 * 1024 * MB}\n")) == pytest.approx(0.75 * 7 * 1024)


def test_cgroup_v2_max_means_no_limit_so_meminfo_counts(tmp_path):
    assert memguard.default_limit_mb(**limits(tmp_path, v2="max\n")) == pytest.approx(0.75 * 8000000 / 1024)


def test_cgroup_v1_limit_counts_only_when_below_memtotal(tmp_path):
    assert memguard.default_limit_mb(**limits(tmp_path, v1=f"{2048 * MB}\n")) == pytest.approx(0.75 * 2048)
    huge = memguard.default_limit_mb(**limits(tmp_path, v1="9223372036854771712\n"))  # cgroup v1 "no limit"
    assert huge == pytest.approx(0.75 * 8000000 / 1024)


def test_nothing_readable_means_no_guard_and_one_logged_line(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="src.web.memguard"):
        assert memguard.job_limit_mb({}, **limits(tmp_path, meminfo=None)) is None
    assert [r.getMessage() for r in caplog.records if "guard is off" in r.getMessage()] and len(caplog.records) == 1


def test_env_overrides_the_default_and_a_bad_value_falls_back(tmp_path, caplog):
    files = limits(tmp_path, v2=f"{1024 * MB}")
    assert memguard.job_limit_mb({"PLANNER_JOB_MEM_MB": "1500"}, **files) == 1500
    with caplog.at_level(logging.WARNING, logger="src.web.memguard"):
        assert memguard.job_limit_mb({"PLANNER_JOB_MEM_MB": "lots"}, **files) == pytest.approx(0.75 * 1024)
    assert "not a positive number" in caplog.text


def test_rss_sums_the_process_and_its_descendants(tmp_path):
    for pid, kb, kids in ((10, 2048, "11 12"), (11, 1024, ""), (12, 512, "13"), (13, 512, "")):
        (tmp_path / str(pid) / "task" / str(pid)).mkdir(parents=True)
        (tmp_path / str(pid) / "status").write_text(f"Name:\tx\nVmRSS:\t{kb} kB\n", encoding="ascii")
        (tmp_path / str(pid) / "task" / str(pid) / "children").write_text(kids, encoding="ascii")
    assert memguard.rss_mb(10, tmp_path) == pytest.approx((2048 + 1024 + 512 + 512) / 1024)
    assert memguard.rss_mb(999, tmp_path) is None


@pytest.mark.skipif(sys.platform == "linux", reason="the no-/proc path")
def test_without_proc_there_is_no_guard():
    assert memguard.rss_mb(1) is None
    assert memguard.job_limit_mb({}) is None


@linux_only
def test_rss_of_this_process_is_readable():
    assert memguard.rss_mb(__import__("os").getpid()) > 1


# --- the kill --------------------------------------------------------------------------------------


def lot() -> dict:
    return instance_to_dict(read_instance(sample_path("sample-small")))


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    # The orient flag picks the engine: e5 runs `fake` (set per test), e5-orient the quick E1 core.
    monkeypatch.setitem(base._REGISTRY, "e5-orient", e1.solve)
    db_path = tmp_path / "app.db"
    conn = webdb.connect(db_path)
    webdb.migrate(conn)
    users.add_user(conn, "alice", "a-long-enough-password-1")
    conn.close()

    def make(limit_mb: float | None, fake=fake_engines.sleeper) -> JobManager:
        import dataclasses

        from src.web.mode import SERVICE
        monkeypatch.setitem(base._REGISTRY, "e5", fake)
        mode = dataclasses.replace(SERVICE, time_range=(0.1, 600.0))
        return JobManager(SqliteStore(db_path), mode, mem_limit_mb=limit_mb, poll_interval=0.1)
    make.db_path = db_path
    return make


def finished(job: Job, timeout: float = 60.0) -> Job:
    end = time.monotonic() + timeout
    while job.status in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.05)
    assert job.status not in ("queued", "running")
    return job


@linux_only
def test_a_job_over_the_threshold_fails_out_of_memory_and_the_next_one_runs(manager):
    jobs = manager(100.0, fake_engines.hog)
    hog = jobs.start("e5", lot(), time_limit=60.0, owner=1, orient=False)
    normal = jobs.start("e5", lot(), time_limit=1.0, owner=1, orient=True)

    assert (finished(hog).status, hog.code) == ("failed", "out_of_memory")
    assert "100 MB" in hog.error and "ngắn hơn" in hog.error
    assert hog.solution is None and hog.view is None and hog.elapsed() < 30  # killed long before the hard limit
    assert hog.state()["code"] == "out_of_memory"
    assert (finished(normal).status, normal.code) == ("done", None)  # the guard does not touch a small job
    row = webdb.connect(manager.db_path).execute("SELECT status, code, cost, solution FROM runs WHERE job_id = ?",
                                                 (hog.id,)).fetchone()
    assert (row["status"], row["code"], row["cost"], row["solution"]) == ("failed", "out_of_memory", None, None)


@linux_only
def test_no_threshold_means_no_kill_and_the_hard_time_kill_still_works(manager):
    jobs = manager(None)
    job = finished(jobs.start("e5", lot(), time_limit=0.4, owner=1, orient=False))
    assert (job.status, job.code) == ("failed", "timeout")


@linux_only
def test_the_stop_button_still_ends_a_guarded_job(manager):
    jobs = manager(100000.0)
    job = jobs.start("e5", lot(), time_limit=30.0, owner=1, orient=False)
    while job.status == "queued" or job.proc is None:
        time.sleep(0.05)
    jobs.stop(job.id, 1)
    assert finished(job, 15.0).status == "stopped"


def test_a_guard_on_windows_is_not_needed_for_jobs_to_run(manager):
    """Whatever the platform, a job under a huge threshold runs normally (on Windows `rss_mb` just answers None)."""
    jobs = manager(1e9)
    job = finished(jobs.start("e5", lot(), time_limit=1.0, owner=1, orient=True))
    assert (job.status, job.code) == ("done", None)
