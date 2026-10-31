"""Extreme points and their residual space (Crainic, Perboli & Tadei 2008, "Extreme point-based
heuristics for three-dimensional bin packing").

**Frame.** `delta` (constraint 5) is handled by widening every box's footprint, and the floor, by
`delta` along +x and +y: box `i` claims
[x0, x1 + delta) x [y0, y1 + delta) x [z0, z1), and a corner at x may take extent `a` along x only
if x + a <= L. Heights are not widened: boxes stacked on each other touch.

**Generation.** A box placed at (x, y, z) with far faces (X, Y, Z) in the widened frame yields up
to six points, Crainic's projections: (X, y, z) slid along -y and along -z, (x, Y, z) slid along -x
and along -z, (x, y, Z) slid along -x and along -y. A slide stops at the nearest face of a box whose
widened extents contain the point across the other two axes, or at the wall / floor. Points outside
the container or inside some box, and duplicates, are dropped; a point a new box covers is removed.

**Residual space** of a point: how far it is, along +x, +y and +z, to the nearest box face crossing
that ray (widened frame) or to the wall -- the largest extent a box at that corner could have along
each axis on its own. Computed for new points against every box, and cut down for existing points
each time a box is placed. It is a necessary condition only (a box may clip a face the ray misses);
the exact check is `src.engines.e2.layout`. A point whose residual space is below the smallest
extent any piece of the call can have is dead for good -- residual space only shrinks -- and dropped.
"""
from __future__ import annotations

import numpy as np

from src.engines.e2.layout import EPS, Layout
from src.model import ContainerType


