"""Shared by the web tests: the sample lots (simulated sizes and masses), and an
app with login on (always on here) and one user logged in."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.formats import instance_to_dict, read_instance
from src.web import db as webdb
from src.web import users
from src.web.service.app import create_app

SAMPLES_DIR = Path(__file__).parent / "samples"
ORIGIN = "https://planner.example.org"
PASSWORD = "correct horse battery"
JSON = {"Origin": ORIGIN}


def sample_path(name: str) -> Path:
    return SAMPLES_DIR / f"{name}.json"


def small_lot() -> dict:
    return instance_to_dict(read_instance(sample_path("sample-small")))


def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, seed: bool = True, names: tuple[str, ...] = ("alice",),
             llm=None, chat_llm=None):
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("PLANNER_DB", str(db_path))
    monkeypatch.setenv("PLANNER_ORIGINS", f"{ORIGIN}, http://planner.example.org")
    if seed:
        conn = webdb.connect(db_path)
        webdb.migrate(conn)
        for name in names:
            users.add_user(conn, name, PASSWORD)
        conn.close()
    models = {k: v for k, v in {"llm": llm, "chat_llm": chat_llm}.items() if v is not None}
    return create_app(**models), db_path


def login(client: TestClient, name: str = "alice", password: str = PASSWORD):
    return client.post("/api/login", json={"name": name, "password": password}, headers=JSON)


def logged_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "alice", llm=None) -> TestClient:
    """A client of a fresh app, logged in as `name`; it sends the allowed Origin on every request. `llm`: what makes
    the model client (default: Gemini)."""
    app, _ = make_app(tmp_path, monkeypatch, names=("alice", "bob"), llm=llm)
    client = TestClient(app, base_url=ORIGIN, headers=JSON)
    assert login(client, name).status_code == 200
    return client
