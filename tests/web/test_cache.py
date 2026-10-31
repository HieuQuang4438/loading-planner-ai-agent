"""Tests for the cache policy of the page and static files (src.web.api.new_app). Login is
always on, so every client but the anonymous one logs in."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from src.web.assets import SHARED_STATIC, shared_version
from tests.web.support import ORIGIN, logged_in, make_app

ASSETS = ("/", "/static/shared/style.css", "/static/shared/util.js")


def test_assets_revalidate(tmp_path, monkeypatch):
    client = logged_in(tmp_path, monkeypatch)
    for path in ASSETS:
        assert client.get(path).headers["cache-control"] == "no-cache", path
    assert client.get("/login").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/config").headers
    anonymous = TestClient(client.app)
    refused = anonymous.get("/static/shared/util.js")
    assert refused.status_code == 401 and refused.headers["cache-control"] == "no-cache"
    assert "cache-control" not in anonymous.get("/api/me").headers


def test_unchanged_static_file_answers_304(tmp_path, monkeypatch):
    client = logged_in(tmp_path, monkeypatch)
    first = client.get("/static/shared/util.js")
    assert first.status_code == 200 and first.headers["etag"]
    again = client.get("/static/shared/util.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"


# ---- versioned shared files ----
BARE = "/static/shared/"
VERSIONED = re.compile(r"/static/([0-9a-f]{12})/shared/")
IMMUTABLE = "public, max-age=31536000, immutable"


def test_the_page_points_at_the_versioned_copy(tmp_path, monkeypatch):
    client = logged_in(tmp_path, monkeypatch)
    page = client.get("/")
    assert BARE not in page.text and VERSIONED.search(page.text)
    assert page.headers["cache-control"] == "no-cache"
    assert page.headers["content-type"].startswith("text/html")
    version = VERSIONED.search(page.text).group(1)
    assert version == shared_version()
    res = client.get(f"/static/{version}/shared/util.js")
    assert res.status_code == 200 and res.headers["cache-control"] == IMMUTABLE
    assert client.get("/static/shared/util.js").headers["cache-control"] == "no-cache"
    assert client.get(f"/static/{'0' * 12}/shared/util.js").status_code == 404


def test_login_page_and_versioned_css_work_without_login(tmp_path, monkeypatch):
    client = TestClient(make_app(tmp_path, monkeypatch)[0], base_url=ORIGIN)
    page = client.get("/login")
    assert BARE not in page.text and page.headers["cache-control"] == "no-cache"
    css = VERSIONED.search(page.text).group(0) + "style.css"
    res = client.get(css)
    assert res.status_code == 200 and res.headers["cache-control"] == IMMUTABLE
    assert client.get(css.replace("style.css", "util.js")).status_code == 401  # only the stylesheet is public


def test_shared_modules_import_each_other_relatively():
    for path in SHARED_STATIC.glob("*.js"):
        assert "'/static/shared/" not in path.read_text(encoding="utf-8") and '"/static/shared/' not in path.read_text(encoding="utf-8"), path.name


def test_version_follows_content(tmp_path):
    (tmp_path / "a.js").write_text("one")
    first = shared_version(tmp_path)
    assert first == shared_version(tmp_path) and re.fullmatch(r"[0-9a-f]{12}", first)
    (tmp_path / "a.js").write_text("two")
    assert shared_version(tmp_path) != first
    (tmp_path / "a.js").write_text("one")
    (tmp_path / "b.js").write_text("")
    assert shared_version(tmp_path) != first
