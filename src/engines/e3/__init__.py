"""E3 = BRKGA over E1's or E2's core. `solve_e1` and `solve_e2`
are registered under `src.engines.base` as `"e3-e1"` and `"e3-e2"` by `src.engines` (the built-in
registry), not here.
"""
from __future__ import annotations

from src.engines.e3.engine import solve, solve_e1, solve_e2

__all__ = ["solve", "solve_e1", "solve_e2"]
