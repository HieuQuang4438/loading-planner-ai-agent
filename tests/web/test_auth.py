"""Tests for the login (src.web.auth, src.web.db), always on in this app; a database file in
`tmp_path`."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.web import db as webdb
from src.web import users
from src.web.auth import COOKIE, MAX_FAILURES
from src.web.service.app import create_app

ORIGIN = "https://planner.example.org"
PASSWORD = "correct horse battery"
JSON = {"Origin": ORIGIN}


def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, seed: bool = True):
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("PLANNER_DB", str(db_path))
    monkeypatch.setenv("PLANNER_ORIGINS", f"{ORIGIN}, http://planner.example.org")
    if seed:
        conn = webdb.connect(db_path)
        webdb.migrate(conn)
        users.add_user(conn, "alice", PASSWORD)
        conn.close()
    return create_app(), db_path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    app, db_path = make_app(tmp_path, monkeypatch)
    return TestClient(app, base_url=ORIGIN), db_path, app


def login(client: TestClient, name: str = "alice", password: str = PASSWORD):
    return client.post("/api/login", json={"name": name, "password": password}, headers=JSON)


def query(db_path: Path, sql: str, *args):
    conn = webdb.connect(db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_unauthenticated_every_route_is_401(env):
    client, _, app = env
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in ("/login", "/healthz", "/api/login"):
            continue
        path = route.path.replace("{job_id}", "abc")
        for method in route.methods:
            res = client.request(method, path, headers=JSON, follow_redirects=False)
            if (method, path) == ("GET", "/"):  # the page redirects instead
                assert res.status_code == 303
                continue
            assert res.status_code == 401, (method, path)
            assert res.json()["code"] == "unauthorized"


def test_unauthenticated_unknown_and_static_paths_are_401(env):
    client, _, _ = env
    for path in ("/nope", "/api/nope", "/static/shared/state.js", "/static/nope", "/docs", "/openapi.json"):
        res = client.get(path)
        assert res.status_code == 401 and res.json()["code"] == "unauthorized", path


def test_public_routes_need_no_session(env):
    client, _, _ = env
    assert client.get("/healthz").json() == {"status": "ok"}
    page = client.get("/login")
    assert page.status_code == 200 and "Đăng nhập" in page.text
    assert client.get("/static/shared/style.css").status_code == 200
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 303 and root.headers["location"] == "/login"


def test_login_page_loads_nothing_from_the_app_but_the_stylesheet(env):
    """/login is served without a session (P1): a second app file in it would be a 401 and a broken page."""
    import re

    client, _, _ = env
    page = client.get("/login").text
    local = set(re.findall(r"""(?:src|href)=["'](/[^"']*)""", page)) | set(re.findall(r"""['"](/static/[^'"]*)""", page))
    assert len(local) == 1 and re.fullmatch(r"/static/[0-9a-f]{12}/shared/style\.css", next(iter(local))), local
    for ident in ("name", "password", "submit", "error"):
        assert f'id="{ident}"' in page
    assert "Chưa có tài khoản hoặc quên mật khẩu? Liên hệ người quản trị." in page
    assert "https://cdn.jsdelivr.net/npm/three@0.160.0/" in page   # same three.js as index.html, pinned
    assert "visibilitychange" in page and "prefers-reduced-motion" in page   # the loop stops when hidden; still when reduced


def test_login_gives_session_and_logout_ends_it(env):
    client, db_path, _ = env
    res = login(client)
    assert res.status_code == 200 and res.json() == {"name": "alice"}
    assert client.get("/api/me").json() == {"name": "alice"}
    assert client.get("/api/config").status_code == 200
    assert client.get("/").status_code == 200
    assert client.post("/api/lots/validate", json={}, headers=JSON).status_code == 200
    assert client.post("/api/logout", headers=JSON).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert query(db_path, "SELECT * FROM sessions") == []


def test_login_name_is_case_and_space_insensitive(env):
    client, _, _ = env
    assert login(client, name="  Alice ").status_code == 200


def test_same_message_for_unknown_name_and_wrong_password(env):
    client, _, _ = env
    a = login(client, name="nobody")
    b = login(client, password="x" * 20)
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() and a.json()["code"] == "unauthorized"


def test_expired_session_is_401(env):
    client, db_path, _ = env
    login(client)
    conn = webdb.connect(db_path)
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00.000000Z'")
    conn.close()
    assert client.get("/api/me").status_code == 401


def test_session_lasts_twelve_hours_from_login(env):
    client, db_path, _ = env
    login(client)
    (row,) = query(db_path, "SELECT (julianday(expires_at) - julianday('now')) * 24 AS hours FROM sessions")
    assert 11.9 < row["hours"] < 12.1


def test_disabled_user_loses_session_and_cannot_login(env):
    client, db_path, _ = env
    login(client)
    conn = webdb.connect(db_path)
    users.disable_user(conn, "alice")
    conn.close()
    assert client.get("/api/me").status_code == 401
    assert login(client).status_code == 401


def test_five_failures_lock_the_name(env):
    client, db_path, _ = env
    for _ in range(MAX_FAILURES):
        assert login(client, password="wrong-password-1").status_code == 401
    locked = login(client)  # the right password is refused too, with the same message
    assert locked.status_code == 401 and locked.json()["message"] == login(client, name="nobody").json()["message"]
    assert len(query(db_path, "SELECT * FROM login_failures WHERE name = 'alice'")) == MAX_FAILURES  # the attempt while locked is not counted
    conn = webdb.connect(db_path)  # 20 minutes later
    conn.execute("UPDATE login_failures SET at = strftime('%Y-%m-%dT%H:%M:%S.000000Z', 'now', '-20 minutes')")
    conn.close()
    assert login(client).status_code == 200


def test_four_failures_do_not_lock_and_success_clears_them(env):
    client, db_path, _ = env
    for _ in range(MAX_FAILURES - 1):
        login(client, password="wrong-password-1")
    assert login(client).status_code == 200
    assert query(db_path, "SELECT * FROM login_failures WHERE name = 'alice'") == []


def test_lockout_is_per_name(env):
    client, _, _ = env
    for _ in range(MAX_FAILURES):
        login(client, name="mallory", password="wrong-password-1")
    assert login(client).status_code == 200


def test_state_change_needs_an_allowed_origin(env):
    client, _, _ = env
    login(client)
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
        res = client.post("/api/lots/validate", json={}, headers=headers)
        assert res.status_code == 403 and res.json()["code"] == "forbidden", headers
    # the Host header is not the source of truth: a request claiming that host and origin is still refused
    res = client.post("/api/lots/validate", json={}, headers={"Host": "evil.example", "Origin": "https://evil.example"})
    assert res.status_code == 403
    res = client.post("/api/lots/validate", json={}, headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example",
                                                              "Origin": "https://evil.example"})
    assert res.status_code == 403
    assert client.post("/api/lots/validate", json={}, headers=JSON).status_code == 200
    assert client.post("/api/lots/validate", json={}, headers={"Origin": ORIGIN + "/"}).status_code == 200


def test_login_itself_checks_origin(env):
    client, _, _ = env
    res = client.post("/api/login", json={"name": "alice", "password": PASSWORD})
    assert res.status_code == 403
    res = client.post("/api/login", json={"name": "alice", "password": PASSWORD}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


def test_empty_origins_refuses_every_post(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path, monkeypatch)
    monkeypatch.setenv("PLANNER_ORIGINS", "")
    client = TestClient(create_app(), base_url=ORIGIN)
    assert login(client).status_code == 403


def test_state_change_with_a_body_must_be_json(env):
    client, _, _ = env
    login(client)
    res = client.post("/api/lots/validate", content=b"{}", headers={**JSON, "Content-Type": "text/plain"})
    assert res.status_code == 403 and res.json()["code"] == "forbidden"
    res = client.post("/api/lots/validate", content=b"a=b", headers={**JSON, "Content-Type": "application/x-www-form-urlencoded"})
    assert res.status_code == 403
    assert client.post("/api/logout", headers=JSON).status_code == 200  # no body: no content type needed


def test_cookie_flags_and_secure_even_over_http(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path, monkeypatch)
    client = TestClient(app, base_url="http://planner.example.org")
    res = client.post("/api/login", json={"name": "alice", "password": PASSWORD}, headers={"Origin": "http://planner.example.org"})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    for flag in (f"{COOKIE}=", "httponly", "secure", "samesite=strict", "path=/"):
        assert flag in cookie, flag


def test_no_plaintext_password_or_token_stored_or_logged(env, caplog):
    client, db_path, _ = env
    caplog.set_level(logging.DEBUG)
    login(client, password="wrong-password-1")
    login(client)
    token = client.cookies.get(COOKIE)
    assert token
    conn = webdb.connect(db_path)
    dump = "\n".join(conn.iterdump())
    conn.close()
    raw = b"".join(p.read_bytes() for p in db_path.parent.glob("app.db*"))
    for secret in (PASSWORD, "wrong-password-1", token):
        assert secret not in dump and secret.encode() not in raw
        assert secret not in caplog.text
    (row,) = query(db_path, "SELECT pw_hash FROM users")
    assert row["pw_hash"].startswith("$argon2id$")


def test_empty_users_table_warns_at_startup(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    make_app(tmp_path, monkeypatch, seed=False)
    assert "users table is empty" in caplog.text


def test_migrations_are_idempotent_and_appendable(tmp_path, monkeypatch):
    conn = webdb.connect(tmp_path / "m.db")
    webdb.migrate(conn)
    webdb.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(webdb.MIGRATIONS)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    before = len(webdb.MIGRATIONS)
    monkeypatch.setattr(webdb, "MIGRATIONS", [*webdb.MIGRATIONS, "CREATE TABLE extra (id TEXT PRIMARY KEY);"])
    webdb.migrate(conn)
    webdb.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before + 1
    conn.execute("SELECT * FROM extra")
    conn.close()


def test_deleting_a_user_deletes_the_sessions(env):
    client, db_path, _ = env
    login(client)
    conn = webdb.connect(db_path)
    conn.execute("DELETE FROM users")
    conn.close()
    assert query(db_path, "SELECT * FROM sessions") == []
    assert client.get("/api/me").status_code == 401
    with pytest.raises(sqlite3.Error):
        webdb.connect(db_path).execute("INSERT INTO sessions VALUES ('h', 99, 'x')")
