"""Where a finished job's run is kept. `JobManager` talks to a `RunStore` only; `SqliteStore` keeps the run as one row
of the `runs` table of `app.db`, owned by the user who ran it.

The engine always writes its files into a directory the store hands out (`begin`); `finish` keeps the run,
`discard` drops it (a job stopped by hand is not a result)."""
from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from src.formats import instance_from_dict, instance_to_dict, solution_from_dict, solution_to_dict
from src.jobs import PEAK_RSS_KEY, RunResult, result_to_dict
from src.web.db import connect, migrate
from src.web.errors import LotNotFound
from src.web.view import build_view, trim_diagnostics

if TYPE_CHECKING:
    from src.model import Instance, Params
    from src.web.job_manager import Job

CLIENT_PREFIX = "client:"  # `lot` label in settings.json for a lot the client sent
KEEP_DAYS = 30
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"  # fixed-width UTC text, so that string order is time order in SQL (as in `auth`)


@dataclass
class RunSpace:
    """What `begin` hands to the job: the directory the engine writes into, the settings of the run, the run id."""

    dir: Path
    settings: dict[str, Any]
    run_id: str | None = None  # the run dir name under `runs_dir`; None for a store that has no such name


@dataclass(frozen=True)
class Outcome:
    """How a job ended, as `finish` records it."""

    status: str  # done | failed
    code: str | None = None  # timeout | out_of_memory | engine_error | invalid_solution
    error: str | None = None


def engine_files(directory: Path, name: str, seed: int) -> tuple[Path, Path, Path]:
    """(solution, error, diagnostics) files of one job inside `directory`, as the batch runner names them."""
    stem = directory / "solutions" / f"{name}-s{seed}"
    return (stem.with_name(stem.name + ".json"), stem.with_name(stem.name + ".error.txt"),
            stem.with_name(stem.name + ".diag.json"))


