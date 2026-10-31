"""Maxrects, best-short-side-fit (Jylänki 2010, "A thousand ways to pack the bin"): step 2 of E1's
core, laying column footprints on the container floor.

Rectangles are placed one at a time, in the caller's order, each where the leftover along its
shorter side is smallest (ties: the longer side, then the free rectangle found first). The free
space is kept as the full list of maximal free rectangles, split around each placement and pruned of
any rectangle inside another.
"""
from __future__ import annotations

EPS = 1e-9

_Rect = tuple[float, float, float, float]  # x, y, width (along x), height (along y)


class MaxRects:
    def __init__(self, width: float, height: float) -> None:
        self.free: list[_Rect] = [(0.0, 0.0, width, height)]
        self.used: list[_Rect] = []

    def insert(self, w: float, h: float, plain: bool = True, turned: bool = True) -> tuple[float, float, bool] | None:
        """Places a w x h rectangle, as given (`plain`) and/or turned 90° (`turned`); returns
        (x, y, was_turned), or `None` when it fits nowhere."""
        options = []
        if plain:
            options.append((False, w, h))
        if turned and abs(w - h) > EPS:
            options.append((True, h, w))
        best = None
        best_score = (float("inf"), float("inf"))
        for fx, fy, fw, fh in self.free:
            for was_turned, rw, rh in options:
                if rw <= fw + EPS and rh <= fh + EPS:
                    left_w, left_h = fw - rw, fh - rh
                    score = (min(left_w, left_h), max(left_w, left_h))
                    if score < best_score:
                        best, best_score = (fx, fy, was_turned, rw, rh), score
        if best is None:
            return None
        x, y, was_turned, rw, rh = best
        self._place((x, y, rw, rh))
        return x, y, was_turned

    def _place(self, placed: _Rect) -> None:
        self.used.append(placed)
        px, py, pw, ph = placed
        split: list[_Rect] = []
        for rect in self.free:
            rx, ry, rw, rh = rect
            if not (px < rx + rw - EPS and rx < px + pw - EPS and py < ry + rh - EPS and ry < py + ph - EPS):
                split.append(rect)
                continue
            if px > rx + EPS:
                split.append((rx, ry, px - rx, rh))
            if px + pw < rx + rw - EPS:
                split.append((px + pw, ry, rx + rw - px - pw, rh))
            if py > ry + EPS:
                split.append((rx, ry, rw, py - ry))
            if py + ph < ry + rh - EPS:
                split.append((rx, py + ph, rw, ry + rh - py - ph))
        self.free = _prune(split)


def _prune(rects: list[_Rect]) -> list[_Rect]:
    """Drops every rectangle contained in another (keeping the first of exact duplicates)."""
    kept: list[_Rect] = []
    for i, a in enumerate(rects):
        if not any(j != i and _contains(b, a) and (not _contains(a, b) or j < i) for j, b in enumerate(rects)):
            kept.append(a)
    return kept


def _contains(outer: _Rect, inner: _Rect) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix + EPS and oy <= iy + EPS and ix + iw <= ox + ow + EPS and iy + ih <= oy + oh + EPS
