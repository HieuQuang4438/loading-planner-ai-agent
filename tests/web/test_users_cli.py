"""Tests for the account CLI (`python -m src.web.users`, docs/product/architecture.md §5, §9)."""
from __future__ import annotations

import pytest

from src.web import db as webdb
from src.web import users
from src.web.auth import hash_password

PASSWORD = "correct horse battery"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    monkeypatch.setenv("PLANNER_DB", str(path))
    for var in ("PLANNER_ADMIN_NAME", "PLANNER_ADMIN_PASSWORD", "PLANNER_NEW_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return path


def rows(path, sql="SELECT name, active, pw_hash FROM users ORDER BY id"):
    conn = webdb.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_seed_creates_admin_once(db_path, monkeypatch, capsys):
    monkeypatch.setenv("PLANNER_ADMIN_NAME", "admin")
    monkeypatch.setenv("PLANNER_ADMIN_PASSWORD", PASSWORD)
    assert users.main(["seed"]) == 0
    (first,) = rows(db_path)
    monkeypatch.setenv("PLANNER_ADMIN_PASSWORD", "another password 123")
    assert users.main(["seed"]) == 0  # idempotent: the existing user is untouched
    (second,) = rows(db_path)
    assert first["pw_hash"] == second["pw_hash"] and first["pw_hash"].startswith("$argon2id$")
    assert "đã có" in capsys.readouterr().out


def test_seed_needs_env(db_path, capsys):
    assert users.main(["seed"]) == 1
    assert "PLANNER_ADMIN_NAME" in capsys.readouterr().err


def test_add_reads_password_from_env_or_prompt(db_path, monkeypatch):
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", PASSWORD)
    assert users.main(["add", "bob"]) == 0
    monkeypatch.delenv("PLANNER_NEW_PASSWORD")
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(users.getpass, "getpass", lambda prompt="": next(answers))
    assert users.main(["add", "carol"]) == 0
    assert [r["name"] for r in rows(db_path)] == ["bob", "carol"]


def test_prompt_mismatch_is_refused(db_path, monkeypatch):
    answers = iter([PASSWORD, PASSWORD + "x"])
    monkeypatch.setattr(users.getpass, "getpass", lambda prompt="": next(answers))
    assert users.main(["add", "bob"]) == 1
    assert rows(db_path) == []


@pytest.mark.parametrize("name", ["Bob", "bo b", "bob!", "", "bób"])
def test_bad_name_is_refused(db_path, monkeypatch, name):
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", PASSWORD)
    assert users.main(["add", name]) == 1
    assert rows(db_path) == []


def test_short_password_is_refused(db_path, monkeypatch):
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", "x" * 11)
    assert users.main(["add", "bob"]) == 1
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", "x" * 12)
    assert users.main(["add", "bob"]) == 0
    assert users.main(["add", "bob"]) == 1  # duplicate


def test_passwd_changes_hash_and_ends_sessions(db_path, monkeypatch):
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", PASSWORD)
    users.main(["add", "bob"])
    conn = webdb.connect(db_path)
    conn.execute("INSERT INTO sessions VALUES ('h', 1, '2999-01-01')")
    conn.close()
    before = rows(db_path)[0]["pw_hash"]
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", "a brand new password")
    assert users.main(["passwd", "bob"]) == 0
    assert rows(db_path)[0]["pw_hash"] != before
    assert rows(db_path, "SELECT * FROM sessions") == []
    assert users.main(["passwd", "ghost"]) == 1


def test_disable_and_list(db_path, monkeypatch, capsys):
    monkeypatch.setenv("PLANNER_NEW_PASSWORD", PASSWORD)
    users.main(["add", "bob"])
    assert users.main(["disable", "bob"]) == 0
    assert rows(db_path)[0]["active"] == 0
    assert users.main(["disable", "ghost"]) == 1
    capsys.readouterr()
    assert users.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "bob\tdisabled" in out and PASSWORD not in out and "argon2" not in out


def test_password_is_never_an_argument(db_path):
    with pytest.raises(SystemExit):
        users.main(["add", "bob", PASSWORD])


def test_hash_password_is_argon2id():
    assert hash_password(PASSWORD).startswith("$argon2id$")
