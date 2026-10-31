"""One rounding per quantity on every screen (ui.md §2): static/shared/util.js `fmtDim`, `fmtKg`, `fmtRatio` run with `node`."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
UTIL_JS = Path(__file__).resolve().parents[2] / "src" / "web" / "static" / "shared" / "util.js"
DRIVER = """
import { pathToFileURL } from 'node:url';
const u = await import(pathToFileURL(process.argv[2]).href);
console.log(JSON.stringify({ dim: [0.7, 14, 2.345, null].map(u.fmtDim), kg: [285, 0.25, 28000, 95.44, null].map(u.fmtKg), ratio: [2, 1.9999, 2.004].map(u.fmtRatio) }));
"""


def test_sizes_have_two_decimals_masses_one_and_ratios_two(tmp_path):
    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    done = subprocess.run([NODE, str(driver), str(UTIL_JS)], capture_output=True, text=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert got["dim"] == ["0,70", "14,00", "2,35", "—"]   # 2.345 rounds as toFixed does
    assert got["kg"] == ["285,0", "0,3", "28 000,0", "95,4", "—"]
    assert got["ratio"] == ["2,00", "2,00", "2,00"]