class ExtremePoints:
    def __init__(self, ctype: ContainerType, min_side: float, min_height: float) -> None:
        self.L, self.W, self.H = ctype.L, ctype.W, ctype.H
        self.min_side = min_side
        self.min_height = min_height
        self.x = np.zeros(1)
        self.y = np.zeros(1)
        self.z = np.zeros(1)
        self.rx = np.array([self.L])
        self.ry = np.array([self.W])
        self.rz = np.array([self.H])

    def __len__(self) -> int:
        return len(self.x)

    def after_place(self, layout: Layout, k: int) -> None:
        """Updates the point set once box `k` is in `layout`."""
        self._cut(layout, k)
        new = self._project(layout, k)
        if len(new):
            self._append(layout, new)
        self._prune()

    def _cut(self, layout: Layout, k: int) -> None:
        d = layout.delta
        x0, y0, z0 = layout.x0[k], layout.y0[k], layout.z0[k]
        X, Y, Z = layout.x1[k] + d, layout.y1[k] + d, layout.z1[k]
        in_x = (x0 - EPS <= self.x) & (self.x < X - EPS)
        in_y = (y0 - EPS <= self.y) & (self.y < Y - EPS)
        in_z = (z0 - EPS <= self.z) & (self.z < Z - EPS)
        keep = ~(in_x & in_y & in_z)
        self._keep(keep)
        # Rays along +x, +y, +z from the surviving points that box k now blocks.
        ahead_x = in_y[keep] & in_z[keep] & (self.x <= x0 + EPS)
        self.rx = np.where(ahead_x, np.minimum(self.rx, x0 - self.x - d), self.rx)
        ahead_y = in_x[keep] & in_z[keep] & (self.y <= y0 + EPS)
        self.ry = np.where(ahead_y, np.minimum(self.ry, y0 - self.y - d), self.ry)
        ahead_z = in_x[keep] & in_y[keep] & (self.z <= z0 + EPS)
        self.rz = np.where(ahead_z, np.minimum(self.rz, z0 - self.z), self.rz)

    def _project(self, layout: Layout, k: int) -> np.ndarray:
        n, d = layout.n, layout.delta
        x0, y0, z0 = layout.x0[:n], layout.y0[:n], layout.z0[:n]
        X, Y, Z = layout.x1[:n] + d, layout.y1[:n] + d, layout.z1[:n]
        xk, yk, zk = layout.x0[k], layout.y0[k], layout.z0[k]
        Xk, Yk, Zk = X[k], Y[k], Z[k]

        def contains(lo: np.ndarray, hi: np.ndarray, p: float | np.ndarray) -> np.ndarray:
            return (lo - EPS <= p) & (p < hi - EPS)

        def slide(p: float, lo_mask: np.ndarray, far: np.ndarray) -> float:
            """Largest far face at or behind `p` among the boxes `lo_mask` selects; 0 (wall) if none."""
            hit = lo_mask & (far <= p + EPS)
            return float(far[hit].max()) if hit.any() else 0.0

        points = [
            (Xk, slide(yk, contains(x0, X, Xk) & contains(z0, Z, zk), Y), zk),
            (Xk, yk, slide(zk, contains(x0, X, Xk) & contains(y0, Y, yk), Z)),
            (slide(xk, contains(y0, Y, Yk) & contains(z0, Z, zk), X), Yk, zk),
            (xk, Yk, slide(zk, contains(x0, X, xk) & contains(y0, Y, Yk), Z)),
            (slide(xk, contains(y0, Y, yk) & contains(z0, Z, Zk), X), yk, Zk),
            (xk, slide(yk, contains(x0, X, xk) & contains(z0, Z, Zk), Y), Zk),
        ]
        pts = np.array(points)
        inside = (pts[:, 0] < self.L - EPS) & (pts[:, 1] < self.W - EPS) & (pts[:, 2] < self.H - EPS)
        pts = pts[inside]
        if not len(pts):
            return pts
        px, py, pz = pts[:, 0:1], pts[:, 1:2], pts[:, 2:3]
        occupied = np.any(contains(x0, X, px) & contains(y0, Y, py) & contains(z0, Z, pz), axis=1)
        pts = pts[~occupied]
        unique = []
        for p in pts:
            if any(np.all(np.abs(p - q) <= EPS) for q in unique):
                continue
            if np.any((np.abs(self.x - p[0]) <= EPS) & (np.abs(self.y - p[1]) <= EPS) & (np.abs(self.z - p[2]) <= EPS)):
                continue
            unique.append(p)
        return np.array(unique)

    def _append(self, layout: Layout, pts: np.ndarray) -> None:
        n, d = layout.n, layout.delta
        x0, y0, z0 = layout.x0[:n], layout.y0[:n], layout.z0[:n]
        X, Y, Z = layout.x1[:n] + d, layout.y1[:n] + d, layout.z1[:n]
        px, py, pz = pts[:, 0:1], pts[:, 1:2], pts[:, 2:3]
        in_x = (x0 - EPS <= px) & (px < X - EPS)
        in_y = (y0 - EPS <= py) & (py < Y - EPS)
        in_z = (z0 - EPS <= pz) & (pz < Z - EPS)
        inf = np.inf
        rx = np.where(in_y & in_z & (x0 >= px - EPS), x0 - px - d, inf).min(axis=1)
        ry = np.where(in_x & in_z & (y0 >= py - EPS), y0 - py - d, inf).min(axis=1)
        rz = np.where(in_x & in_y & (z0 >= pz - EPS), z0 - pz, inf).min(axis=1)
        self.x = np.concatenate([self.x, pts[:, 0]])
        self.y = np.concatenate([self.y, pts[:, 1]])
        self.z = np.concatenate([self.z, pts[:, 2]])
        self.rx = np.concatenate([self.rx, np.minimum(rx, self.L - pts[:, 0])])
        self.ry = np.concatenate([self.ry, np.minimum(ry, self.W - pts[:, 1])])
        self.rz = np.concatenate([self.rz, np.minimum(rz, self.H - pts[:, 2])])

    def _prune(self) -> None:
        alive = (self.rx >= self.min_side - EPS) & (self.ry >= self.min_side - EPS) & (self.rz >= self.min_height - EPS)
        self._keep(alive)

    def _keep(self, mask: np.ndarray) -> None:
        self.x, self.y, self.z = self.x[mask], self.y[mask], self.z[mask]
        self.rx, self.ry, self.rz = self.rx[mask], self.ry[mask], self.rz[mask]
