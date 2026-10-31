"""E4's ALNS loop (Ropke and Pisinger 2006,
options 5A, 6A).

Each iteration picks one destroy and one repair operator by roulette over adaptive weights, applies
them to a copy of the current solution, and accepts the result by simulated annealing on the scalar
objective (`state.scalar`: cost plus a small weight times the emptiest container's fill).

- **Temperature**: T0 such that a solution `start_temperature` x f(initial) worse is accepted with
  probability 0.5; cooled geometrically to `end_temperature` x T0 over the run, by elapsed share of
  the time budget (or of `max_iterations`, when set).
- **Weights**: every `segment` iterations, w <- (1 - r) w + r * (score sum / uses) for each operator
  used in the segment; scores `scores` = (new best, better than current, accepted and new), and
  nothing for a solution accepted before (hash of its (type, item set) pairs).
- **Acceptance** (`Settings.acceptance`): "anneal" as above; "flat": the same test at a
  fixed `flat_temperature` x T0; "lahc": late acceptance (Burke and Bykov 2017) -- accept when no worse
  than the current objective or than the current objective `lahc_length` iterations ago. "flat" and
  "lahc" never look at the clock, so iteration k is the same whatever the budget.
- **Stop**: time budget spent, `max_iterations` reached, or the best cost equals the instance's
  lower bound (`src.bound` cost comment) -- nothing cheaper exists; or, when `Settings.stall_min`
  is set, a stall: more iterations since the last improvement than max(stall_min, stall_ratio x
  the iteration of the last improvement). Iteration counts only, so a stall is the same on every run of a seed.

An iteration cut short by the deadline (`Deadline`, raised before a core call) is dropped whole.
`Search` keeps the run's state so a caller can advance it again later; `run` is one advance.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from src.engines.e4.operators import DESTROYS, REPAIRS, Context, Work
from src.engines.e4.packer import Deadline
from src.engines.e4.state import Box, cost, key, scalar, signature

EPS = 1e-6  # cost tolerance, matches src.checker.EPS
ACCEPTANCES = ("anneal", "flat", "lahc")


@dataclass
class _Roulette:
    names: list[str]
    weights: list[float] = field(default_factory=list)
    uses: list[int] = field(default_factory=list)
    total_uses: list[int] = field(default_factory=list)
    score: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.names)
        self.weights, self.uses, self.total_uses, self.score = [1.0] * n, [0] * n, [0] * n, [0.0] * n

    def pick(self, rng) -> int:
        i = rng.choices(range(len(self.names)), weights=self.weights)[0]
        self.uses[i] += 1
        self.total_uses[i] += 1
        return i

    def unpick(self, i: int) -> None:
        """Undo `pick` for an iteration dropped by the deadline."""
        self.uses[i] -= 1
        self.total_uses[i] -= 1

    def reward(self, i: int, score: float) -> None:
        self.score[i] += score

    def update(self, reaction: float) -> None:
        for i, used in enumerate(self.uses):
            if used:
                self.weights[i] = (1 - reaction) * self.weights[i] + reaction * self.score[i] / used
                self.weights[i] = max(self.weights[i], 1e-3)  # never drop an operator for good
        self.uses = [0] * len(self.names)
        self.score = [0.0] * len(self.names)

    def report(self) -> dict[str, Any]:
        return {n: {"weight": round(w, 3), "uses": u} for n, w, u in zip(self.names, self.weights, self.total_uses)}


@dataclass
class Outcome:
    best: list[Box]
    iterations: int
    improvements: int
    accepted: int
    best_time: float  # seconds from the search's start to the last new best
    stop: str  # "time", "iterations", "bound", "stall"
    destroy: dict[str, Any]
    repair: dict[str, Any]
    improvement_iterations: list[int] = field(default_factory=list)  # 1-based, first IMPROVEMENT_CAP of them
    last_improvement_iteration: int = 0  # 0: the initial solution is still the best
    last_improvement_time: float | None = None  # time.monotonic() of the last new best; None if none


IMPROVEMENT_CAP = 1000  # entries kept in `improvement_iterations` (the last one is always in `last_improvement_*`)


def run(initial: list[Box], ctx: Context, bound: float, deadline: float) -> Outcome:
    return Search(initial, ctx, bound).advance(deadline)


class Search:
    """One ALNS run's state, advanced until a deadline and resumable after it (E5 goes back to
    the search when its master leaves time). An iteration cut short by the deadline is dropped whole and
    the random stream and operator picks it used are rolled back, so with a clock-free acceptance
    ("flat", "lahc") advancing to t1 and then to t2 runs the same iterations as advancing to t2 once."""

    def __init__(self, initial: list[Box], ctx: Context, bound: float) -> None:
        s = ctx.settings
        if s.acceptance not in ACCEPTANCES:
            raise ValueError(f"unknown acceptance {s.acceptance!r}; expected one of {ACCEPTANCES}")
        self.ctx = ctx
        self.bound = bound
        self.start: float | None = None  # set by the first advance: the anneal schedule spans that budget
        self.budget = 1e-9
        self.current, self.best = initial, initial
        self.f_cur = scalar(initial)
        self.t0 = s.start_temperature * self.f_cur / math.log(2) if self.f_cur > 0 else 0.0
        self.history = [self.f_cur] * s.lahc_length
        self.destroy, self.repair = _Roulette(list(DESTROYS)), _Roulette(list(REPAIRS))
        self.visited = {signature(initial)}
        self.iterations = self.improvements = self.accepted = 0
        self.best_time = 0.0
        self.improvement_iterations: list[int] = []
        self.last_improvement_iteration = 0
        self.last_improvement_time: float | None = None
        self.stop = "time"

    def stalled(self, stall_min: int, stall_ratio: float) -> bool:
        """more iterations since the last improvement than max(stall_min, stall_ratio x its index)."""
        last = self.last_improvement_iteration
        return self.iterations - last > max(stall_min, stall_ratio * last)

    def outcome(self) -> Outcome:
        return Outcome(self.best, self.iterations, self.improvements, self.accepted, self.best_time, self.stop,
                       self.destroy.report(), self.repair.report(), list(self.improvement_iterations),
                       self.last_improvement_iteration, self.last_improvement_time)

    def advance(self, deadline: float) -> Outcome:
        s, rng, ctx = self.ctx.settings, self.ctx.rng, self.ctx
        if self.start is None:
            self.start = time.monotonic()
            self.budget = max(deadline - self.start, 1e-9)
        destroy, repair = self.destroy, self.repair
        self.stop = "time"
        while True:
            if cost(self.best) <= self.bound + EPS:
                self.stop = "bound"
                break
            if s.max_iterations is not None and self.iterations >= s.max_iterations:
                self.stop = "iterations"
                break
            if s.stall_min is not None and self.stalled(s.stall_min, s.stall_ratio):
                self.stop = "stall"
                break
            now = time.monotonic()
            if now >= deadline:
                break
            if s.acceptance == "flat":
                temperature = self.t0 * s.flat_temperature
            else:
                progress = (self.iterations / s.max_iterations if s.max_iterations
                            else (now - self.start) / self.budget)
                temperature = self.t0 * s.end_temperature ** min(progress, 1.0)

            state = rng.getstate()
            d, r = destroy.pick(rng), repair.pick(rng)
            work = Work(boxes=[b.copy() for b in self.current], pool=[])
            try:
                DESTROYS[destroy.names[d]](work, ctx)
                REPAIRS[repair.names[r]](work, ctx)
            except Deadline:
                rng.setstate(state)
                destroy.unpick(d)
                repair.unpick(r)
                break
            candidate = work.boxes
            self.iterations += 1
            f_cur, f_new = self.f_cur, scalar(candidate)
            sig = signature(candidate)
            score = 0.0
            if key(candidate) < key(self.best):
                self.best, score = candidate, s.scores[0]
                self.improvements += 1
                self.best_time = time.monotonic() - self.start
                self.last_improvement_iteration = self.iterations
                self.last_improvement_time = time.monotonic()
                if len(self.improvement_iterations) < IMPROVEMENT_CAP:
                    self.improvement_iterations.append(self.iterations)
            elif f_new < f_cur - 1e-12 and sig not in self.visited:
                score = s.scores[1]
            if s.acceptance == "lahc":
                slot = (self.iterations - 1) % s.lahc_length
                take = f_new <= f_cur or f_new <= self.history[slot]
            else:
                take = f_new <= f_cur or (temperature > 0 and rng.random() < math.exp(-(f_new - f_cur) / temperature))
            if take:
                if score == 0.0 and sig not in self.visited:
                    score = s.scores[2]
                self.current, self.f_cur = candidate, f_new
                self.visited.add(sig)
                self.accepted += 1
            if s.acceptance == "lahc":
                self.history[slot] = self.f_cur
            destroy.reward(d, score)
            repair.reward(r, score)
            if self.iterations % s.segment == 0:
                destroy.update(s.reaction)
                repair.update(s.reaction)
        return self.outcome()
