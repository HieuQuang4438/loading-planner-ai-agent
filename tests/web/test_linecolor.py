"""Colour of an item type from its id alone (ui.md §3): static/shared/linecolor.js is run with `node`. Deleting or adding
another type must not change a type's colour, which holds when the colour is a pure function of the id."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

LINECOLOR_JS = Path(__file__).resolve().parents[2] / "src" / "web" / "static" / "shared" / "linecolor.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = """
import { pathToFileURL } from 'node:url';
const r = await import(pathToFileURL(process.argv[2]).href);
const ids = JSON.parse(process.argv[3]);
console.log(JSON.stringify(ids.map((id) => [r.lineHue(id), r.lineLightness(id), r.lineCss(id)])));
"""


@pytest.fixture(scope="module")
def colors(tmp_path_factory):
    driver = tmp_path_factory.mktemp("linecolor") / "driver.mjs"
    driver.write_text(DRIVER, encoding="utf-8")

    def run(ids: list[str]) -> dict[str, tuple[float, float, str]]:
        done = subprocess.run([NODE, str(driver), str(LINECOLOR_JS), json.dumps(ids)], capture_output=True, text=True,
                              check=True, timeout=30)
        return {i: tuple(c) for i, c in zip(ids, json.loads(done.stdout))}

    return run


def test_colour_depends_on_the_id_only(colors):
    lot = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
    full = colors(lot)
    without_l3 = colors([i for i in lot if i != "L3"])
    assert all(without_l3[i] == full[i] for i in without_l3), "deleting L3 changes no other colour"
    assert colors(["L9", *lot])["L1"] == full["L1"], "adding a type changes no colour"
    assert colors(lot[::-1]) == {i: full[i] for i in lot[::-1]}, "the order of the types does not matter"


def test_colours_are_valid_and_tell_the_sample_types_apart(colors):
    lot = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
    got = colors(lot)
    assert all(0 <= hue < 1 and 0.4 <= light <= 0.7 for hue, light, _ in got.values())
    assert len({css for _, _, css in got.values()}) == len(lot), "no two types share a colour"
