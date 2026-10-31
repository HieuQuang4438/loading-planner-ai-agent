"""The decoration of the solving screen: static/shared/fillart.js is run with `node`. It must stay decoration: hidden
from assistive tech and with no number that could read as progress."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FILLART_JS = Path(__file__).resolve().parents[2] / "src" / "web" / "static" / "shared" / "fillart.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = """
import { pathToFileURL } from 'node:url';
const r = await import(pathToFileURL(process.argv[2]).href);
console.log(JSON.stringify({ svg: r.fillArtSvg(), boxes: r.FILL_BOXES.length }));
"""


def test_art_is_a_hidden_looping_set_of_boxes(tmp_path):
    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    done = subprocess.run([NODE, str(driver), str(FILLART_JS)], capture_output=True, text=True, check=True, timeout=30)
    import json

    out = json.loads(done.stdout)
    svg = out["svg"]
    assert 'aria-hidden="true"' in svg and "<text" not in svg, "decoration only: hidden, no text"
    assert svg.count('class="bx ') == out["boxes"] == 11
    assert svg.count("<g ") == svg.count("</g>")
    assert "NaN" not in svg
