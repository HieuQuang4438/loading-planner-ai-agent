"""Engines that fail on purpose, for the web's job and error tests. Module-level functions, so a `spawn`
child process can import them."""
from __future__ import annotations

import time
from typing import Any

from src.model import Instance, Params, Placement, Solution, UsedContainer


def sleeper(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """Never returns in time: the runner hard-kills it."""
    time.sleep(3600)
    raise AssertionError("unreachable")


def hog(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """Grows its memory by 20 MB every 0.1 s up to 400 MB (touching every page), then sleeps: the memory guard kills it."""
    held = []
    for _ in range(20):
        held.append(bytearray(b"\x01") * (20 * 1024 * 1024))
        time.sleep(0.1)
    time.sleep(3600)
    raise AssertionError("unreachable")


def crasher(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    raise RuntimeError("boom")


def stacker(instance: Instance, params: Params, time_limit: float, seed: int) -> tuple[Solution, dict[str, Any]]:
    """Every item at the same corner of one container: overlaps, so the checker rejects it."""
    placements = [Placement(item, 1, 0.0, 0.0, 0.0, "LWH") for line in instance.items for item in line.item_ids()]
    return Solution(instance.name, params, [UsedContainer(1, instance.container_types[0].id)], placements), {}


def restartable(instance: Instance, params: Params, time_limit: float, seed: int,
                start: Solution | None = None) -> tuple[Solution, dict[str, Any]]:
    """Takes a `start`: hands it back as it is, and says in the diagnostics whether it got one and under which
    δ and α. Without one it packs like E1."""
    from src.engines import e1

    if start is None:
        solution, _ = e1.solve(instance, params, time_limit, seed)
        return solution, {"got_start": False}
    return start, {"got_start": True, "delta": params.delta, "alpha": params.alpha, "lot": instance.name}
