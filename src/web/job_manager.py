"""Engine jobs of the web: a FIFO queue run by one worker thread, so one job at a time; each job runs through
`src.jobs`: its own process, hard-killed at `HARD_KILL_FACTOR * time_limit`, the solution always through
`src.checker`. Every job not stopped by hand is kept as a run by the `RunStore` (`src.web.runstore`), a row of
`app.db`, so a restart keeps it. A job takes a lot as JSON, its container types and costs included.
"""
from __future__ import annotations

import collections
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.engines import base, fill
from src.formats import instance_from_dict, instance_to_dict, read_solution, solution_from_dict, solution_to_dict
from src.jobs import HARD_KILL_FACTOR, RunResult, collect_result, run_settings, spawn_one
from src.model import Instance, Params, Solution
from src.web.errors import BadRequest, LotNotFound, QueueFull
from src.web.lots import lot_from_client
from src.web.memguard import rss_mb
from src.web.mode import (DEFAULT_ALPHA, DEFAULT_DELTA, DEFAULT_SEED, FILL_ENGINES, SERVICE, SERVICE_TIME_LIMIT, Mode,
                           check_engine)
from src.web.runstore import CLIENT_PREFIX, Outcome, RunSpace, RunStore, engine_files
from src.web.view import build_view, trim_diagnostics

QUEUE_SIZE = 5  # jobs waiting, not counting the running one (1A): 5 x 600 s is ~75 min of wait at most
KEEP_FINISHED = 100  # finished jobs kept in memory; their runs stay on disk


@dataclass
class Job:
    id: str
    engine: str
    lot: str  # `client:<name>`
    seed: int
    time_limit: float
    delta: float
    alpha: float
    instance: Instance | None = field(default=None, repr=False)
    orient: bool = False  # the "let the engine tip pieces" flag: picks e5-orient over e5
    created: float = field(default_factory=time.monotonic)
    started: float | None = None
    finished: float | None = None
    status: str = "queued"  # queued | running | done | stopped | failed
    code: str | None = None  # why it failed: timeout | out_of_memory | engine_error | invalid_solution
    error: str | None = None
    view: dict[str, Any] | None = None
    proc: Any = None
    saved: str | None = None  # run id under the runs dir, once the job has written its settings
    solution: Solution | None = field(default=None, repr=False)  # what the engine returned, kept after its files go
    owner: int | None = None  # user id with login on: only the owner sees the job; None without login
    from_job: str | None = None  # the earlier run this one continues from
    start: Solution | None = field(default=None, repr=False)  # that run's solution, handed to the engine
    lot_id: int | None = None  # the product lot this run is of; None for a lot sent as JSON
    mode: str | None = None  # "a" | "b" (docs/product/brief.md §2.2)

    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        return (self.finished or time.monotonic()) - self.started

    def state(self, position: int | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "position": position,  # 0: running, n: n-th in the queue, None: finished
            "elapsed": round(self.elapsed(), 2),
            "time_limit": self.time_limit,
            "hard_limit": HARD_KILL_FACTOR * self.time_limit,
            "code": self.code,
            "error": self.error,
            "has_result": self.view is not None,
            "saved": self.saved,
            "orient": self.orient,
        }


