"""E3's decoder: random keys -> containers, through E1's or E2's `pack_one` (options 1A, 2A).

A chromosome is a list of keys in [0, 1), laid out as

    [order_0, turn_0, order_1, turn_1, ..., order_{n-1}, turn_{n-1}, type_0, ..., type_{S-1}]

one (order, turn) pair per item line, in instance order, then one container-type key per container
slot. Decoding opens containers one at a time over the pieces still unplaced:

1. The candidate types are those at least one remaining piece fits (`src.formats.fits_container`),
   cheapest first (ties by id). Slot j's key picks one: index floor(key x number of candidates).
   Past the last slot, slots are reused cyclically (slot j mod S).
2. The pieces that fit the picked type go to one cached core call (`src.engines.e4.packer.Packer`)
   with `Hints` built from the keys of the lines present in that call: order = dense rank of the
   order keys among those lines (equal keys, equal rank), turn = turn key >= 0.5. Ranks, not raw
   keys, so two chromosomes with the same permutation give the same hints and hit the cache.
3. What the core placed forms a container; the rest goes on to the next slot.

When every piece is placed, the last container opened tries each cheaper type, cheapest first, and
moves to the first whose core call places all its items (the fleet layer's last-container swap).
"""
from __future__ import annotations

import random

from src.engines.base import Hints
from src.engines.e4.packer import Packer
from src.engines.e4.state import EPS, Box, make_box
from src.formats import fits_container
from src.model import Instance, line_of

TURN_THRESHOLD = 0.5  # a turn key at or above this prefers the turned way


class Decoder:
    def __init__(self, instance: Instance, packer: Packer, slots: int) -> None:
        if slots < 1:
            raise ValueError("at least one container slot")
        self.packer = packer
        self.lines = [line.id for line in instance.items]
        self.n_lines = len(self.lines)
        self.slots = slots
        self.length = 2 * self.n_lines + slots
        self.types = sorted(instance.container_types, key=lambda t: (t.cost, t.id))
        index = {line: i for i, line in enumerate(self.lines)}
        self._fits = [[fits_container(line, t) for t in self.types] for line in instance.items]
        self._items = sorted(packer.pieces, key=packer.sort_key)  # canonical order
        self._line_idx = {item: index[line_of(item)] for item in self._items}

    def random(self, rng: random.Random) -> list[float]:
        return [rng.random() for _ in range(self.length)]

    def seeded(self, types: list[str], rng: random.Random) -> tuple[list[float], list[Box]]:
        """A chromosome decoding near a known solution (option 3A): every order key equal
        (so the core keeps its own order), every line unturned, and slot j forced to `types[j]`
        whenever that type is a candidate there; other slot keys random. Returns it with its decode."""
        chrom = [0.5 if g % 2 == 0 else 0.25 for g in range(2 * self.n_lines)]
        chrom += [rng.random() for _ in range(self.slots)]
        return chrom, self.decode(chrom, force=types)

    def hints(self, chrom: list[float], present: list[int]) -> Hints:
        """Hints for one core call on the lines `present` (indices, in instance order)."""
        keys = sorted({chrom[2 * i] for i in present})
        rank = {k: float(r) for r, k in enumerate(keys)}
        order = tuple((self.lines[i], rank[chrom[2 * i]]) for i in present)
        turn = tuple((self.lines[i], chrom[2 * i + 1] >= TURN_THRESHOLD) for i in present)
        return Hints(order=order, turn=turn)

    def type_index(self, key: float, n: int) -> int:
        return min(int(key * n), n - 1)

    def decode(self, chrom: list[float], force: list[str] | None = None) -> list[Box]:
        """The chromosome's containers. With `force`, slot j's key is first rewritten (in `chrom`) to
        pick `force[j]` when that type is a candidate at slot j."""
        remaining = list(self._items)
        boxes: list[Box] = []
        j = 0
        while remaining:
            present = sorted({self._line_idx[i] for i in remaining})
            candidates = [t for ti, t in enumerate(self.types) if any(self._fits[li][ti] for li in present)]
            if not candidates:
                raise ValueError(f"no container type takes any of {len(remaining)} remaining item(s)")
            gene = 2 * self.n_lines + j % self.slots
            if force is not None and j < len(force):
                ids = [t.id for t in candidates]
                if force[j] in ids:
                    chrom[gene] = (ids.index(force[j]) + 0.5) / len(candidates)
            ctype = candidates[self.type_index(chrom[gene], len(candidates))]
            ti = self.types.index(ctype)
            items = [i for i in remaining if self._fits[self._line_idx[i]][ti]]
            hints = self.hints(chrom, sorted({self._line_idx[i] for i in items}))
            placed = self.packer.pack(items, ctype, hints)
            if not placed:
                raise ValueError(f"{ctype.id}: core placed 0 items into an empty container")
            box = make_box(ctype, placed, self.packer.pieces, hints)
            boxes.append(box)
            remaining = [i for i in remaining if i not in box.items]
            j += 1
        boxes[-1] = self._downgrade(boxes[-1])
        return boxes

    def _downgrade(self, box: Box) -> Box:
        present = sorted({self._line_idx[i] for i in box.items})
        for ti, ctype in enumerate(self.types):
            if ctype.cost >= box.type.cost - EPS:
                break
            if box.volume > ctype.volume + EPS or box.mass > ctype.max_mass + EPS:
                continue
            if not all(self._fits[li][ti] for li in present):
                continue
            placed = self.packer.pack(box.items, ctype, box.hints)
            if len(placed) == len(box.items):
                return make_box(ctype, placed, self.packer.pieces, box.hints)
        return box