class RunStore(Protocol):
    """Writing (the worker) and reading back (the routes). `owner` is the user id with login on, else None; a store
    that has no users ignores it."""

    def begin(self, job: Job, settings: dict[str, Any]) -> RunSpace: ...

    def finish(self, job: Job, space: RunSpace, result: RunResult | None, outcome: Outcome) -> None: ...

    def discard(self, job: Job, space: RunSpace) -> None: ...

    def source(self, job: Job) -> str: ...

    def view(self, owner: int | None, job_id: str) -> dict[str, Any]: ...

    def lot_dict(self, owner: int | None, job_id: str) -> dict[str, Any]: ...

    def solution_dict(self, owner: int | None, job_id: str) -> dict[str, Any]: ...

    def settings_dict(self, owner: int | None, job_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RunSummary:
    job_id: str
    lot_name: str
    created_at: str
    status: str
    code: str | None
    cost: float | None
    lot_id: int | None = None
    mode: str | None = None
    containers: list[str] = field(default_factory=list)  # the types used, one entry per container
    placed: int | None = None  # pieces in the plan; None without one
    total: int | None = None  # pieces of the lot the run was given (mode B: the whole lot, placed or not)


@dataclass
class SqliteStore:
    """Runs as rows of `runs` in `app.db`, each owned by a user: every query has the owner's `user_id`, so another
    user's run and a missing one are the same `LotNotFound`. The engine writes into a temp directory that is removed
    whatever happens; the worker reads it into one row in one transaction. Runs older than `keep_days` are purged
    when the store is made and after each write."""

    db_path: str | Path
    keep_days: int = KEEP_DAYS
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        with closing(connect(self.db_path)) as conn:
            migrate(conn)
            self._purge(conn)

    # ---- write ------------------------------------------------------------------------------------------------
    def begin(self, job: Job, settings: dict[str, Any]) -> RunSpace:
        work = Path(tempfile.mkdtemp(prefix=f"planner-{job.id}-"))
        (work / "solutions").mkdir()
        return RunSpace(work, settings)

    def finish(self, job: Job, space: RunSpace, result: RunResult | None, outcome: Outcome) -> None:
        """One row from what the job left in `space.dir`; the directory is removed even when this fails."""
        try:
            assert job.instance is not None
            name = job.instance.name
            sol_path, _, diag_path = engine_files(space.dir, name, job.seed)
            if result is None:  # the job died before it was judged: the row says why
                result = RunResult(name, job.seed, None, job.elapsed(), False, None, outcome.error)
            row = (
                job.id, job.owner, self._stamp(self.now()), name, outcome.status, outcome.code,
                result.cost if result.valid else None,
                json.dumps(space.settings, ensure_ascii=False),
                json.dumps(instance_to_dict(job.instance), ensure_ascii=False),
                json.dumps(result_to_dict(result), ensure_ascii=False),
                sol_path.read_text(encoding="utf-8") if sol_path.is_file() else None,
                diag_path.read_text(encoding="utf-8") if diag_path.is_file() else None,
                job.lot_id, job.mode,
            )
            with closing(connect(self.db_path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        "INSERT INTO runs (job_id, user_id, created_at, lot_name, status, code, cost, settings, lot,"
                        " result, solution, diag, lot_id, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                self._purge(conn)
        finally:
            shutil.rmtree(space.dir, ignore_errors=True)

    def discard(self, job: Job, space: RunSpace) -> None:
        shutil.rmtree(space.dir, ignore_errors=True)

    def source(self, job: Job) -> str:
        return "chạy vừa xong, lưu trong tài khoản"

    def _purge(self, conn: Any) -> None:
        conn.execute("DELETE FROM runs WHERE created_at < ?", (self._stamp(self.now() - timedelta(days=self.keep_days)),))

    @staticmethod
    def _stamp(t: datetime) -> str:
        return t.strftime(_STAMP)

    # ---- read -------------------------------------------------------------------------------------------------
    def list_runs(self, owner: int, lot_ids: list[int] | None = None) -> list[RunSummary]:
        """The owner's runs, newest first; only those of `lot_ids` when given."""
        query = ("SELECT job_id, lot_name, created_at, status, code, cost, lot_id, mode, solution, lot FROM runs"
                 " WHERE user_id = ?")
        args: list[Any] = [owner]
        if lot_ids is not None:
            query += f" AND lot_id IN ({', '.join('?' * len(lot_ids))})"
            args += lot_ids
        with closing(connect(self.db_path)) as conn:
            rows = conn.execute(query + " ORDER BY created_at DESC", args).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            raw = row.pop("solution")
            solution = json.loads(raw) if raw else None
            lot = json.loads(row.pop("lot"))
            types = [c["type"] for c in solution["containers"]] if solution else []
            out.append(RunSummary(**row, containers=types, placed=len(solution["placements"]) if solution else None,
                                  total=sum(item["qty"] for item in lot["items"])))
        return out

    def delete(self, owner: int, job_id: str) -> None:
        with closing(connect(self.db_path)) as conn:
            if conn.execute("DELETE FROM runs WHERE job_id = ? AND user_id = ?", (job_id, owner)).rowcount == 0:
                raise self._missing(job_id)

    def _row(self, owner: int | None, job_id: str) -> dict[str, Any]:
        """A run that can be handed out: the owner's, and `done` (an `invalid_solution` row is kept, never served)."""
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT settings, lot, result, solution, diag, lot_id FROM runs"
                " WHERE job_id = ? AND user_id = ? AND status = 'done'", (job_id, owner)).fetchone()
        if row is None or row["solution"] is None:
            raise self._missing(job_id)
        return dict(row)

    @staticmethod
    def _missing(job_id: str) -> LotNotFound:
        return LotNotFound(f"không có lần chạy đã lưu {job_id!r}")

    def view(self, owner: int | None, job_id: str) -> dict[str, Any]:
        row = self._row(owner, job_id)
        settings, result = json.loads(row["settings"]), json.loads(row["result"])
        instance, solution = instance_from_dict(json.loads(row["lot"])), solution_from_dict(json.loads(row["solution"]))
        diagnostics = json.loads(row["diag"]) if row["diag"] else {}
        diagnostics.pop(PEAK_RSS_KEY, None)  # the live view has it lifted onto the result, not among the diagnostics
        info = {
            "engine": settings.get("engine"),
            "seed": int(result["seed"]),
            "time": round(result["time"], 2),
            "time_limit": settings.get("time_limit"),
            "delta": solution.params.delta,
            "alpha": solution.params.alpha,
            "cost_table": [{"id": t["id"], "cost": t["cost"]} for t in settings.get("cost_table", [])],  # as the live view
            "orient": settings.get("orient"),
            "diagnostics": trim_diagnostics(diagnostics),
            "source": "mở lại từ tài khoản",
        }
        return build_view(instance, solution, info)

    def lot_dict(self, owner: int | None, job_id: str) -> dict[str, Any]:
        return instance_to_dict(instance_from_dict(json.loads(self._row(owner, job_id)["lot"])))

    def solution_dict(self, owner: int | None, job_id: str) -> dict[str, Any]:
        return solution_to_dict(solution_from_dict(json.loads(self._row(owner, job_id)["solution"])))

    def snapshot(self, owner: int | None, job_id: str) -> tuple[Instance, Params, int | None]:
        """The lot a run was packed for, its params and the product lot it is of (None: a lot sent as JSON)."""
        row = self._row(owner, job_id)
        return instance_from_dict(json.loads(row["lot"])), solution_from_dict(json.loads(row["solution"])).params, row["lot_id"]

    def settings_dict(self, owner: int | None, job_id: str) -> dict[str, Any]:
        return json.loads(self._row(owner, job_id)["settings"])

