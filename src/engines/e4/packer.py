"""Cached calls of a packing core for E4.

A container of E4's state is a type and an item set; its layout is whatever the core's `pack_one`
returns for that set (option 1A). The same (type, set, hints) comes back often -- a
container left alone by one iteration is re-tried by the next -- so results are cached.

**Why caching is exact.** Items are handed to the core in one canonical order: by line, in instance
order, then by item number. Items of one line are identical, and E1's and E2's cores look only at
piece dimensions, mass, limits and input position (never at the item id), so the core's result
depends only on (type, number of items of each line, hints). A cached layout is replayed by
position: the j-th piece of the canonical input in the cached call is the j-th piece of the
canonical input now, same line.
"""
from __future__ import annotations

import random
import time
from collections import OrderedDict
from collections.abc import Iterable
from typing import Callable

from src.engines.base import Hints, Piece, expand_pieces
from src.model import ContainerType, Instance, Params, Placement, line_of

HintedPackOne = Callable[..., list[Placement]]  # pack_one(items, ctype, params, rng, hints)

CACHE_SIZE = 20_000  # entries; one entry is one container's layout
_RNG = random.Random(0)  # E1's and E2's cores ignore rng


class Deadline(RuntimeError):
    """The search's time is up; raised before a core call, never in the middle of one."""


_Key = tuple[str, tuple[tuple[str, int], ...], Hints | None]
_Entry = tuple[tuple[int, float, float, float, str], ...]  # (canonical position, x, y, z, o)


class Packer:
    def __init__(self, instance: Instance, params: Params, pack_one: HintedPackOne, deadline: float) -> None:
        self.params = params
        self.pack_one = pack_one
        self.deadline = deadline
        self.pieces: dict[str, Piece] = {p.item: p for p in expand_pieces(instance)}
        rank = {line.id: i for i, line in enumerate(instance.items)}
        self._sort_key = {item: (rank[line_of(item)], int(item.rsplit("#", 1)[1])) for item in self.pieces}
        self._cache: OrderedDict[_Key, _Entry] = OrderedDict()
        self.calls = 0
        self.hits = 0

    def sort_key(self, item: str) -> tuple[int, int]:
        """Canonical item order: line in instance order, then item number."""
        return self._sort_key[item]

    def pack(self, items: Iterable[str], ctype: ContainerType, hints: Hints | None = None) -> list[Placement]:
        """The core's placements (k = 0) for `items` in one empty `ctype`."""
        order = sorted(items, key=self._sort_key.__getitem__)
        key = (ctype.id, _runs(order), hints)
        entry = self._cache.get(key)
        if entry is not None:
            self.hits += 1
            self._cache.move_to_end(key)
            return [Placement(order[j], 0, x, y, z, o) for j, x, y, z, o in entry]
        if time.monotonic() > self.deadline:
            raise Deadline
        placed = self.pack_one([self.pieces[i] for i in order], ctype, self.params, _RNG, hints)
        self.calls += 1
        position = {item: j for j, item in enumerate(order)}
        self._cache[key] = tuple((position[p.item], p.x, p.y, p.z, p.o) for p in placed)
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return placed


def _runs(order: list[str]) -> tuple[tuple[str, int], ...]:
    """(line, count) runs of a canonically ordered item list: the multiset, in a hashable form."""
    runs: list[tuple[str, int]] = []
    for item in order:
        line = line_of(item)
        if runs and runs[-1][0] == line:
            runs[-1] = (line, runs[-1][1] + 1)
        else:
            runs.append((line, 1))
    return tuple(runs)
