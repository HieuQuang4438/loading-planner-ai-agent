"""E2b = block building over maximal spaces. `solve` is
registered under `src.engines.base` as `"e2b"` by `src.engines` (the built-in registry), not here.
"""
from __future__ import annotations

from src.engines.e2b.engine import pack_one, solve

__all__ = ["solve", "pack_one"]