class JobManager:
    """One engine job at a time: parallel jobs would fight over CPU and skew both costs. Others wait in a FIFO
    queue of `QUEUE_SIZE`."""

    def __init__(self, store: RunStore, mode: Mode = SERVICE, mem_limit_mb: float | None = None,
                 poll_interval: float = 1.0) -> None:
        """`mem_limit_mb`: a job whose resident memory passes it is killed and fails `out_of_memory` (None: no guard)."""
        self.mem_limit_mb = mem_limit_mb
        self.poll_interval = poll_interval
        self.mode = mode
        self.store: RunStore = store
        self.jobs: dict[str, Job] = {}
        self._queue: collections.deque[Job] = collections.deque()
        self._running: Job | None = None
        self._cv = threading.Condition()
        threading.Thread(target=self._work, daemon=True).start()

    # --- submit, look up, stop ------------------------------------------------------------------------

    def start(
        self,
        engine: str,
        lot: dict[str, Any] | None,
        seed: int = DEFAULT_SEED,
        time_limit: float = SERVICE_TIME_LIMIT,
        delta: float = DEFAULT_DELTA,
        alpha: float = DEFAULT_ALPHA,
        orient: bool = False,
        owner: int | None = None,
        from_job: str | None = None,
        lot_id: int | None = None,
        mode: str | None = None,
    ) -> Job:
        """Check a request and queue its job; BadRequest, LotNotFound or QueueFull when it cannot run. `from_job`:
        continue from that earlier run of `owner`; its lot (costs included), δ, α and
        orient flag are taken from the saved run, `lot`, `delta`, `alpha` and `orient` of the request are ignored."""
        start = None
        if from_job is not None:
            if not self.mode.restart:
                raise BadRequest("chế độ này không giải lại từ lần chạy trước")
            saved = self.store.settings_dict(owner, from_job)
            lot, delta, alpha = self.store.lot_dict(owner, from_job), saved.get("delta"), saved.get("alpha")
            orient = bool(saved.get("orient"))
            start = solution_from_dict(self.store.solution_dict(owner, from_job))
            if not isinstance(delta, (int, float)) or not isinstance(alpha, (int, float)):
                raise BadRequest("lần chạy trước không ghi δ, α")
        elif lot is None:
            raise BadRequest("thiếu lô")
        if not time_limit > 0 or delta < 0 or not 0 <= alpha <= 1:
            raise BadRequest("giới hạn thời gian phải > 0, δ >= 0, 0 <= α <= 1")
        low, high = self.mode.time_range
        if not low <= time_limit <= high:
            raise BadRequest(f"giới hạn thời gian phải trong [{low:g}, {high:g}] s")
        pair = FILL_ENGINES if mode == "b" else self.mode.orient_engines
        engine = pair[1 if orient else 0]  # the mode and the flag pick the engine; `engine` is ignored
        check_engine(engine, self.mode)
        if from_job is not None and not base.accepts_start(engine):
            raise BadRequest(f"engine {engine!r} không giải tiếp từ phương án có sẵn")
        seed = self.mode.seed
        if not isinstance(lot, dict):
            raise BadRequest("lô phải là JSON")
        instance = instance_from_dict(lot) if from_job is not None else lot_from_client(lot)
        job = Job(uuid.uuid4().hex[:12], engine, CLIENT_PREFIX + instance.name, seed, time_limit, delta, alpha,
                  instance, orient=orient, owner=owner, from_job=from_job, start=start, lot_id=lot_id, mode=mode)
        with self._cv:
            if len(self._queue) >= QUEUE_SIZE:
                raise QueueFull(f"hàng đợi đầy ({QUEUE_SIZE} lần chạy đang chờ); thử lại sau")
            self.jobs[job.id] = job
            self._queue.append(job)
            self._cv.notify()
        return job

    def get(self, job_id: str, owner: int | None = None) -> Job:
        """The job, if it is `owner`'s: another user's job answers like a missing one."""
        job = self.jobs.get(job_id)
        if job is None or job.owner != owner:
            raise LotNotFound(f"không có lần chạy {job_id!r}")
        return job

    def position(self, job: Job) -> int | None:
        with self._cv:
            if job is self._running:
                return 0
            for n, waiting in enumerate(self._queue, 1):
                if waiting is job:
                    return n
        return None

    def state(self, job_id: str, owner: int | None = None) -> dict[str, Any]:
        job = self.get(job_id, owner)
        return job.state(self.position(job))

    def stop(self, job_id: str, owner: int | None = None) -> Job:
        """A waiting job leaves the queue; a running one is killed. Either way it ends `stopped`, unsaved."""
        job = self.get(job_id, owner)
        with self._cv:
            if job.status == "queued":
                self._queue.remove(job)
                job.status, job.finished = "stopped", time.monotonic()
                self._prune()
            elif job.status == "running":
                job.status = "stopped"
                if job.proc is not None and job.proc.is_alive():
                    job.proc.terminate()
        return job

    def lot_dict(self, job_id: str, owner: int | None = None) -> dict[str, Any]:
        instance = self.get(job_id, owner).instance
        if instance is None:
            raise LotNotFound(f"lần chạy {job_id!r} không có lô")
        return instance_to_dict(instance)

    def solution_dict(self, job_id: str, owner: int | None = None) -> dict[str, Any]:
        job = self.get(job_id, owner)
        if job.solution is None:
            raise LotNotFound(f"lần chạy {job.status}, không có lời giải")
        return solution_to_dict(job.solution)

    # --- worker ---------------------------------------------------------------------------------------

    def _work(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                job = self._queue.popleft()
                self._running = job
                job.status, job.started = "running", time.monotonic()
            try:
                self._run(job)
            finally:
                with self._cv:
                    self._running = None
                    self._prune()

    def _run(self, job: Job) -> None:
        instance = job.instance
        assert instance is not None
        space: RunSpace | None = None
        result: RunResult | None = None
        view: dict[str, Any] | None = None
        outcome = Outcome("failed", "engine_error")
        try:
            space = self.store.begin(job, self._settings(job))
            job.saved = space.run_id
            params = Params(delta=job.delta, alpha=job.alpha)
            sol_path, err_path, diag_path = engine_files(space.dir, instance.name, job.seed)
            start = time.monotonic()
            job.proc = spawn_one(base.get(job.engine), instance, params, job.time_limit, job.seed,
                                 sol_path, err_path, diag_path, job.start)
            if job.status == "stopped":  # stopped between the queue and the spawn
                job.proc.terminate()
            elapsed, killed, oom_mb = self._wait(job, job.proc, start)
            if job.status == "stopped":
                return
            checked, excess = instance, []
            if fill.META_KEY in instance.meta and sol_path.exists():  # mode B: the lot of the pieces it places
                placed = read_solution(sol_path)
                checked, excess = fill.placed_instance(instance, placed), fill.fleet_excess(instance, placed)
            result = collect_result(instance.name, job.seed, checked, params, elapsed, killed or oom_mb is not None,
                                    sol_path, err_path, diag_path)
            if oom_mb is not None:
                outcome = Outcome("failed", "out_of_memory", self._oom_message(oom_mb))
                return
            if result.error is not None:
                outcome = Outcome("failed", "timeout" if killed else "engine_error", result.error)
                return
            job.solution = read_solution(sol_path)
            if not result.valid:  # never handed out as a result: the checker decides
                outcome = Outcome("failed", "invalid_solution", f"lời giải không qua bộ kiểm tra độc lập ({result.violations} vi phạm)")
                return
            if excess:
                outcome = Outcome("failed", "invalid_solution", f"dùng nhiều container hơn số có sẵn: {', '.join(excess)}")
                return
            view = build_view(instance, job.solution, self._run_info(job, result), params)
            outcome = Outcome("done")
        except Exception as exc:  # noqa: BLE001 - any failure is reported to the page, not lost in the thread
            outcome, view = Outcome("failed", "engine_error", f"{type(exc).__name__}: {exc}"), None
        finally:
            stopped = job.status == "stopped"
            outcome, view = self._keep(job, space, result, outcome, view, stopped)
            job.view, job.finished = view, time.monotonic()
            if not stopped:  # the status is the last thing set: a poller that sees it finds the run kept
                job.status, job.code, job.error = outcome.status, outcome.code, outcome.error

    def _wait(self, job: Job, proc: Any, start: float) -> tuple[float, bool, float | None]:
        """Waits for the job process; ends on the first of: it exits; the hard time limit (killed); its resident memory
        above `mem_limit_mb`, polled every `poll_interval` s (killed, third value = the MB seen); a stop by hand (`stop`
        already terminated it). Returns (elapsed, killed by time, MB seen when killed for memory else None)."""
        deadline = start + HARD_KILL_FACTOR * job.time_limit
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            proc.join(min(self.poll_interval, remaining) if self.mem_limit_mb is not None else remaining)
            if not proc.is_alive():
                return time.monotonic() - start, False, None
            if job.status == "stopped":
                proc.terminate()
                proc.join()
                return time.monotonic() - start, False, None
            if time.monotonic() >= deadline:
                proc.terminate()
                proc.join()
                return time.monotonic() - start, True, None
            if self.mem_limit_mb is not None and proc.pid is not None:
                used = rss_mb(proc.pid)
                if used is not None and used > self.mem_limit_mb:
                    proc.terminate()
                    proc.join()
                    return time.monotonic() - start, False, used

    def _oom_message(self, used_mb: float) -> str:
        return (f"tiến trình giải dùng {used_mb:,.0f} MB, vượt ngưỡng {self.mem_limit_mb:,.0f} MB nên bị dừng; "
                "bộ nhớ tăng theo thời gian giải, thử giới hạn thời gian ngắn hơn")

    def _keep(self, job: Job, space: RunSpace | None, result: RunResult | None, outcome: Outcome,
              view: dict[str, Any] | None, stopped: bool) -> tuple[Outcome, dict[str, Any] | None]:
        """Hand the run to the store, or drop it when the job was stopped by hand (unlike a hard kill, which the
        runner counts as no solution). A store that cannot keep the run turns the job `failed`."""
        if space is None:
            return outcome, view
        try:
            if stopped:
                self.store.discard(job, space)
                job.saved = None
            else:
                self.store.finish(job, space, result, outcome)
        except Exception as exc:  # noqa: BLE001 - the page is told, the thread goes on
            return Outcome("failed", "engine_error", f"không lưu được lần chạy: {type(exc).__name__}: {exc}"), None
        return outcome, view

    def _prune(self) -> None:
        """Forget the oldest finished jobs beyond `KEEP_FINISHED` (caller holds the lock)."""
        finished = [j for j in self.jobs.values() if j.status in ("done", "stopped", "failed")]
        for job in sorted(finished, key=lambda j: j.created)[:max(0, len(finished) - KEEP_FINISHED)]:
            del self.jobs[job.id]

    def _settings(self, job: Job) -> dict[str, Any]:
        settings = {
            "source": "web",
            "job_id": job.id,  # reopening a saved run is by this id, not by the guessable run dir name
            "lot": job.lot,
            **run_settings(job.engine, job.alpha, job.delta, job.instance.container_types if job.instance else (),
                           job.time_limit, [job.seed]),
            "orient": job.orient,
        }
        if job.from_job is not None:
            settings["from_job"] = job.from_job
        return settings

    def _run_info(self, job: Job, result: RunResult) -> dict[str, Any]:
        return {
            "engine": job.engine,
            "seed": job.seed,
            "time": round(result.time, 2),
            "time_limit": job.time_limit,
            "delta": job.delta,
            "alpha": job.alpha,
            "cost_table": [{"id": t.id, "cost": t.cost} for t in job.instance.container_types] if job.instance else [],
            "orient": job.orient,
            "diagnostics": trim_diagnostics(result.diagnostics),
            "source": self.store.source(job),
        }
