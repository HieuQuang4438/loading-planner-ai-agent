"""E4's destroy and repair operators (options 3A, 4A).

Destroy takes items out of the solution into a pool; repair puts every pooled item back. Neither
touches coordinates: a changed container is re-packed from scratch by the core (`Packer`), and a
container is only kept if the core places every item it must hold.

Destroy:
- `worst`: empty the emptiest container (by `Box.fill`), picked with Ropke-Pisinger's randomised
  rank (`worst_determinism`), so repeated calls do not always hit the same one.
- `random_containers`: empty 1 or 2 containers chosen at random.
- `random_items`: take a random `destroy_share` of the items out of 2 or 3 random containers; each
  is re-packed during repair (taking items out can break support, so old coordinates are not kept).

Repair (greedy, fullest-first insertion; `shuffle` = the light-shuffle variant):
1. Containers from fullest to emptiest (shuffle: fill plus uniform noise up to `shuffle_noise`).
   Each gets pooled items, largest first (shuffle: volume times a random factor), as many as its
   free volume and mass allow, in one core call on its items plus those; the result is kept if the
   core placed every item the container already had, taking whichever pooled items it also placed.
   If not, and `hint_retry`, once more with random hints (order and turn, `random_hints`); a win
   keeps those hints on the container. A container changed by destroy that takes nothing is
   re-packed alone; what the core then leaves out goes back to the pool.
2. Whatever is left opens new containers: the cheapest type whose one call places the whole pool;
   if none does, the type placing the most volume per cost, then again on the rest.
3. Every container changed by this repair tries each cheaper type, cheapest first, and moves to the
   first whose call places all its items (the fleet layer's last-container swap, for each).
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from src.engines.base import Hints
from src.engines.e4.packer import Packer
from src.engines.e4.state import EPS, Box, make_box
from src.formats import fits_container
from src.model import ContainerType, Instance, Placement, line_of

ORDER_NOISE = 1.0  # sd of the noise added to a line's default rank in random order hints ("light")


@dataclass(frozen=True)
class Settings:
    """Search parameters."""

    start_temperature: float = 0.02  # a solution this share of the initial objective worse is accepted with p = 0.5
    end_temperature: float = 0.01  # final temperature, as a share of the start one
    reaction: float = 0.1  # Ropke-Pisinger r
    segment: int = 20  # iterations between weight updates
    scores: tuple[float, float, float] = (33.0, 9.0, 13.0)  # new best, better than current, accepted new
    destroy_share: float = 0.3  # share of a container's items `random_items` takes out
    worst_determinism: float = 4.0  # Ropke-Pisinger p for `worst`
    shuffle_noise: float = 0.1  # fill noise of the shuffled repair's container order
    hint_retry: bool = True
    time_share: float = 0.95  # of time_limit: slack for process start-up and writing the solution
    max_iterations: int | None = None  # for tests: stop (and cool) by iteration count, not time
    # (E5's e5-mono-*, not E4): "anneal" cools by elapsed share of the budget; "flat" anneals at a
    # fixed `flat_temperature` x T0; "lahc" is late acceptance over `lahc_length` iterations. Neither of the
    # last two needs the end of the run, so a longer run repeats a shorter one's iterations and adds more.
    acceptance: str = "anneal"
    flat_temperature: float = 0.1
    lahc_length: int = 50
    # Stall rule (E5's e5-v4; off in E4): stop with "stall" once the iterations since the last
    # improvement exceed max(stall_min, stall_ratio x the iteration of that improvement). Counted in iterations.
    stall_min: int | None = None
    stall_ratio: float = 2.0


@dataclass
class Work:
    """A solution being destroyed and repaired."""

    boxes: list[Box]
    pool: list[str]


@dataclass
class Context:
    instance: Instance
    packer: Packer
    rng: random.Random
    settings: Settings
    hint_wins: int = 0

    def __post_init__(self) -> None:
        self.types = sorted(self.instance.container_types, key=lambda t: t.cost)
        self._fits = {(line.id, t.id): fits_container(line, t) for line in self.instance.items for t in self.types}
        ranked = sorted(
            enumerate(self.instance.items), key=lambda il: (-il[1].L * il[1].W, -il[1].mass, il[0])
        )
        self.rank = {line.id: r for r, (_, line) in enumerate(ranked)}

    def volume(self, item: str) -> float:
        p = self.packer.pieces[item]
        return p.L * p.W * p.H

    def mass(self, item: str) -> float:
        return self.packer.pieces[item].mass

    def fits(self, item: str, ctype: ContainerType) -> bool:
        return self._fits[(line_of(item), ctype.id)]

    def box(self, ctype: ContainerType, placed: list[Placement], hints: Hints | None) -> Box:
        return make_box(ctype, placed, self.packer.pieces, hints)


# --- destroy ------------------------------------------------------------------------------------


def worst(work: Work, ctx: Context) -> None:
    if not work.boxes:
        return
    ranked = sorted(work.boxes, key=lambda b: b.fill)
    idx = int(len(ranked) * ctx.rng.random() ** ctx.settings.worst_determinism)
    _empty(work, ranked[idx])


def random_containers(work: Work, ctx: Context) -> None:
    n = min(len(work.boxes), ctx.rng.choice((1, 2)))
    for box in ctx.rng.sample(work.boxes, n):
        _empty(work, box)


def random_items(work: Work, ctx: Context) -> None:
    n = min(len(work.boxes), ctx.rng.choice((2, 3)))
    for i, box in enumerate(ctx.rng.sample(work.boxes, n)):
        items = sorted(box.items, key=ctx.packer.sort_key)
        take = max(1, round(ctx.settings.destroy_share * len(items)))
        removed = set(ctx.rng.sample(items, min(take, len(items))))
        if len(removed) == len(items):
            _empty(work, box)
            continue
        keep = box.items - removed
        box.items = keep
        box.volume -= sum(ctx.volume(i) for i in removed)
        box.mass -= sum(ctx.mass(i) for i in removed)
        box.placements = ()
        box.dirty = True
        work.pool += sorted(removed, key=ctx.packer.sort_key)


def _empty(work: Work, box: Box) -> None:
    work.boxes.remove(box)
    work.pool += sorted(box.items)


DESTROYS: dict[str, Callable[[Work, Context], None]] = {
    "worst": worst,
    "random_containers": random_containers,
    "random_items": random_items,
}


# --- repair -------------------------------------------------------------------------------------


def greedy(work: Work, ctx: Context) -> None:
    _repair(work, ctx, shuffle=False)


def greedy_shuffle(work: Work, ctx: Context) -> None:
    _repair(work, ctx, shuffle=True)


REPAIRS: dict[str, Callable[[Work, Context], None]] = {"greedy": greedy, "greedy_shuffle": greedy_shuffle}


def _repair(work: Work, ctx: Context, shuffle: bool) -> None:
    rng = ctx.rng
    noise = ctx.settings.shuffle_noise
    boxes = sorted(work.boxes, key=lambda b: -(b.fill + (rng.uniform(0.0, noise) if shuffle else 0.0)))
    if shuffle:
        pool = sorted(work.pool, key=lambda i: -ctx.volume(i) * rng.uniform(0.8, 1.2))
    else:
        pool = sorted(work.pool, key=lambda i: (-ctx.volume(i), ctx.packer.sort_key(i)))
    for box in boxes:
        if pool:
            taken = _fill(box, pool, ctx)
            if taken:
                pool = [i for i in pool if i not in taken]
                continue
        if box.dirty:
            pool += _repack(box, ctx)
    work.boxes = [b for b in boxes if b.items]
    while pool:
        pool = _open(work, pool, ctx)
    work.pool = []
    for i, box in enumerate(work.boxes):
        if box.touched:
            work.boxes[i] = _downgrade(box, ctx)


def _fill(box: Box, pool: list[str], ctx: Context) -> set[str]:
    """Pooled items the core adds to `box` (keeping every item it has), or an empty set."""
    free_v = box.type.volume - box.volume
    free_m = box.type.max_mass - box.mass
    candidates = []
    for item in pool:
        v, m = ctx.volume(item), ctx.mass(item)
        if v <= free_v + EPS and m <= free_m + EPS and ctx.fits(item, box.type):
            candidates.append(item)
            free_v -= v
            free_m -= m
    if not candidates:
        return set()
    wanted = box.items | set(candidates)
    for hints in _hint_tries(box, ctx):
        placed = ctx.packer.pack(wanted, box.type, hints)
        ids = {p.item for p in placed}
        if box.items <= ids:
            if hints is not box.hints:
                ctx.hint_wins += 1
            old = box.items
            _commit(box, placed, hints, ctx)
            return ids - old
    return set()


def _repack(box: Box, ctx: Context) -> list[str]:
    """Re-packs a container changed by destroy on its own; returns the items the core left out."""
    best: list[Placement] | None = None
    best_hints = box.hints
    for hints in _hint_tries(box, ctx):
        placed = ctx.packer.pack(box.items, box.type, hints)
        if best is None or _volume(placed, ctx) > _volume(best, ctx) + EPS:
            best, best_hints = placed, hints
        if len(placed) == len(box.items):
            break
    assert best is not None
    if best_hints is not box.hints and len(best) == len(box.items):
        ctx.hint_wins += 1
    left = box.items - {p.item for p in best}
    _commit(box, best, best_hints, ctx)
    return sorted(left, key=ctx.packer.sort_key)


def _open(work: Work, pool: list[str], ctx: Context) -> list[str]:
    """Opens one new container for (part of) the pool; returns what is still unplaced."""
    best: tuple[float, ContainerType, list[Placement]] | None = None
    for ctype in ctx.types:
        fitting = [i for i in pool if ctx.fits(i, ctype)]
        if not fitting:
            continue
        placed = ctx.packer.pack(fitting, ctype)
        if len(placed) == len(pool):
            best = (math.inf, ctype, placed)
            break
        rate = _volume(placed, ctx) / ctype.cost
        if placed and (best is None or rate > best[0] + EPS):
            best = (rate, ctype, placed)
    if best is None:
        raise ValueError(f"no container type takes any of {len(pool)} pooled item(s)")
    _, ctype, placed = best
    box = ctx.box(ctype, placed, None)
    box.touched = True
    work.boxes.append(box)
    ids = box.items
    return [i for i in pool if i not in ids]


def _downgrade(box: Box, ctx: Context) -> Box:
    for ctype in ctx.types:
        if ctype.cost >= box.type.cost - EPS:
            break
        if box.volume > ctype.volume + EPS or box.mass > ctype.max_mass + EPS:
            continue
        if not all(ctx.fits(i, ctype) for i in box.items):
            continue
        placed = ctx.packer.pack(box.items, ctype, box.hints)
        if len(placed) == len(box.items):
            smaller = ctx.box(ctype, placed, box.hints)
            smaller.touched = True
            return smaller
    return box


def _hint_tries(box: Box, ctx: Context) -> Iterator[Hints | None]:
    """The container's own hints, then (with `hint_retry`) one random draw."""
    yield box.hints
    if ctx.settings.hint_retry:
        yield random_hints({line_of(i) for i in box.items}, ctx)


def random_hints(lines: set[str], ctx: Context) -> Hints:
    """Light perturbation of the default line order (base area, largest first) plus a turn choice:
    all unturned, all turned, or per line at random -- "no turn", "turn", and a mix."""
    rng = ctx.rng
    ranked = sorted(lines, key=ctx.rank.__getitem__)
    order = tuple((line, ctx.rank[line] + rng.gauss(0.0, ORDER_NOISE)) for line in ranked)
    mode = rng.randrange(3)
    turn = tuple((line, mode == 1 or (mode == 2 and rng.random() < 0.5)) for line in ranked)
    return Hints(order=order, turn=turn)


def _commit(box: Box, placed: list[Placement], hints: Hints | None, ctx: Context) -> None:
    fresh = ctx.box(box.type, placed, hints)
    box.items, box.placements, box.volume, box.mass = fresh.items, fresh.placements, fresh.volume, fresh.mass
    box.hints = hints
    box.dirty = False
    box.touched = True


def _volume(placed: list[Placement], ctx: Context) -> float:
    return sum(ctx.volume(p.item) for p in placed)
