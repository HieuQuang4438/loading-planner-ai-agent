"""The ground-grid shader exists twice: shared/groundgrid.js for the viewer and an inline copy in service/static/login.html
(the login page may load nothing but style.css from the app). The vertex shader and the line() function, which make the
anti-aliased 1 m / 5 m lines, must stay identical; the colours, the fade distances and the alpha are the login panel's own."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "web"
GROUND = (ROOT / "static" / "shared" / "groundgrid.js").read_text(encoding="utf-8")
LOGIN = (ROOT / "service" / "static" / "login.html").read_text(encoding="utf-8")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def vertex(source: str) -> str:
    m = re.search(r"vertexShader:\s*(?:`|')(.*?)(?:`|')\s*,", source, re.S)
    assert m, "vertex shader not found"
    return flat(m.group(1))


def line_function(source: str) -> str:
    m = re.search(r"float line\(vec2 p, float (?:size|s)\)\s*\{.*?\}", source, re.S)
    assert m, "line() not found"
    return flat(m.group(0).replace("float size", "float s").replace("p / size", "p / s"))


def test_vertex_shaders_are_identical():
    assert vertex(GROUND) == vertex(LOGIN)


def test_line_function_is_identical():
    assert line_function(GROUND) == line_function(LOGIN)


def test_both_fade_with_the_camera_distance_on_the_ground_plane():
    for source in (GROUND, LOGIN):
        flat_source = flat(source)
        assert "smoothstep(" in flat_source and "distance(uCam.xz, " in flat_source
        assert re.search(r"line\(p, 1\.0\)|line\(vWorld\.xz, 1\.0\)", flat_source) and re.search(r"line\(p, 5\.0\)|line\(vWorld\.xz, 5\.0\)", flat_source), "1 m and 5 m lines"
