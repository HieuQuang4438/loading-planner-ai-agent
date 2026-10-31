"""Tests for the chat of a lot with a scripted model: tools run by the backend, proposals that change nothing
until the user clicks, what-if copies, runs explained with the engine's numbers, and numbers from nowhere flagged."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from src.agent.chat import unverified
from tests.web.support import JSON, ORIGIN, login, make_app
from tests.web.test_history import FakeLLM, answer_all, read_lot


class ScriptedChat:
    """Each turn: the tool calls of the script's next step, then its reply. A reply may be a function of the tool
    results, to quote them."""

    def __init__(self) -> None:
        self.turns: list[tuple[list[tuple[str, dict]], object]] = []
        self.seen: list[list[tuple[str, str]]] = []
        self.results: list[dict] = []

    def then(self, calls, reply):
        self.turns.append((calls, reply))
        return self

    def converse(self, system, history, tools, call, max_steps):
        assert "Không tự chọn" in system and {t.name for t in tools} >= {"get_lot", "propose_answer", "run_mode_a"}
        self.seen.append(history)
        calls, reply = self.turns.pop(0)
        results = [call(name, args) for name, args in calls]
        self.results += results
        return reply(results) if callable(reply) else reply


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    script = ScriptedChat()
    app, _ = make_app(tmp_path, monkeypatch, names=("alice", "bob"), llm=FakeLLM, chat_llm=lambda: script)
    c = TestClient(app, base_url=ORIGIN, headers=JSON)
    assert login(c).status_code == 200
    return c, script, app


def say(c, lot_id, text):
    r = c.post(f"/api/lots/{lot_id}/chat", json={"text": text})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


# --- numbers ---------------------------------------------------------------------------------------------------------


def test_numbers_in_a_reply_must_come_from_the_tools_read_either_way():
    sources = ['{"total_cost": "4 600,00 USD", "volume_used": "86,4 %", "mass_kg": 3790}']
    assert unverified("Tổng cước 4 600,00 USD, dùng 86,4 % thể tích, 3 790 kg.", sources) == []
    assert unverified("Tổng cước 4,600 USD, khoảng 86 %.", sources) == []  # the other marks, rounded
    assert unverified("Tiết kiệm 1 200 USD so với 2 container.", sources) == ["1 200"]  # single digits aside


# --- turns ---------------------------------------------------------------------------------------------------------


def test_an_answer_in_words_is_a_proposal_until_the_user_clicks(setup):
    c, script, _ = setup
    lot = read_lot(c)
    script.then([("list_points", {}), ("propose_answer", {"point_id": 4, "choice": 0})],
                "Mình đề xuất 26 kg cho SKU-B; bấm Xác nhận nếu đúng.")
    events = say(c, lot["id"], "SKU-B lấy theo spec nhé")
    kinds = [e["type"] for e in events]
    assert kinds == ["action", "proposal", "action", "message"]
    proposal = events[1]
    assert (proposal["point_id"], proposal["choice"], proposal["label"]) == (4, 0, "26 kg")
    after = c.get(f"/api/lots/{lot['id']}").json()
    assert after["rev"] == lot["rev"] and next(p for p in after["lot"]["points"] if p["id"] == 4)["resolved_at"] is None
    clicked = c.post(f"/api/lots/{lot['id']}/points/4", json={"rev": after["rev"], "choice": proposal["choice"]})
    assert clicked.status_code == 200


def test_a_proposal_the_lot_cannot_take_is_an_error_for_the_model(setup):
    c, script, _ = setup
    lot = read_lot(c)
    script.then([("propose_answer", {"point_id": 4, "values": {"SKU-B.mass": -3}})], "Giá trị đó không hợp lệ.")
    events = say(c, lot["id"], "SKU-B nặng âm 3 kg")
    assert "proposal" not in [e["type"] for e in events] and script.results[0]["ok"] is False


CUBE = {"sku": "SKU-AA", "qty": 3, "dims": {"L": 100, "W": 100, "H": 100}, "dims_unit": "cm", "mass": 10,
        "posture": "upright", "stacking": {"kind": "free"}, "fragile": False}


def test_a_row_said_in_words_is_a_proposal_in_metres_until_the_user_clicks(setup):
    c, script, _ = setup
    lot = read_lot(c)
    script.then([("propose_add_line", CUBE)], "Mình đề xuất thêm SKU-AA; bấm Xác nhận nếu đúng.")
    events = say(c, lot["id"], "thêm 1 mã hàng: SKU-AA, 3 thùng, lập phương cạnh 1m, 10kg/thùng, chỉ đứng")
    proposal = next(e for e in events if e["type"] == "proposal")
    assert proposal["kind"] == "add_line" and proposal["body"]["values"]["dims"] == {"L": 1.0, "W": 1.0, "H": 1.0}
    assert proposal["label"] == "Thêm SKU-AA: 3 thùng · 1,00 × 1,00 × 1,00 m · 10 kg · chỉ đứng · chồng tự do · không dễ vỡ"
    after = c.get(f"/api/lots/{lot['id']}").json()
    assert after["rev"] == lot["rev"] and "SKU-AA" not in [x["sku"] for x in after["lot"]["lines"]]
    clicked = c.post(f"/api/lots/{lot['id']}/lines", json={**proposal["body"], "rev": after["rev"]})
    assert clicked.status_code == 201 and "SKU-AA" in [x["sku"] for x in clicked.json()["lot"]["lines"]]


@pytest.mark.parametrize("change", [{"posture": None}, {"dims_unit": None}, {"sku": "SKU-A"}, {"qty": 0}])
def test_a_row_missing_a_field_or_a_code_the_lot_has_is_an_error_for_the_model(setup, change):
    c, script, _ = setup
    lot = read_lot(c)
    script.then([("propose_add_line", {k: v for k, v in {**CUBE, **change}.items() if v is not None})], "Thiếu.")
    events = say(c, lot["id"], "thêm SKU-AA")
    assert "proposal" not in [e["type"] for e in events] and script.results[0]["ok"] is False


def test_a_change_to_a_row_is_a_proposal_and_a_field_a_question_holds_is_not(setup):
    c, script, _ = setup
    lot = read_lot(c)
    asked = {f for p in lot["lot"]["points"] if p["resolved_at"] is None for f in p["fields"]}
    free = next(f"{x['id']}.dims" for x in lot["lot"]["lines"] if f"{x['id']}.dims" not in asked)
    held = sorted(asked)[0]
    line_id = free.rsplit(".", 1)[0]
    script.then([("propose_edit_line", {"line_id": line_id, "dims": {"L": 500, "W": 400, "H": 300}, "dims_unit": "mm"}),
                 ("propose_edit_line", {"line_id": held.rsplit(".", 1)[0], held.rsplit(".", 1)[1]: 1})], "Đã đề xuất.")
    events = say(c, lot["id"], "đổi kích thước")
    proposals = [e for e in events if e["type"] == "proposal"]
    assert len(proposals) == 1 and proposals[0]["label"] == f"Sửa {line_id}: 0,50 × 0,40 × 0,30 m"
    assert script.results[1]["ok"] is False and "câu hỏi H" in script.results[1]["error"]
    after = c.get(f"/api/lots/{lot['id']}").json()
    clicked = c.post(f"/api/lots/{lot['id']}/lines/{line_id}", json={**proposals[0]["body"], "rev": after["rev"]})
    line = next(x for x in clicked.json()["lot"]["lines"] if x["id"] == line_id)
    assert clicked.status_code == 200 and line["dims"]["value"] == {"L": 0.5, "W": 0.4, "H": 0.3}


def test_the_conversation_is_kept_with_the_lot_and_sent_back(setup):
    c, script, app = setup
    lot = read_lot(c)
    script.then([], "Chào bạn.").then([], "Lô có 5 dòng.")
    say(c, lot["id"], "chào")
    say(c, lot["id"], "lô có mấy dòng?")
    assert script.seen[1] == [("user", "chào"), ("model", "Chào bạn."), ("user", "lô có mấy dòng?")]
    kept = c.get(f"/api/lots/{lot['id']}/chat").json()
    assert [(m["role"], m["content"]["text"]) for m in kept][-1] == ("assistant", "Lô có 5 dòng.")
    bob = TestClient(app, base_url=ORIGIN, headers=JSON)
    login(bob, "bob")
    assert bob.post(f"/api/lots/{lot['id']}/chat", json={"text": "hi"}).status_code == 404


def test_a_number_from_nowhere_is_asked_again_then_flagged(setup):
    c, script, _ = setup
    lot = read_lot(c)
    script.then([("get_lot", {})], "Lô nặng 9 999 kg.").then([], "Lô nặng 9 999 kg.")
    events = say(c, lot["id"], "lô nặng bao nhiêu?")
    assert events[-1]["type"] == "message" and events[-1]["unverified"] == ["9 999"]
    assert "9 999" in script.seen[1][-1][1]  # the second call was told which number


def test_what_if_makes_a_copy_and_leaves_the_lot(setup):
    c, script, _ = setup
    lot = read_lot(c)
    script.then([("make_variant", {"note": "bỏ SKU-B, thêm SKU-C", "drop_skus": ["SKU-B"],
                                   "qty": [{"line_id": "SKU-C", "qty": 60}]})], "Đã tạo bản lô mới.")
    events = say(c, lot["id"], "bỏ SKU-B và SKU-C thành 60 thùng")
    made = next(e for e in events if e["type"] == "lot")
    copy = c.get(f"/api/lots/{made['lot_id']}").json()
    assert copy["parent_id"] == lot["id"] and "yêu cầu trong chat" in copy["note"]
    assert "SKU-B" not in [x["sku"] for x in copy["lot"]["lines"]]
    point = next(p for p in copy["lot"]["points"] if p["fields"] == ["SKU-C.qty"])
    assert [o["label"] for o in point["options"]] == ["50 thùng", "60 thùng"]  # documents' 50, the chat's 60: user picks
    original = c.get(f"/api/lots/{lot['id']}").json()
    assert original["rev"] == lot["rev"] and len(original["lot"]["lines"]) == 5


def test_a_run_is_started_and_explained_with_the_engines_numbers(setup):
    c, script, _ = setup
    lot = answer_all(c, read_lot(c))
    script.then([("run_mode_a", {"time_limit_s": 10})], "Đang chạy.")  # the shortest limit the service takes: the test waits for the run
    events = say(c, lot["id"], "chạy tối ưu cước")
    job_id = next(e for e in events if e["type"] == "run")["job_id"]
    end = time.monotonic() + 120
    while c.get(f"/api/jobs/{job_id}").json()["status"] in ("queued", "running"):
        assert time.monotonic() < end
        time.sleep(0.2)
    script.then([("get_run", {})], lambda results: f"Tổng cước {results[0]['total_cost']}.")
    events = say(c, lot["id"], "kết quả thế nào?")
    run = script.results[-1]
    assert run["check_ok"] and run["pieces_placed"] == run["pieces_total"] == 380
    assert run["total_cost"].endswith(" USD") and events[-1]["unverified"] == []
