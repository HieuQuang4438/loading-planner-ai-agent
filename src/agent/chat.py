"""The chat agent (docs/product/brief.md §2.1 "Gọi engine", "What-if", "Giải thích"). The model picks tools and
words the reply; the values, the plans and their check come from code (brief §2.3). It never confirms data: an answer
it understood from the user's words is a proposal the user confirms with a click (choice 2A).

Every number in a reply must be in what the tools returned this turn or in the user's own messages; a reply with a
number from nowhere is asked again once, then shown with those numbers flagged (choice 5A).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from src.llm.client import ChatLLM, Tool, prompt

MAX_STEPS = 8
HISTORY = 20  # messages sent back to the model each turn

_INT = {"type": "integer"}
_FIELDS = {  # the values of a row, as the user said them; a size in `dims_unit`, the code turns it into metres
    "qty": _INT,
    "dims": {"type": "object", "properties": {"L": {"type": "number"}, "W": {"type": "number"}, "H": {"type": "number"}}},
    "dims_unit": {"type": "string", "enum": ["m", "cm", "mm"]},
    "mass": {"type": "number"},
    "posture": {"type": "string", "enum": ["upright", "tippable"]},
    "stacking": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["free", "limited", "none"]},
                                                  "tiers": _INT}},
    "fragile": {"type": "boolean"},
}
TOOLS = [
    Tool("get_lot", "Dữ liệu lô đang mở: các dòng hàng, giá trị và trạng thái từng trường, mã bị loại, số câu hỏi còn chờ "
         "xác nhận.", {"type": "object", "properties": {}}),
    Tool("list_points", "Các câu hỏi đang chờ người dùng trả lời (mã H + `id`, ví dụ H3), mỗi câu có nội dung, các lựa chọn (đánh số từ 0) và "
         "nguồn của từng lựa chọn.", {"type": "object", "properties": {}}),
    Tool("propose_answer", "Đề xuất câu trả lời cho một câu hỏi, theo lời người dùng: một lựa chọn có sẵn "
         "(choice) hoặc giá trị người dùng nói (values, khóa '<line id>.<field>'). Không chốt gì: trang hiện nút "
         "Xác nhận để người dùng bấm.",
         {"type": "object", "properties": {"point_id": _INT, "choice": _INT,
                                           "values": {"type": "object", "additionalProperties": True}},
          "required": ["point_id"]}),
    Tool("propose_confirm_lot", "Đề xuất xác nhận phần dữ liệu còn lại của lô khi không còn câu hỏi nào mở. Không chốt "
         "gì: trang hiện nút Xác nhận.", {"type": "object", "properties": {}}),
    Tool("propose_add_line", "Đề xuất thêm một dòng hàng vào lô đang mở, theo lời người dùng: mã, đơn vị, và đủ sáu "
         "trường (qty; dims kèm dims_unit; mass kg mỗi kiện; posture upright = chỉ đứng, tippable = được lật; "
         "stacking; fragile). Trường người dùng không nói thì bỏ trống, không đoán: công cụ báo thiếu. Không chốt "
         "gì: trang hiện nút Xác nhận.",
         {"type": "object", "properties": {"sku": {"type": "string"}, "description": {"type": "string"},
                                           "unit": {"type": "string", "enum": ["carton", "pallet", "piece"]},
                                           **_FIELDS},
          "required": ["sku"]}),
    Tool("propose_edit_line", "Đề xuất sửa các trường của một dòng có sẵn (line_id), theo lời người dùng; chỉ gửi "
         "trường cần đổi. Trường đang chờ ở một câu hỏi thì dùng propose_answer. Không chốt gì: trang hiện nút "
         "Xác nhận.",
         {"type": "object", "properties": {"line_id": {"type": "string"}, **_FIELDS}, "required": ["line_id"]}),
    Tool("run_mode_a", "Chạy chế độ A (tối thiểu tổng cước) cho lô đã xác nhận đủ, với bảng cước của lô.",
         {"type": "object", "properties": {"time_limit_s": {"type": "integer", "enum": [60, 120, 300]}}}),
    Tool("run_mode_b", "Chạy chế độ B (container có sẵn, xếp nhiều hàng nhất theo thứ tự ưu tiên) cho lô đã xác nhận "
         "đủ. fleet: số container có sẵn mỗi loại theo lời người dùng, ví dụ {\"40HC\": 2}. priority: mã dòng (line "
         "id) theo thứ tự ưu tiên, bỏ trống là thứ tự trong lô. partial: cho xếp một phần một dòng (mặc định có).",
         {"type": "object", "properties": {
             "fleet": {"type": "object", "additionalProperties": _INT},
             "priority": {"type": "array", "items": {"type": "string"}},
             "partial": {"type": "boolean"},
             "time_limit_s": {"type": "integer", "enum": [60, 120, 300]}},
          "required": ["fleet"]}),
    Tool("get_run", "Kết quả một lần chạy (mặc định: lần gần nhất của lô): trạng thái, tổng cước, container theo "
         "loại, số kiện, tỷ lệ dùng thể tích và tải, kết quả kiểm tra ràng buộc, cận dưới.",
         {"type": "object", "properties": {"job_id": {"type": "string"}}}),
    Tool("compare_runs", "So hai lần chạy: chỉ số của từng lần và chênh lệch.",
         {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}),
    Tool("make_variant", "Tạo bản lô mới từ lô đang mở theo yêu cầu what-if của người dùng: bỏ mã hàng (drop_skus) "
         "hoặc đổi số lượng một dòng (qty: [{line_id, qty}]). Lô gốc giữ nguyên; số lượng mới phải được người dùng "
         "xác nhận trong bản mới.",
         {"type": "object", "properties": {
             "note": {"type": "string"},
             "drop_skus": {"type": "array", "items": {"type": "string"}},
             "qty": {"type": "array", "items": {"type": "object", "properties": {"line_id": {"type": "string"},
                                                                               "qty": _INT}}}},
          "required": ["note"]}),
]

RETRY_NOTE = ("Câu trả lời vừa rồi có số không có trong kết quả công cụ: {numbers}. Viết lại, chỉ dùng số có trong "
              "kết quả công cụ; cần số nào thì gọi công cụ.")


@dataclass
class Reply:
    text: str
    unverified: list[str] = field(default_factory=list)  # numbers of the reply found in no tool result


def respond(llm: ChatLLM, history: list[tuple[str, str]], call: Callable[[str, dict[str, Any]], dict[str, Any]]) -> Reply:
    """The agent's reply to `history` (the last message is the user's), calling tools through `call`."""
    seen: list[str] = [text for role, text in history if role == "user"]

    def recorded(name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = call(name, args)
        seen.append(json.dumps(result, ensure_ascii=False))
        return result

    text = llm.converse(prompt("chat"), history[-HISTORY:], TOOLS, recorded, MAX_STEPS)
    bad = unverified(text, seen)
    if bad:
        again = history[-HISTORY:] + [("model", text), ("user", RETRY_NOTE.format(numbers=", ".join(bad)))]
        text = llm.converse(prompt("chat"), again, TOOLS, recorded, MAX_STEPS)
        bad = unverified(text, seen)
    return Reply(text, bad)


_NUMBER = re.compile(r"\d(?:[\d.,   ]*\d)?")


def unverified(text: str, sources: list[str]) -> list[str]:
    """The numbers of `text` (single digits aside) that none of `sources` holds, read either way (`4 600,50` and
    `4,600.50` are the same) and rounded as a reply may round them (0, 1 or 2 decimals)."""
    known: set[float] = set()
    for source in sources:
        for token in _NUMBER.findall(source):
            for value in _readings(token):
                known |= {round(value, d) for d in (0, 1, 2)} | {value}
    out = []
    for token in _NUMBER.findall(text):
        values = _readings(token)
        if not values or all(v < 10 and v == int(v) for v in values):
            continue
        if not any(v in known or round(v, 2) in known for v in values):
            out.append(token.strip())
    return list(dict.fromkeys(out))


def _readings(token: str) -> set[float]:
    """What a number may mean: `,` decimal and `.`/space thousands (Vietnamese), or the other way round."""
    plain = re.sub(r"[   ]", "", token.strip())
    out = set()
    for decimal, thousands in ((",", "."), (".", ",")):
        candidate = plain.replace(thousands, "").replace(decimal, ".")
        try:
            out.add(float(candidate))
        except ValueError:
            pass
    return out
