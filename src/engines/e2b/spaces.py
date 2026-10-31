"""Maximal spaces.

A space is an axis-aligned empty box `(x0, y0, z0, x1, y1, z1)` in the **widened frame**: every
block claims its footprint widened by `delta` along +x and +y, and the container is widened the same
way, so two widened boxes with disjoint interiors are at least `delta` apart in x or y (constraint 5)
or stacked (touching in z is allowed). Heights are not widened.

The set holds the maximal empty boxes. Placing a block cuts every space whose interior meets the
block's widened box into up to six pieces (the parts left of, right of, in front of, behind, below
and above the block); a piece too small for any item, or contained in another space, is dropped.
Old spaces the block does not touch never lose their maximality, so only the new pieces are tested
for containment.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-9


class Spaces:
    def __init__(self, dx: float, dy: float, dz: float, min_dx: float, min_dy: float, min_dz: float) -> None:
        self.a = np.array([[0.0, 0.0, 0.0, dx, dy, dz]])
        self.min = np.array([min_dx, min_dy, min_dz])
        self.generated = 1
        self.peak = 1

    def __len__(self) -> int:
        return len(self.a)

    def lowest(self) -> int:
        """Index of the space with the lowest corner: smallest z, then x, then y."""
        return int(np.lexsort((self.a[:, 1], self.a[:, 0], self.a[:, 2]))[0])

    def drop(self, i: int) -> None:
        self.a = np.delete(self.a, i, axis=0)

    def cut(self, box: tuple[float, float, float, float, float, float]) -> None:
        """Removes `box` (a widened block, x0 y0 z0 x1 y1 z1) from the free volume."""
        bx0, by0, bz0, bx1, by1, bz1 = box
        s = self.a
        hit = (
            (s[:, 0] < bx1 - EPS) & (s[:, 3] > bx0 + EPS)
            & (s[:, 1] < by1 - EPS) & (s[:, 4] > by0 + EPS)
            & (s[:, 2] < bz1 - EPS) & (s[:, 5] > bz0 + EPS)
        )
        if not hit.any():
            return
        kept, cut = s[~hit], s[hit]
        parts = []

        def piece(mask: np.ndarray, col: int, value: float) -> None:
            if mask.any():
                c = cut[mask].copy()
                c[:, col] = value
                parts.append(c)

        piece(cut[:, 0] < bx0 - EPS, 3, bx0)
        piece(cut[:, 3] > bx1 + EPS, 0, bx1)
        piece(cut[:, 1] < by0 - EPS, 4, by0)
        piece(cut[:, 4] > by1 + EPS, 1, by1)
        piece(cut[:, 2] < bz0 - EPS, 5, bz0)
        piece(cut[:, 5] > bz1 + EPS, 2, bz1)
        if not parts:
            self.a = kept
            return
        children = np.concatenate(parts)
        big = np.all(children[:, 3:] - children[:, :3] >= self.min - EPS, axis=1)
        children = children[big]
        if len(children):
            children = children[~self._contained(children, kept)]
        self.generated += len(children)
        self.a = np.concatenate([kept, children])
        self.peak = max(self.peak, len(self.a))

    @staticmethod
    def _contained(children: np.ndarray, kept: np.ndarray) -> np.ndarray:
        """Which children lie inside a kept space or inside another child (of two equal children, the
        later one is dropped)."""
        k, m = len(children), len(kept)
        pool = np.concatenate([kept, children])
        inside = np.all(pool[None, :, :3] <= children[:, None, :3] + EPS, axis=2) & np.all(
            pool[None, :, 3:] >= children[:, None, 3:] - EPS, axis=2
        )
        inside[np.arange(k), m + np.arange(k)] = False
        drop = inside[:, :m].any(axis=1)
        among = inside[:, m:]
        mutual = among & among.T
        drop |= (among & ~mutual).any(axis=1)
        drop |= np.tril(mutual, k=-1).any(axis=1)
        return drop
