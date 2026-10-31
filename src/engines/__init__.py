"""Engine registry: the engines the product runs (docs/product/brief.md §2.2).

Importing this package registers them by name under `src.engines.base`. Only E5's default version is
registered, with and without the orientation option, plus mode B's `e5-fill`.
"""
from __future__ import annotations

from src.engines import base, e5, fill

base.register("e5", e5.solve, start=True)  # the default version: minimum total cost over the container table
base.register("e5-orient", e5.solve_orient, start=True)  # the same, free to tip items that allow it
base.register("e5-fill", fill.solve)  # mode B: most pieces by priority into the containers at hand (ADR-0002)
base.register("e5-fill-orient", fill.solve_orient)

__all__ = ["base"]
