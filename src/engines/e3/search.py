"""E3's BRKGA loop (Goncalves and Resende 2011, options
3A, 4A, 5A).

- **Population**: p = clamp(round(`pop_factor` x chromosome length), `pop_min`, `pop_cap`). The first
  one is the seeded chromosome (`Decoder.seeded`, decoding near the core's own solution) plus p - 1
  random ones.
- **Generation**: sorted by the lexicographic objective (`state.key`), the best `elite` share is
  copied unchanged (not decoded again); a `mutant` share is new random chromosomes; the rest are
  children of one random elite and one random non-elite parent, taking each key from the elite one
  with probability `rho_e` (parameterised uniform crossover).
- **Partial restart**: after `restart_after` generations without a new best in the population, the
  next generation's non-elite part is all random (no children).
- **Stop**: time budget spent, `max_generations` reached (tests), or the best cost equals the
  instance's lower bound (`src.bound`) -- nothing cheaper exists. A decode cut short by the deadline
  (`Deadline`, raised before a core call) is dropped.

The best solution is the better of the incumbent (the plain E1/E2 solve) and every decode.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

from src.engines.e3.decoder import Decoder
from src.engines.e4.packer import Deadline
from src.engines.e4.state import Box, cost, key

EPS = 1e-6  # cost tolerance, matches src.checker.EPS


@dataclass(frozen=True)
class Settings:
    """Search parameters."""

    elite: float = 0.2  # share of the population kept unchanged
    mutant: float = 0.15  # share replaced by random chromosomes each generation
    rho_e: float = 0.7  # probability a child takes the elite parent's key
    pop_factor: float = 1.0  # population size per key of the chromosome ...
    pop_min: int = 20  # ... at least ...
    pop_cap: int = 100  # ... and at most this
    restart_after: int = 20  # generations without a new population best before a partial restart
    time_share: float = 0.95  # of time_limit: slack for process start-up and writing the solution
    max_generations: int | None = None  # for tests: stop by generation count, not time


def population_size(length: int, s: Settings) -> int:
    return max(s.pop_min, min(s.pop_cap, round(s.pop_factor * length)))


@dataclass
class Outcome:
    best: list[Box]
    population: int
    generations: int  # completed after the initial population
    decodes: int
    improvements: int  # new overall bests (over the incumbent)
    restarts: int
    best_time: float  # seconds from the search's start to the last new best
    stop: str  # "time", "generations", "bound"


class _Stop(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def run(
    decoder: Decoder,
    incumbent: list[Box],
    seed_types: list[str],
    settings: Settings,
    rng: random.Random,
    bound: float,
    deadline: float,
) -> Outcome:
    s = settings
    start = time.monotonic()
    p = population_size(decoder.length, s)
    n_elite = max(1, round(s.elite * p))
    n_mutant = max(1, round(s.mutant * p)) if p - n_elite > 1 else 0
    state = {"best": incumbent, "decodes": 0, "improvements": 0, "best_time": 0.0}

    def check_stop() -> None:
        if cost(state["best"]) <= bound + EPS:
            raise _Stop("bound")
        if time.monotonic() >= deadline:
            raise _Stop("time")

    def consider(boxes: list[Box]) -> tuple[float, float]:
        state["decodes"] += 1
        k = key(boxes)
        if k < key(state["best"]):
            state["best"] = boxes
            state["improvements"] += 1
            state["best_time"] = time.monotonic() - start
        return k

    def evaluate(chrom: list[float]) -> tuple[tuple[float, float], list[float]]:
        check_stop()
        try:
            boxes = decoder.decode(chrom)
        except Deadline:
            raise _Stop("time") from None
        return consider(boxes), chrom

    population: list[tuple[tuple[float, float], list[float]]] = []
    generations = restarts = stall = 0
    stop = "time"
    try:
        check_stop()
        try:
            chrom, boxes = decoder.seeded(seed_types, rng)
        except Deadline:
            raise _Stop("time") from None
        population.append((consider(boxes), chrom))
        while len(population) < p:
            population.append(evaluate(decoder.random(rng)))
        population.sort(key=lambda e: e[0])
        pop_best = population[0][0]
        restart = False
        while True:
            if s.max_generations is not None and generations >= s.max_generations:
                raise _Stop("generations")
            elite, rest = population[:n_elite], population[n_elite:]
            nxt = list(elite)
            if restart:
                while len(nxt) < p:
                    nxt.append(evaluate(decoder.random(rng)))
                restarts += 1
                restart = False
            else:
                for _ in range(n_mutant):
                    nxt.append(evaluate(decoder.random(rng)))
                while len(nxt) < p:
                    a = rng.choice(elite)[1]
                    b = rng.choice(rest)[1] if rest else rng.choice(elite)[1]
                    child = [x if rng.random() < s.rho_e else y for x, y in zip(a, b)]
                    nxt.append(evaluate(child))
            nxt.sort(key=lambda e: e[0])
            population = nxt
            generations += 1
            if population[0][0] < pop_best:
                pop_best, stall = population[0][0], 0
            else:
                stall += 1
                if stall >= s.restart_after:
                    restart, stall = True, 0
    except _Stop as done:
        stop = done.reason
    return Outcome(
        best=state["best"],
        population=p,
        generations=generations,
        decodes=state["decodes"],
        improvements=state["improvements"],
        restarts=restarts,
        best_time=state["best_time"],
        stop=stop,
    )
