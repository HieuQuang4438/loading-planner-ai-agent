"""Configuration of the web: the engines it runs and the limits of a job.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import src.engines  # noqa: F401 - side effect: registers the engines
from src.engines import base
from src.web.errors import BadRequest

DEFAULT_ENGINE = "e5"
SERVICE_TIME_LIMIT = 60.0  # the time limit before a lot is checked (no size known yet)
# Default time limit by lot size = containers of the lower-bound fleet (`bound.fleet`): (name, largest fleet that is
# still this size, seconds); `None`: no upper end. Measured on a 2-vCPU VM.
SERVICE_SIZE_LIMITS: tuple[tuple[str, int | None, float], ...] = (
    ("small", 4, 60.0), ("medium", 20, 60.0), ("large", None, 120.0))
DEFAULT_DELTA = 0.05
DEFAULT_ALPHA = 0.8
DEFAULT_SEED = 1
SERVICE_ENGINES = ("e5", "e5-orient")  # e5 by default, e5-orient when the user lets the engine tip items
FILL_ENGINES = ("e5-fill", "e5-fill-orient")  # mode B, the same pair (ADR-0002)

ENGINE_TITLES = {
    "e5": "E5 · set cover",
    "e5-orient": "E5 · set cover, mọi tư thế",
    "e5-fill": "E5-fill · tối đa hàng",
    "e5-fill-orient": "E5-fill · tối đa hàng, mọi tư thế",
}
ENGINE_DESCRIPTIONS = {
    "e5": "Set cover trên các container E1, E2, E4 xếp; tối thiểu tổng cước",
    "e5-orient": "E5 thêm lõi thử mọi tư thế cho phép",
    "e5-fill": "Container có sẵn; nhiều hàng nhất theo thứ tự ưu tiên",
    "e5-fill-orient": "E5-fill thêm lõi thử mọi tư thế cho phép",
}


@dataclass(frozen=True)
class Mode:
    name: str
    engines: tuple[str, ...]
    seed: int  # fixed seed
    time_range: tuple[float, float]  # allowed time limits (s)
    default_time_limit: float  # used when a request leaves the time limit out
    orient_engines: tuple[str, str]  # (flag off, flag on): the engine follows the request's `orient` flag
    size_limits: tuple[tuple[str, int | None, float], ...]  # default time limit by lot size
    restart: bool = True  # a request may start from an earlier run (`from_job`)


SERVICE = Mode("service", SERVICE_ENGINES + FILL_ENGINES, seed=DEFAULT_SEED, time_range=(10.0, 600.0),
               default_time_limit=SERVICE_TIME_LIMIT, orient_engines=SERVICE_ENGINES, size_limits=SERVICE_SIZE_LIMITS)


def default_time_limit(fleet_size: int, mode: Mode = SERVICE) -> float:
    """The time limit (s) a lot gets when the request leaves it out: by the number of containers of its lower-bound
    fleet."""
    for _, largest, seconds in mode.size_limits:
        if largest is None or fleet_size <= largest:
            return seconds
    return mode.default_time_limit


def engine_entries(mode: Mode = SERVICE) -> list[dict[str, Any]]:
    """The engines the web offers."""
    return [{
        "name": name,
        "available": True,
        "reason": None,
        "default": name == DEFAULT_ENGINE,
        "title": ENGINE_TITLES.get(name, name),
        "description": ENGINE_DESCRIPTIONS.get(name, ""),
    } for name in base.names() if name in mode.engines]


def check_engine(engine: str, mode: Mode = SERVICE) -> None:
    """BadRequest unless the mode offers `engine`."""
    engine = base.canonical(engine)
    if engine not in [e["name"] for e in engine_entries(mode)]:
        raise BadRequest(f"engine {engine!r} không có; có: {list(mode.engines)}")
