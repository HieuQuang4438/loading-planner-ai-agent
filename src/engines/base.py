"""Common engine interface.

Every engine — whatever its packing core, search and fleet layer — exposes the same call:

    solve(instance, params, time_limit, seed) -> (Solution, dict)

An engine registered with `start=True` also takes `start: Solution | None = None`, an earlier solution of the
same lot to continue from; with `start=None` it behaves exactly as without the argument.

`params` (delta, alpha) are run settings, not instance data, so
every engine takes them explicitly instead of hard-coding a value. No engine module runs the
checker itself; every returned `Solution` must go through `src.checker.check` before being trusted
(the runner, `src.run`, does this for every result).

The `dict` is free-form, engine-specific run diagnostics, written into the runner's `results.jsonl` row for that (instance, seed) rather than parsed by
`src.run` itself. An engine with nothing to report (e.g. `src.engines.shelf`) returns `{}`. This is a
plain second return value, not a wrapper type, because every engine's diagnostics shape differs and
nothing downstream needs to interpret it structurally.

`register`/`get`/`names` are a name -> callable registry so the runner can resolve `--engine NAME`
without importing every engine module by hand.

`Piece` and `expand_pieces` support the packing-core contract used by `src.engines.fleet`:
`pack_one(items, ctype, params, rng) -> placements`.
A core is handed `list[Piece]` instead of an `Instance` slice so it needs
nothing beyond its four arguments to place items into one empty container.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable

from src.model import (
    ContainerType,
    Instance,
    Params,
    Placement,
    Solution,
    allowed_orientations,
    item_id,
    line_of,
)

Engine = Callable[[Instance, Params, float, int], "tuple[Solution, dict[str, Any]]"]

_REGISTRY: dict[str, Engine] = {}
_STARTABLE: set[str] = set()  # engines whose call also takes `start=`
_ALIASES: dict[str, str] = {}  # old name -> current name: still resolves in `get`, not listed by `names`


def register(name: str, engine: Engine, start: bool = False) -> None:
    """`start`: the engine takes the optional `start=` solution."""
    if name in _REGISTRY:
        raise ValueError(f"engine {name!r} already registered")
    _REGISTRY[name] = engine
    if start:
        _STARTABLE.add(name)


def alias(old: str, name: str) -> None:
    """Keep `old` resolving to the engine registered as `name` (a renamed engine; old runs and scripts
    still say `old`). The alias is hidden from `names`, so lists and menus show each engine once."""
    if name not in _REGISTRY or old in _REGISTRY or old in _ALIASES:
        raise ValueError(f"cannot alias {old!r} to {name!r}")
    _ALIASES[old] = name


def canonical(name: str) -> str:
    """The current name of an engine, whether given by it or by an alias."""
    return _ALIASES.get(name, name)


def get(name: str) -> Engine:
    try:
        return _REGISTRY[canonical(name)]
    except KeyError:
        raise KeyError(f"unknown engine {name!r}; available: {sorted(_REGISTRY)}") from None


def accepts_start(name: str) -> bool:
    """Whether the engine (by its name or an alias) takes a `start` solution."""
    return canonical(name) in _STARTABLE


def names() -> list[str]:
    return sorted(_REGISTRY)


@dataclass(frozen=True)
class Piece:
    """One concrete item ready for a packing core: a line's per-item id, paired with the line's own
    shape and packing limits. `item` is the final placement id (e.g. "L1#3")."""

    item: str
    L: float
    W: float
    H: float
    mass: float
    tippable: bool
    tiers: int
    load: float | None
    orientations: tuple[str, ...] | None = None  # the line's explicit allowed set, else derived from `tippable`

    @property
    def allowed(self) -> tuple[str, ...]:
        return allowed_orientations(self.tippable, self.orientations)

    def dims(self, orientation: str) -> tuple[float, float, float]:
        """Extents (l', w', h') along x, y, z in the given orientation."""
        size = {"L": self.L, "W": self.W, "H": self.H}
        return size[orientation[0]], size[orientation[1]], size[orientation[2]]


PackOne = Callable[[list[Piece], ContainerType, Params, random.Random], list[Placement]]


@dataclass(frozen=True)
class Hints:
    """Optional steering a search passes to a packing core (option 2A): per item line, an order key and a preferred
    turn about the vertical axis. What each core does with them is in its own `pack`; a core called
    without hints behaves exactly as before.

    `order`: (line id, key) pairs; lower keys go first, the core's own order breaking ties. A line
    missing from a non-empty `order` gets key 0. `turn`: (line id, turned) pairs; a line missing
    from a non-empty `turn` prefers the unturned way. Tuples, not dicts, so hints hash (a search may
    cache core results by them)."""

    order: tuple[tuple[str, float], ...] = ()
    turn: tuple[tuple[str, bool], ...] = ()

    def order_key(self, line: str) -> float:
        return self._order.get(line, 0.0)

    def turned(self, line: str) -> bool:
        return self._turn.get(line, False)

    @property
    def _order(self) -> dict[str, float]:
        return _as_dict(self.order)

    @property
    def _turn(self) -> dict[str, bool]:
        return _as_dict(self.turn)


_DICTS: dict[tuple, dict] = {}


def _as_dict(pairs: tuple) -> dict:
    """Memoised dict view of a hint tuple: cores look keys up once per piece."""
    d = _DICTS.get(pairs)
    if d is None:
        if len(_DICTS) > 4096:
            _DICTS.clear()
        d = _DICTS[pairs] = dict(pairs)
    return d


def expand_pieces(instance: Instance) -> list[Piece]:
    """Every item of `instance`, expanded from lines into individual pieces, in instance order."""
    return [
        Piece(item_id(line.id, n), line.L, line.W, line.H, line.mass, line.tippable, line.tiers, line.load, line.orientations)
        for line in instance.items
        for n in range(1, line.qty + 1)
    ]


def piece_of(instance: Instance, item: str) -> Piece:
    """The `Piece` for one already-placed item id, looked up by its line — used when a piece needs
    rebuilding outside `expand_pieces`'s one-pass walk (e.g. `src.engines.fleet`'s swap step, which
    repacks a specific container's items into a candidate replacement type)."""
    line = instance.line(line_of(item))
    assert line is not None
    return Piece(item, line.L, line.W, line.H, line.mass, line.tippable, line.tiers, line.load, line.orientations)
