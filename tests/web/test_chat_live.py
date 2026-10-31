"""The chat with a real model on the probe lot (data/probe, simulated; documents read by the mocked
model). Needs GOOGLE_API_KEY; run with `pytest -m live`. Not a quality measure: it checks the model calls
the tools, proposes instead of confirming, and quotes only the tools' numbers."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.llm.client import api_keys, load_env
from src.web.service.app import chat_model
from tests.web.support import JSON, ORIGIN, login, make_app
from tests.web.test_chat import say
from tests.web.test_history import FakeLLM, read_lot

load_env(Path(__file__).resolve().parents[2] / ".env")
pytestmark = [pytest.mark.live, pytest.mark.skipif(not api_keys(), reason="needs GOOGLE_API_KEY")]


def test_a_real_model_asks_proposes_and_quotes_only_tool_numbers(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path, monkeypatch, llm=FakeLLM, chat_llm=chat_model)
    c = TestClient(app, base_url=ORIGIN, headers=JSON)
    assert login(c).status_code == 200
    lot = read_lot(c)

    events = say(c, lot["id"], "Lô này còn những câu hỏi nào cần mình trả lời?")
    assert events[-1]["type"] == "message", events[-1]
    assert any("câu hỏi đang chờ" in e.get("text", "") for e in events if e["type"] == "action")
    assert events[-1]["unverified"] == []

    events = say(c, lot["id"], "SKU-B thì lấy khối lượng cả bì theo spec nhé.")
    proposals = [e for e in events if e["type"] == "proposal"]
    assert proposals and proposals[0]["point_id"] == 4 and proposals[0]["label"] == "26 kg"
    after = c.get(f"/api/lots/{lot['id']}").json()
    assert after["rev"] == lot["rev"]  # nothing confirmed by the model
