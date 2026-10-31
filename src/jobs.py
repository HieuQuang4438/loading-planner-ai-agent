"""One engine job in its own process, hard-killed at `HARD_KILL_FACTOR * time_limit`, and the
checked result, as the web runs it (`src.web.job_manager`). `run_settings` gives the settings
every run keeps."""
from __future__ import annotations

import multiprocessing as mp
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.checker import check
from src.engines import base
from src.formats import read_json, read_solution, write_json, write_solution
from src.model import ContainerType, Instance, Params, Solution

HARD_KILL_FACTOR = 1.5
PEAK_RSS_KEY = "peak_rss_mb"  # carried from the child in the diagnostics file, then lifted onto RunResult

# --- data --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    instance: str
    seed: int
    cost: float | None
    time: float
    valid: bool
    violations: int | None
    error: str | None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    peak_rss_mb: float | None = None  # the job process's peak resident memory; None on Windows or when killed


def result_to_dict(r: RunResult) -> dict[str, Any]:
    return asdict(r)


def result_from_dict(d: dict[str, Any]) -> RunResult:
    return RunResult(**d)


def peak_rss_mb() -> float | None:
    """This process's peak resident set size in MB (`resource.getrusage`), or None where the
    `resource` module does not exist (Windows)."""
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1024**2 if sys.platform == "darwin" else rss / 1024  # bytes on macOS, KB on Linux


# --- running -------------------------------------------------------------------------------------


def _spawn_target(
    engine: base.Engine,
    instance: Instance,
    params: Params,
    time_limit: float,
    seed: int,
    sol_path: Path,
    err_path: Path,
    diag_path: Path,
    start: Solution | None = None,
) -> None:
    """Runs in the child process. Any solver failure is written to `err_path`, not raised, so the
    parent can record it as an invalid run instead of crashing the whole batch."""
    try:
        if start is None:
            solution, diagnostics = engine(instance, params, time_limit, seed)
        else:  # only an engine registered with start=True is handed one
            solution, diagnostics = engine(instance, params, time_limit, seed, start=start)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any engine failure is data, not a crash
        err_path.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return
    write_solution(sol_path, solution)
    peak = peak_rss_mb()
    if peak is not None:
        diagnostics = {**diagnostics, PEAK_RSS_KEY: round(peak, 1)}
    if diagnostics:
        write_json(diag_path, diagnostics)


def spawn_one(
    engine: base.Engine,
    instance: Instance,
    params: Params,
    time_limit: float,
    seed: int,
    sol_path: Path,
    err_path: Path,
    diag_path: Path,
    start: Solution | None = None,
) -> mp.Process:
    """Starts `engine.solve` for one (instance, seed) in its own process; the caller joins or kills it. `start`:
    an earlier solution to continue from, for an engine that takes one."""
    ctx = mp.get_context("spawn")
    proc = ctx.Process(
        target=_spawn_target, args=(engine, instance, params, time_limit, seed, sol_path, err_path, diag_path, start)
    )
    proc.start()
    return proc


def join_one(proc: mp.Process, time_limit: float, start: float) -> tuple[float, bool]:
    """Waits for `proc` up to `HARD_KILL_FACTOR * time_limit` after `start` (a `time.monotonic()`
    reading), then kills it. Returns (elapsed seconds, killed)."""
    proc.join(max(0.0, start + HARD_KILL_FACTOR * time_limit - time.monotonic()))
    killed = proc.is_alive()
    if killed:
        proc.terminate()
        proc.join()
    return time.monotonic() - start, killed


def run_one(
    engine: base.Engine,
    instance: Instance,
    params: Params,
    time_limit: float,
    seed: int,
    sol_path: Path,
    err_path: Path,
    diag_path: Path,
) -> tuple[float, bool]:
    """Runs `engine.solve` for one (instance, seed) in its own process. Returns (elapsed seconds,
    killed). Hard kill at `HARD_KILL_FACTOR * time_limit`, whatever the engine is doing."""
    start = time.monotonic()
    proc = spawn_one(engine, instance, params, time_limit, seed, sol_path, err_path, diag_path)
    return join_one(proc, time_limit, start)


def collect_result(
    name: str,
    seed: int,
    instance: Instance,
    params: Params,
    elapsed: float,
    killed: bool,
    sol_path: Path,
    err_path: Path,
    diag_path: Path,
) -> RunResult:
    """Turns what a finished (or killed) job left on disk into a checked `RunResult`."""
    if killed:
        return RunResult(name, seed, None, elapsed, False, None, f"killed after {elapsed:.1f} s (no solution)")
    if err_path.exists():
        return RunResult(name, seed, None, elapsed, False, None, err_path.read_text(encoding="utf-8"))
    if not sol_path.exists():
        return RunResult(name, seed, None, elapsed, False, None, "engine returned no solution")
    solution = read_solution(sol_path)
    result = check(instance, solution, params)
    diagnostics = read_json(diag_path) if diag_path.exists() else {}
    peak = diagnostics.pop(PEAK_RSS_KEY, None)
    return RunResult(name, seed, result.cost, elapsed, result.ok, len(result.violations), None, diagnostics, peak)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - a missing git binary or non-repo checkout must not break a run
        try:  # a code archive without .git carries a COMMIT file
            return (Path(__file__).resolve().parents[1] / "COMMIT").read_text().strip() or None
        except OSError:
            return None


def run_settings(engine: str, alpha: float, delta: float, container_types: tuple[ContainerType, ...],
                 time_limit: float, seeds: list[int]) -> dict[str, Any]:
    """The settings every run keeps. The container table, costs included, comes with the lot (docs/product/ux.md §5):
    there is no named cost table on the server."""
    settings: dict[str, Any] = {
        "engine": engine,
        "alpha": alpha,
        "delta": delta,
        "cost_table": [asdict(t) for t in container_types],
        "time_limit": time_limit,
        "hard_kill_factor": HARD_KILL_FACTOR,
        "seeds": seeds,
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "git_commit": _git_commit(),
    }
    if engine.startswith("e5"):
        from ortools import __version__ as ortools_version

        settings["threads_per_job"] = 1  # every E5 solver (GLOP, SCIP, CP-SAT) runs on one thread
        settings["ortools_version"] = ortools_version
    return settings
