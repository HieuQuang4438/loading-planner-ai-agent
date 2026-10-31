"""The chat of a lot: `POST /api/lots/{id}/chat` streams the turn as server-sent events (one JSON object per
`data:` line): `action` (a tool the agent ran, as one line), `proposal` (an answer or "the lot is right" for the user
to confirm with a click), `lot` (a what-if copy was made), `run` (a run was queued), then `message` (the reply, with
the lot's revision so the page reloads it when it moved) or `error`. The conversation is kept with the lot.

The tools work on the session user's lots through the same code as the page (`src.web.service.lots`), so a chat and
a click give the same result (docs/product/ux.md §1)."""
from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agent.chat import respond
from src.llm.client import ChatLLM, LLMError
from src.lot.edit import add_line, edit_line
from src.lot.review import UNIT_LABEL, AnswerError, answer, fmt, refresh
from src.lot.schema import FIELD_NAMES, Excluded, LotField, Source
from src.web.api import session_owner
from src.web.errors import WebError
from src.web.job_manager import JobManager
from src.web.lotstore import LotStore
from src.web.runstore import SqliteStore
from src.web.service.lots import FillIn, start_mode_a, start_mode_b

CHAT_FILE = "chat"  # `Source.file` of a value the user gave in the chat
TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001}


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def line_values(fields: dict[str, Any]) -> dict[str, Any]:
    """The row values of a proposal, as the lines routes take them: the size turned into metres by `dims_unit`."""
    out = {n: fields[n] for n in FIELD_NAMES if fields.get(n) is not None}
    if "dims" in out:
        unit = fields.get("dims_unit")
        if unit not in TO_M:
            raise AnswerError("Thiếu đơn vị kích thước (m, cm hay mm)")
        out["dims"] = {k: round(float(v) * TO_M[unit], 6) for k, v in out["dims"].items()}
    return out


def money(x: float | None) -> str | None:
    return None if x is None else f"{x:,.2f}".replace(",", " ").replace(".", ",") + " USD"


def percent(x: float | None) -> str | None:
    return None if x is None else f"{x * 100:.1f}".replace(".", ",") + " %"


def run_summary(job_id: str, view: dict[str, Any]) -> dict[str, Any]:
    """The numbers of a run the agent may quote, already written as the screens write them."""
    containers = view["containers"]
    by_type: dict[str, int] = {}
    for c in containers:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    fill = view.get("fill")
    total = fill["total"] if fill else sum(line["qty"] for line in view["lines"])
    out = {
        "job_id": job_id,
        "check_ok": view["check"]["ok"],
        "violations": view["check"]["n_violations"],
        "total_cost": money(view["check"]["cost"]),
        "containers": len(containers),
        "containers_by_type": by_type,
        "pieces_placed": len(view["placements"]),
        "pieces_total": total,
        "lower_bound_cost": money(view["bound"]["cost"]) if view.get("bound") else None,
        "per_container": [{"k": c["k"], "type": c["type"], "cost": money(c["cost"]),
                           "pieces": sum(x["qty"] for x in c["lines"]), "volume_used": percent(c["volume_ratio"]),
                           "mass_used": percent(c["mass_ratio"]), "mass_kg": round(c["mass"])} for c in containers],
    }
    if fill:  # mode B: what the containers at hand took and left, by priority
        out |= {"mode": "b", "fleet": fill["fleet"], "partial_lines_allowed": fill["partial"],
                "by_priority": [{"line_id": x["id"], "placed": x["placed"], "total": x["qty"],
                                 "left": x["qty"] - x["placed"]} for x in fill["lines"]]}
    return out


