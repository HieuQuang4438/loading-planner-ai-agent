"""Memory guard of the web's engine jobs: the resident memory of a job process
(and of its descendants) read from `/proc`, and the threshold above which `JobManager` kills the job. Linux only, no
dependency: where `/proc` or a memory limit cannot be read (Windows) there is no guard."""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

ENV_VAR = "PLANNER_JOB_MEM_MB"
SHARE = 0.75  # default threshold: this share of the memory the app may use
PROC = Path("/proc")
MEMINFO = PROC / "meminfo"
CGROUP2_MAX = Path("/sys/fs/cgroup/memory.max")
CGROUP1_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


def mem_total_mb(meminfo: Path = MEMINFO) -> float | None:
    """`MemTotal` of `/proc/meminfo` in MB, or None."""
    match = re.search(r"^MemTotal:\s+(\d+)\s*kB", _read(meminfo) or "", re.MULTILINE)
    return int(match.group(1)) / 1024 if match else None


def memory_available_mb(meminfo: Path = MEMINFO, cgroup2: Path = CGROUP2_MAX, cgroup1: Path = CGROUP1_LIMIT) -> float | None:
    """The memory the app may use, in MB: the cgroup v2 limit if it is a number (`max` means none), else the cgroup v1
    limit if below `MemTotal` (v1 shows a huge number for none), else `MemTotal`; None if nothing is readable."""
    total = mem_total_mb(meminfo)
    text = (_read(cgroup2) or "").strip()
    if text.isdigit():
        return int(text) / 1024**2
    text = (_read(cgroup1) or "").strip()
    if text.isdigit() and (total is None or int(text) / 1024**2 < total):
        return int(text) / 1024**2
    return total


def default_limit_mb(meminfo: Path = MEMINFO, cgroup2: Path = CGROUP2_MAX, cgroup1: Path = CGROUP1_LIMIT) -> float | None:
    available = memory_available_mb(meminfo, cgroup2, cgroup1)
    return None if available is None else available * SHARE


def job_limit_mb(env: Mapping[str, str] = os.environ, meminfo: Path = MEMINFO, cgroup2: Path = CGROUP2_MAX,
                 cgroup1: Path = CGROUP1_LIMIT) -> float | None:
    """The threshold in MB, read once at app creation: `PLANNER_JOB_MEM_MB` if it is a positive number, else the default;
    None (no guard, one line logged) when neither exists."""
    raw = (env.get(ENV_VAR) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if value > 0:
            log.info("memory guard: a job is killed above %.0f MB (%s)", value, ENV_VAR)
            return value
        log.warning("%s=%r is not a positive number: using the default", ENV_VAR, raw)
    limit = default_limit_mb(meminfo, cgroup2, cgroup1)
    if limit is None:
        log.warning("memory guard is off: no memory limit readable (no /proc, e.g. Windows); set %s to turn it on", ENV_VAR)
    else:
        log.info("memory guard: a job is killed above %.0f MB (%.0f%% of the memory the app may use)", limit, SHARE * 100)
    return limit


def _children(pid: int, proc: Path) -> list[int]:
    kids: list[int] = []
    try:
        tasks = list((proc / str(pid) / "task").iterdir())
    except OSError:
        return kids
    for task in tasks:
        kids += [int(p) for p in (_read(task / "children") or "").split()]
    return kids


def rss_mb(pid: int, proc: Path = PROC) -> float | None:
    """Resident memory (`VmRSS`) of process `pid` plus all its descendants (an engine may start a helper process, e.g.
    E0's Java bridge), in MB; None if the process cannot be read (gone, or no `/proc`)."""
    total_kb, seen, todo = 0, set(), [pid]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        match = re.search(r"^VmRSS:\s+(\d+)\s*kB", _read(proc / str(current) / "status") or "", re.MULTILINE)
        if match:
            total_kb += int(match.group(1))
        elif current == pid:
            return None
        todo += _children(current, proc)
    return total_kb / 1024
