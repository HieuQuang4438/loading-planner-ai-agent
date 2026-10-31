"""Tests for the configuration of the web (src.web.mode, `/api/config`, `python -m src.web`)."""
from __future__ import annotations

import pytest

from src import web
from src.engines import base
from src.web import __main__ as web_main
from src.web.mode import ENGINE_TITLES, FILL_ENGINES, SERVICE, SERVICE_ENGINES, default_time_limit, engine_entries
from tests.web.support import logged_in


@pytest.fixture()
def service(tmp_path, monkeypatch):
    return logged_in(tmp_path, monkeypatch)


def test_service_engines_are_registered():
    assert set(SERVICE_ENGINES) <= set(base.names())


def test_config_lists_only_the_service_engines(service):
    config = service.get("/api/config").json()

    assert config["mode"] == "service"
    assert [e["name"] for e in config["engines"]] == sorted(SERVICE_ENGINES + FILL_ENGINES)
    assert config["defaults"]["time_limit"] == 60.0  # before the lot's size is known
    assert config["size_time_limits"] == [  # the page reads the thresholds here
        {"name": "small", "max_containers": 4, "seconds": 60.0},
        {"name": "medium", "max_containers": 20, "seconds": 60.0},
        {"name": "large", "max_containers": None, "seconds": 120.0}]
    assert "cost_tables" not in config  # the costs come with the lot


@pytest.mark.parametrize(("fleet", "seconds"), [(0, 60.0), (1, 60.0), (4, 60.0), (5, 60.0), (20, 60.0), (21, 120.0), (58, 120.0)])
def test_default_time_limit_thresholds(fleet, seconds):
    assert default_time_limit(fleet) == seconds  # small <= 4, medium 5-20, large > 20


def test_main_runs_the_app_on_localhost(monkeypatch):
    seen = {}
    monkeypatch.setattr(web_main.uvicorn, "run", lambda app, host, port: seen.update(title=app.title, host=host))
    monkeypatch.setattr("src.web.service.app.AuthConfig.from_env", lambda: web.auth.AuthConfig(":memory:", ()))

    assert web_main.main([]) == 0
    assert seen == {"title": "Loading AI Planner", "host": "127.0.0.1"}


def test_every_engine_entry_has_a_title_and_a_description(service):
    entries = engine_entries(SERVICE)
    assert entries and all(e["description"].strip() for e in entries)
    assert set(base.names()) <= set(ENGINE_TITLES)
    assert all(e["description"] for e in service.get("/api/config").json()["engines"])
