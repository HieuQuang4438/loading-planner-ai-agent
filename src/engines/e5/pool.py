"""E5's column pool.

A column is one container the packing core actually laid out: a container type and how many items
of each line it holds, plus one layout for that count vector. Items of one line are identical, so
the master only sees (type, counts); any layout with those counts serves.

Columns come from every core call E5 makes through a `RecordingPacker` (E4's cached `Packer` that
also files each fresh result into the pool) and from whole solutions (the fleet layer's initial
solve calls the core directly, not through a `Packer`). Duplicates -- same type, same counts -- are
kept once.

Two storages: `Column` keeps a count for every line of the lot (dense; every engine but e5-v2-lean);
`SparseColumn` keeps only the lines the container holds (`Pool(sparse=True)`, engine e5-v2-lean): on
a lot of 486 lines, 115 800 dense count tuples took 434 MB. Both hold the same columns in the same order.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar

from src.engines.base import Hints
from src.engines.e4.packer import HintedPackOne, Packer
from src.model import ContainerType, Instance, Params, Placement, line_of

# A layout entry: (line id, x, y, z, orientation); item numbers are assigned when a solution is built.
Slot = tuple[str, float, float, float, str]
# (type id, count per line in instance order); sparse pool: (type id, `SparseColumn.nonzero`)
ColumnKey = tuple[str, tuple]


@dataclass(frozen=True)
class Column:
    sparse: ClassVar[bool] = False
    type: ContainerType
    counts: tuple[int, ...]  # per line, instance order
    layout: tuple[Slot, ...]
    source: str  # which phase first produced it: "e1", "e2", "pricing-e1", ...

    @property
    def key(self) -> ColumnKey:
        return self.type.id, self.counts

    @property
    def cost(self) -> float:
        return self.type.cost

    @cached_property
    def nonzero(self) -> tuple[tuple[int, int], ...]:
        """(line index, count) of the lines the column holds: a container holds a few of a lot's lines,
        so the masters' sparse build walks these instead of every line."""
        return tuple((i, a) for i, a in enumerate(self.counts) if a)


@dataclass(frozen=True)
class SparseColumn:
    """A column holding only its nonzero (line index, count) pairs, by line index; no dense `counts`, so code
    reading them fails loudly instead of paying for a dense tuple."""

    sparse: ClassVar[bool] = True
    type: ContainerType
    nonzero: tuple[tuple[int, int], ...]
    layout: tuple[Slot, ...]
    source: str

    @property
    def key(self) -> ColumnKey:
        return self.type.id, self.nonzero

    @property
    def cost(self) -> float:
        return self.type.cost


AnyColumn = Column | SparseColumn


class Pool:
    def __init__(self, instance: Instance, sparse: bool = False) -> None:
        self.instance = instance
        self.sparse = sparse
        self.line_index = {line.id: i for i, line in enumerate(instance.items)}
        self.columns: list[AnyColumn] = []
        self._index: dict[ColumnKey, int] = {}
        self._pairs: dict[tuple[int, int], tuple[int, int]] = {}  # sparse: one tuple object per (line, count)

    def __len__(self) -> int:
        return len(self.columns)

    def counts_of(self, lines: Iterable[str]) -> tuple[int, ...]:
        counts = [0] * len(self.line_index)
        for line in lines:
            counts[self.line_index[line]] += 1
        return tuple(counts)

    def nonzero_of(self, lines: Iterable[str]) -> tuple[tuple[int, int], ...]:
        counts: dict[int, int] = {}
        for line in lines:
            i = self.line_index[line]
            counts[i] = counts.get(i, 0) + 1
        return tuple(self._pairs.setdefault(pair, pair) for pair in sorted(counts.items()))

    def key_of(self, ctype: ContainerType, lines: Iterable[str]) -> ColumnKey:
        """The pool's key for a container of `ctype` holding `lines` (one entry per item)."""
        return ctype.id, (self.nonzero_of(lines) if self.sparse else self.counts_of(lines))

    def add(self, ctype: ContainerType, placements: Iterable[Placement], source: str) -> int | None:
        """Files one container's layout; returns its column index (existing or new), or None when
        the layout is empty."""
        slots = tuple((line_of(p.item), p.x, p.y, p.z, p.o) for p in placements)
        if not slots:
            return None
        key = self.key_of(ctype, (s[0] for s in slots))
        found = self._index.get(key)
        if found is not None:
            return found
        self._index[key] = len(self.columns)
        self.columns.append((SparseColumn if self.sparse else Column)(ctype, key[1], slots, source))
        return len(self.columns) - 1

    def index(self, key: ColumnKey) -> int | None:
        return self._index.get(key)


class RecordingPacker(Packer):
    """E4's `Packer`, filing every non-empty core result into `pool` under `source`."""

    def __init__(
        self, instance: Instance, params: Params, pack_one: HintedPackOne, deadline: float, pool: Pool, source: str
    ) -> None:
        super().__init__(instance, params, pack_one, deadline)
        self.pool = pool
        self.source = source
        # Knapsack pricing sets a filter: a result is filed only when it passes. A cache hit is
        # then offered too, since the duals that rejected it earlier may have changed (the pool drops duplicates).
        self.admit: Callable[[ContainerType, list[Placement]], bool] | None = None

    def pack(self, items: Iterable[str], ctype: ContainerType, hints: Hints | None = None) -> list[Placement]:
        calls = self.calls
        placed = super().pack(items, ctype, hints)
        if self.admit is not None:
            if self.admit(ctype, placed):
                self.pool.add(ctype, placed, self.source)
        elif self.calls != calls:  # a cache hit was filed when it was first computed
            self.pool.add(ctype, placed, self.source)
        return placed