class ChatTools:
    """The agent's tools for one turn of one user on one lot; `events` collects what the page is told."""

    def __init__(self, store: LotStore, runs: SqliteStore, jobs: JobManager, user: int, lot_id: int,
                 emit: Callable[[dict[str, Any]], None]) -> None:
        self.store, self.runs, self.jobs, self.user, self.lot_id = store, runs, jobs, user, lot_id
        self.emit = emit
        self.actions: list[str] = []
        self.proposals: list[dict[str, Any]] = []

    def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = getattr(self, f"tool_{name}", None)
        if tool is None:
            return {"error": f"không có công cụ {name}"}
        try:
            return tool(**args)
        except (WebError, ValueError, TypeError, KeyError) as exc:
            message = exc.message if isinstance(exc, WebError) else str(exc)
            self._action(f"{name}: lỗi — {message}")
            return {"error": message}

    def _action(self, text: str) -> None:
        self.actions.append(text)
        self.emit({"type": "action", "text": text})

    # ---- reading ------------------------------------------------------------------------------------------------
    def tool_get_lot(self) -> dict[str, Any]:
        record = self.store.get(self.user, self.lot_id)
        lot = record.lot
        self._action("Đọc dữ liệu lô")
        return {
            "lot_id": record.id, "name": record.name,
            "lines": [{"line_id": x.id, "sku": x.sku, "description": x.description, "unit": x.unit,
                       "fields": {n: {"value": fmt(n, f.value, x), "status": f.status} for n, f in x.fields().items()}}
                      for x in lot.lines],
            "excluded": [{"sku": e.sku, "reason": e.reason} for e in lot.excluded],
            "open_points": len(lot.open_points()),
            "all_confirmed": not lot.open_fields(),
        }

    def tool_list_points(self) -> dict[str, Any]:
        lot = self.store.get(self.user, self.lot_id).lot
        self._action("Đọc các câu hỏi đang chờ")
        return {"points": [{"point_id": p.id, "title": p.title, "question": p.question, "fields": p.fields,
                            "options": [{"choice": i, "label": o.label,
                                         "sources": [f"{s.file} · {s.where}: {s.raw}" for s in o.sources]}
                                        for i, o in enumerate(p.options)]}
                           for p in lot.open_points()]}

    # ---- proposals: the user confirms them ----------------------------------------------------------------------
    def tool_propose_answer(self, point_id: int, choice: int | None = None,
                            values: dict[str, Any] | None = None) -> dict[str, Any]:
        lot = self.store.get(self.user, self.lot_id).lot
        try:
            answer(lot, int(point_id), "proposal", choice=choice, values=values)  # checked, not kept
        except AnswerError as exc:
            return {"ok": False, "error": str(exc)}
        point = next(p for p in lot.points if p.id == int(point_id))
        label = point.options[choice].label if choice is not None else ", ".join(f"{k} = {v}" for k, v in values.items())
        proposal = {"type": "proposal", "kind": "answer", "lot_id": self.lot_id, "point_id": point.id,
                    "title": point.title, "choice": choice, "values": values, "label": label}
        self.proposals.append(proposal)
        self.emit(proposal)
        self._action(f"Đề xuất cho H{point.id}: {label}")
        return {"ok": True, "shown": "Trang đã hiện nút Xác nhận; dữ liệu chỉ chốt khi người dùng bấm."}

    def tool_propose_confirm_lot(self) -> dict[str, Any]:
        lot = self.store.get(self.user, self.lot_id).lot
        if lot.open_points():
            return {"ok": False, "error": f"còn {len(lot.open_points())} câu hỏi chưa trả lời"}
        proposal = {"type": "proposal", "kind": "confirm", "lot_id": self.lot_id, "label": "Xác nhận dữ liệu lô"}
        self.proposals.append(proposal)
        self.emit(proposal)
        self._action("Đề xuất xác nhận dữ liệu lô")
        return {"ok": True, "shown": "Trang đã hiện nút Xác nhận."}

    def tool_propose_add_line(self, sku: str, description: str = "", unit: str = "carton",
                              **fields: Any) -> dict[str, Any]:
        lot = self.store.get(self.user, self.lot_id).lot
        try:
            if any(x.sku == sku.strip() for x in lot.lines):
                raise AnswerError(f"Lô đã có mã {sku.strip()}: hỏi người dùng muốn sửa dòng đó hay thêm dòng riêng")
            values = line_values(fields)
            line = add_line(lot, "proposal", sku, values, description=description, unit=unit).lines[-1]  # checked
        except AnswerError as exc:
            return {"ok": False, "error": str(exc)}
        label = f"Thêm {line.sku}: " + " · ".join(fmt(n, getattr(line, n).value, line) for n in FIELD_NAMES)
        return self._propose_line({"kind": "add_line", "line_id": None, "body": {
            "sku": line.sku, "description": line.description, "unit": line.unit, "values": values}}, label)

    def tool_propose_edit_line(self, line_id: str, **fields: Any) -> dict[str, Any]:
        lot = self.store.get(self.user, self.lot_id).lot
        try:
            values = line_values(fields)
            if not values:
                raise AnswerError("Không có trường nào để sửa")
            line = next(x for x in edit_line(lot, line_id, "proposal", values).lines if x.id == line_id)  # checked
        except AnswerError as exc:
            return {"ok": False, "error": str(exc)}
        label = f"Sửa {line.id}: " + " · ".join(fmt(n, getattr(line, n).value, line) for n in values)
        return self._propose_line({"kind": "edit_line", "line_id": line.id, "body": {"values": values}}, label)

    def _propose_line(self, change: dict[str, Any], label: str) -> dict[str, Any]:
        proposal = {"type": "proposal", "lot_id": self.lot_id, **change, "label": label}
        self.proposals.append(proposal)
        self.emit(proposal)
        self._action(f"Đề xuất: {label}")
        return {"ok": True, "proposal": label, "shown": "Trang đã hiện nút Xác nhận; dữ liệu chỉ chốt khi người dùng bấm."}

    # ---- runs ---------------------------------------------------------------------------------------------------
    def tool_run_mode_a(self, time_limit_s: int = 60) -> dict[str, Any]:
        state = start_mode_a(self.store, self.jobs, self.user, self.lot_id, time_limit=float(time_limit_s))
        self.emit({"type": "run", "lot_id": self.lot_id, "job_id": state["id"]})
        self._action(f"Xếp lô hàng, chọn container rẻ nhất, giới hạn {time_limit_s} s")
        return {"job_id": state["id"], "status": state["status"], "time_limit_s": time_limit_s}

    def tool_run_mode_b(self, fleet: dict[str, int], priority: list[str] | None = None, partial: bool = True,
                        time_limit_s: int = 60) -> dict[str, Any]:
        settings = FillIn(fleet={t: int(n) for t, n in fleet.items()}, priority=priority, partial=partial)
        state = start_mode_b(self.store, self.jobs, self.user, self.lot_id, settings, time_limit=float(time_limit_s))
        self.emit({"type": "run", "lot_id": self.lot_id, "job_id": state["id"]})
        shown = ", ".join(f"{n} × {t}" for t, n in settings.fleet.items() if n)
        self._action(f"Xếp lô hàng vào container có sẵn ({shown}), giới hạn {time_limit_s} s")
        return {"job_id": state["id"], "status": state["status"], "time_limit_s": time_limit_s}

    def _run(self, job_id: str | None) -> dict[str, Any]:
        if job_id is None:
            family = self.store.family(self.user, self.lot_id)
            live = [j for j in self.jobs.jobs.values() if j.owner == self.user and j.lot_id in family]
            saved = self.runs.list_runs(self.user, family)
            if live:
                job_id = max(live, key=lambda j: j.created).id
            elif saved:
                job_id = saved[0].job_id
            else:
                raise ValueError("lô chưa có lần chạy nào")
        job = self.jobs.jobs.get(job_id)
        if job is not None and job.owner == self.user:
            if job.view is None:
                return {"job_id": job_id, "status": job.status, "elapsed_s": round(job.elapsed())}
            return {"status": job.status, **run_summary(job_id, job.view)}
        return {"status": "done", **run_summary(job_id, self.runs.view(self.user, job_id))}

    def tool_get_run(self, job_id: str | None = None) -> dict[str, Any]:
        out = self._run(job_id)
        self._action(f"Đọc kết quả lần chạy {out['job_id']}")
        return out

    def tool_compare_runs(self, a: str, b: str) -> dict[str, Any]:
        first, second = self._run(a), self._run(b)
        self._action(f"So hai lần chạy {a} và {b}")
        out: dict[str, Any] = {"a": first, "b": second}
        if "total_cost" in first and "total_cost" in second:  # the difference on the checker's costs, not the text
            ca, cb = self._cost(a), self._cost(b)
            out["cost_difference_b_minus_a"] = money(cb - ca) if ca is not None and cb is not None else None
            out["containers_difference_b_minus_a"] = second["containers"] - first["containers"]
        return out

    def _cost(self, job_id: str) -> float | None:
        job = self.jobs.jobs.get(job_id)
        view = job.view if job is not None and job.owner == self.user else self.runs.view(self.user, job_id)
        return view["check"]["cost"] if view else None

    # ---- what-if ------------------------------------------------------------------------------------------------
    def tool_make_variant(self, note: str, drop_skus: list[str] | None = None,
                          qty: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        record = self.store.get(self.user, self.lot_id)
        lot = record.lot.model_copy(deep=True)
        at = datetime.now().strftime("%H:%M")
        where = f"yêu cầu trong chat lúc {at}"
        for sku in drop_skus or []:
            gone = [x for x in lot.lines if x.sku == sku]
            if not gone:
                raise ValueError(f"lô không có mã {sku}")
            for line in gone:
                lot.lines.remove(line)
                lot.excluded.append(Excluded(sku=line.sku, description=line.description,
                                             reason=f"Bỏ theo {where}", sources=[Source(file=CHAT_FILE, where=where,
                                                                                      raw=note)]))
        for change in qty or []:
            line = next((x for x in lot.lines if x.id == change["line_id"]), None)
            if line is None:
                raise ValueError(f"lô không có dòng {change['line_id']}")
            new = int(change["qty"])
            if new <= 0:
                raise ValueError("số lượng phải > 0")
            source = Source(file=CHAT_FILE, where=where, raw=f"{new} {UNIT_LABEL[line.unit]}")
            line.qty = LotField(value=None, status="needs_review", sources=[*line.qty.sources, source])
        lot = refresh(lot.model_copy(update={"name": f"{record.name} — {note}"}))
        new_id = self.store.create(self.user, lot, parent_id=record.id, note=f"{note} ({where})",
                                   containers=record.containers)
        self.emit({"type": "lot", "lot_id": new_id, "parent_id": record.id})
        self._action(f"Tạo bản lô mới: {note}")
        self.lot_id = new_id
        return {"lot_id": new_id, "name": lot.name, "open_points": len(lot.open_points())}


def chat_routes(store: LotStore, runs: SqliteStore, jobs: JobManager, llm: Callable[[], ChatLLM]) -> APIRouter:
    router = APIRouter()
    made: list[ChatLLM] = []
    lock = threading.Lock()

    def model() -> ChatLLM:
        with lock:
            if not made:
                made.append(llm())
            return made[0]

    @router.post("/api/lots/{lot_id}/chat")
    def chat(lot_id: int, body: ChatIn, request: Request) -> StreamingResponse:
        user = session_owner(request)
        assert user is not None  # the login middleware is in front of every route
        store.get(user, lot_id)  # another user's lot: 404 before anything streams
        store.add_message(user, lot_id, "user", {"text": body.text})
        history = [("user" if m["role"] == "user" else "model", m["content"]["text"])
                   for m in store.messages(user, lot_id) if m["content"].get("text")]
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def work() -> None:
            tools = ChatTools(store, runs, jobs, user, lot_id, events.put)
            try:
                reply = respond(model(), history, tools)
                content = {"text": reply.text, "unverified": reply.unverified, "actions": tools.actions,
                           "proposals": tools.proposals}
                store.add_message(user, lot_id, "assistant", content)
                events.put({"type": "message", **content, "lot_id": tools.lot_id,
                            "rev": store.get(user, tools.lot_id).rev})
            except (LLMError, WebError) as exc:
                events.put({"type": "error", "message": f"Trợ lý lỗi: {exc}"})
            finally:
                events.put(None)

        threading.Thread(target=work, name="chat", daemon=True).start()

        def stream():
            while (event := events.get()) is not None:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
