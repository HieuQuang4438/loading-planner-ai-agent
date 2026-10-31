"""Routes of the product's lots: a lot, its documents read by the model in the background, its points
answered, and its runs (mode A mode B). Every query is the session user's (`src.web.lotstore`).

Bodies are JSON (the login middleware refuses any other): a document comes as base64. Writes to a lot carry the
revision the client read (`rev`); an older one answers 409 `conflict`."""
from __future__ import annotations

import base64
import binascii
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Callable

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.extract.documents import UnsupportedFile, load
from src.extract.merge import Doc, merge
from src.extract.pipeline import read_document
from src.extract.readings import DocumentReading
from src.engines import fill
from src.formats import Issue, instance_to_dict
from src.llm.client import LLM, LLMError
from src.lot.engine import LotNotReady, confirm_rest, to_instance
from src.lot.review import AnswerError, answer, carry, forget, refresh
from src.lot.edit import add_line, drop_line, edit_line, restore_line
from src.lot.schema import Line, Lot, PieceUnit
from src.model import ContainerType, Instance, Params
from src.plan import mode_b
from src.plan.mode_a import DEFAULT_CONTAINERS, ENGINE, compare, orient_for, run_lot
from src.web.api import session_owner
from src.web.errors import BadRequest, Conflict, LotNotFound, NotReady
from src.web.job_manager import JobManager
from src.web.lotstore import MAX_DOCUMENT_BYTES, LotStore
from src.web.mode import DEFAULT_ALPHA, DEFAULT_DELTA
from src.web.runstore import SqliteStore

READERS = 4
SAVE_TRIES = 3
DEFAULT_RUN_S = 60.0  # docs/product/ux.md §5: 1, 2 or 5 minutes


class NewLot(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None  # a what-if copy of this lot
    note: str | None = None


class RenameIn(BaseModel):
    rev: int
    name: str = Field(min_length=1, max_length=200)


class LineEditIn(BaseModel):
    rev: int
    values: dict[str, Any] = {}
    sku: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=300)


class LineNewIn(BaseModel):
    rev: int
    sku: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    unit: PieceUnit = "carton"
    values: dict[str, Any]


class FileIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data: str  # base64


class FilesIn(BaseModel):
    files: list[FileIn] = Field(min_length=1, max_length=20)


class AnswerIn(BaseModel):
    rev: int
    choice: int | None = None
    values: dict[str, Any] | None = None


class RevIn(BaseModel):
    rev: int


class ContainerIn(BaseModel):
    id: str
    L: float = Field(gt=0)
    W: float = Field(gt=0)
    H: float = Field(gt=0)
    door_w: float = Field(gt=0)
    door_h: float = Field(gt=0)
    max_mass: float = Field(gt=0)
    cost: float = Field(ge=0)


class FillIn(BaseModel):
    """Mode B's settings (ADR-0002): containers at hand per type, line ids by priority (None: the lot's order), and
    whether a line may go in part."""
    fleet: dict[str, int] = Field(min_length=1)
    priority: list[str] | None = None
    partial: bool = True


class RunIn(BaseModel):
    mode: str = "a"
    containers: list[ContainerIn] | None = None  # None: the lot's last table, else the default one
    time_limit: float | None = None
    fill: FillIn | None = None  # mode B
    # "Thiết lập nâng cao": the gap, the support ratio, and whether E5 tips the pieces that may tip (None: the
    # lot decides, `orient_for`)
    delta: float = Field(default=DEFAULT_DELTA, ge=0)
    alpha: float = Field(default=DEFAULT_ALPHA, ge=0, le=1)
    orient: bool | None = None


class CompareIn(BaseModel):
    containers: list[ContainerIn] | None = None
    mode: str = "a"
    fill: FillIn | None = None  # mode B
    delta: float = Field(default=DEFAULT_DELTA, ge=0)  # the run's own, so the baseline is packed as it was
    alpha: float = Field(default=DEFAULT_ALPHA, ge=0, le=1)


_UNMERGED = frozenset({-1})  # no document has this id: the lot must be merged again


class Reader:
    """Reads uploaded documents in the background, one model call each, then merges every reading of the lot again
    and carries what the user confirmed over (`src.lot.review.carry`)."""

    def __init__(self, store: LotStore, llm: Callable[[], LLM]) -> None:
        self.store, self._make_llm, self._llm = store, llm, None
        self._pool = ThreadPoolExecutor(max_workers=READERS, thread_name_prefix="reader")
        self._lock = threading.Lock()
        self._merged: dict[int, frozenset[int]] = {}  # lot id -> the documents its last merge read

    def llm(self) -> LLM:
        with self._lock:
            if self._llm is None:
                self._llm = self._make_llm()
            return self._llm

    def submit(self, owner: int, lot_id: int, doc_ids: list[int]) -> None:
        with self._lock:
            self._merged[lot_id] = _UNMERGED  # until the readings are merged, the page keeps waiting
        for doc_id in doc_ids:
            self._pool.submit(self._read, owner, lot_id, doc_id)

    def _read(self, owner: int, lot_id: int, doc_id: int) -> None:
        try:
            self.store.set_document(lot_id, doc_id, "reading")
            name, _, data = self.store.document_data(owner, lot_id, doc_id)
            reading = read_document(self.llm(), load(name, data))
            self.store.set_document(lot_id, doc_id, "read", reading=reading.model_dump())
        except (LLMError, UnsupportedFile, ValueError) as exc:
            self.store.set_document(lot_id, doc_id, "failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a reader thread never dies silently: the document says why
            self.store.set_document(lot_id, doc_id, "failed", error=f"lỗi khi đọc: {exc}")
        finally:
            self.settle(owner, lot_id)

    def reread(self, owner: int, lot_id: int, doc_id: int) -> None:
        """Read a failed document again; the lot is merged again after it, though its set of documents is the same."""
        with self._lock:
            self.store.retry_document(owner, lot_id, doc_id)
            self._merged[lot_id] = _UNMERGED
        self.submit(owner, lot_id, [doc_id])

    def settled(self, lot_id: int, documents: list[Any]) -> bool:
        """Whether the lot holds the merge of its documents as they are: none waiting or being read, and merged since
        (a lot this process has not merged is taken as merged: the app restarted after it)."""
        done = frozenset(d.id for d in documents)
        with self._lock:
            return not any(d.status in ("waiting", "reading") for d in documents) and self._merged.get(lot_id, done) == done

    def remove(self, owner: int, lot_id: int, doc_id: int) -> None:
        """Delete a document and merge the lot again from the rest; what was confirmed on it is asked again
        (`src.lot.review.forget`)."""
        with self._lock:
            name = self.store.delete_document(owner, lot_id, doc_id)
        self.settle(owner, lot_id, forgotten=name)

    def settle(self, owner: int, lot_id: int, forgotten: str | None = None) -> None:
        """Once no document of the lot is waiting or being read: the lot merged again from every reading, once per set
        of documents (readers finishing together must not write the lot again while the user answers). `forgotten`:
        the name of a document just removed."""
        with self._lock:
            documents = self.store.documents(owner, lot_id)
            if any(d.status in ("waiting", "reading") for d in documents):
                return
            done = frozenset(d.id for d in documents)
            if self._merged.get(lot_id) == done:
                return
            self._merged[lot_id] = done
            docs = [Doc(name, DocumentReading.model_validate(r)) for name, r in self.store.readings(owner, lot_id)]
            for _ in range(SAVE_TRIES):
                record = self.store.get(owner, lot_id)
                merged = merge(record.name, docs)
                old = forget(record.lot, forgotten) if forgotten else record.lot
                try:
                    self.store.save(owner, lot_id, carry(old, merged), record.rev)
                    return
                except Conflict:
                    continue


def lot_routes(store: LotStore, runs: SqliteStore, jobs: JobManager, reader: Reader) -> APIRouter:
    router = APIRouter()

    def owner(request: Request) -> int:
        user_id = session_owner(request)
        assert user_id is not None  # the login middleware is in front of every route
        return user_id

    def user_name(request: Request) -> str:
        return request.scope["planner.user"].name

    def lot_body(user: int, lot_id: int) -> dict[str, Any]:
        record = store.get(user, lot_id)
        family = store.family(user, lot_id)
        relatives = [store.get(user, i) for i in family]
        documents = store.documents(user, lot_id)
        return {
            "id": record.id, "name": record.name, "rev": record.rev, "parent_id": record.parent_id,
            "note": record.note, "lot": record.lot.model_dump(mode="json"),
            "containers": [asdict(c) for c in (record.containers or DEFAULT_CONTAINERS)],
            "documents": [asdict(d) for d in documents],
            "settled": reader.settled(lot_id, documents),  # the page waits while False
            "family": [{"id": r.id, "name": r.name, "note": r.note, "parent_id": r.parent_id} for r in relatives],
            "runs": [asdict(r) for r in runs.list_runs(user, family)],
            "updated_at": record.updated_at,
        }

    def write(user: int, lot_id: int, rev: int, change: Callable[[Lot], Lot]) -> dict[str, Any]:
        record = store.get(user, lot_id)
        if record.rev != rev:
            raise Conflict("lô vừa được sửa ở chỗ khác; tải lại lô rồi làm lại")
        store.save(user, lot_id, change(record.lot), rev)
        return lot_body(user, lot_id)

    def documents_lines(user: int, lot_id: int, name: str) -> dict[str, Line]:
        """The lot's lines as its documents give them (merged again, nothing confirmed): where a row the user dropped
        comes back from when a point is answered again."""
        docs = [Doc(n, DocumentReading.model_validate(r)) for n, r in store.readings(user, lot_id)]
        return {line.id: line for line in merge(name, docs).lines} if docs else {}

    @router.get("/api/plan/containers")
    def default_containers() -> dict[str, Any]:
        return {"containers": [asdict(c) for c in DEFAULT_CONTAINERS], "simulated": True}

    @router.get("/api/lots")
    def list_lots(request: Request) -> list[dict[str, Any]]:
        user = owner(request)
        out = []
        for summary in store.list(user):
            row = asdict(summary)
            family = store.family(user, summary.id)
            last = next(iter(runs.list_runs(user, family)), None)
            row["last_run"] = asdict(last) if last else None
            out.append(row)
        return out

    @router.post("/api/lots", status_code=201)
    def create_lot(body: NewLot, request: Request) -> dict[str, Any]:
        user = owner(request)
        if body.parent_id is not None:
            parent = store.get(user, body.parent_id)
            lot = parent.lot.model_copy(update={"name": body.name}, deep=True)
            lot_id = store.create(user, lot, parent_id=parent.id, note=body.note, containers=parent.containers)
        else:
            lot_id = store.create(user, Lot(name=body.name, lines=[]), note=body.note)
        return lot_body(user, lot_id)

    @router.get("/api/lots/{lot_id}")
    def get_lot(lot_id: int, request: Request) -> dict[str, Any]:
        return lot_body(owner(request), lot_id)

    @router.patch("/api/lots/{lot_id}")
    def rename_lot(lot_id: int, body: RenameIn, request: Request) -> dict[str, Any]:
        name = body.name.strip()
        if not name:
            raise BadRequest("tên lô không được để trống")
        return write(owner(request), lot_id, body.rev, lambda lot: lot.model_copy(update={"name": name}))

    @router.delete("/api/lots/{lot_id}")
    def delete_lot(lot_id: int, request: Request) -> dict[str, Any]:
        store.delete(owner(request), lot_id)
        return {"ok": True}

    @router.post("/api/lots/{lot_id}/restore")
    def restore_lot(lot_id: int, request: Request) -> dict[str, Any]:
        user = owner(request)
        store.restore(user, lot_id)
        return lot_body(user, lot_id)

    @router.post("/api/lots/{lot_id}/documents", status_code=202)
    def add_documents(lot_id: int, body: FilesIn, request: Request) -> dict[str, Any]:
        user = owner(request)
        store.get(user, lot_id)
        files = []
        for f in body.files:
            try:
                data = base64.b64decode(f.data, validate=True)
            except binascii.Error:
                raise BadRequest(f"{f.name}: không phải base64") from None
            if len(data) > MAX_DOCUMENT_BYTES:
                raise BadRequest(f"{f.name}: tệp lớn hơn {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB")
            try:
                load(f.name, data)  # an unsupported or broken file is refused now, not after a model call
            except Exception as exc:  # noqa: BLE001 - whatever the parser raises, the user gets the file's name
                raise BadRequest(f"{f.name}: không đọc được tệp ({exc})") from None
            files.append((f.name, data))
        ids = [store.add_document(user, lot_id, name, _mime(name), data) for name, data in files]
        reader.submit(user, lot_id, ids)
        return lot_body(user, lot_id)

    @router.delete("/api/lots/{lot_id}/documents/{doc_id}")
    def delete_document(lot_id: int, doc_id: int, request: Request) -> dict[str, Any]:
        user = owner(request)
        reader.remove(user, lot_id, doc_id)
        return lot_body(user, lot_id)

    @router.post("/api/lots/{lot_id}/documents/{doc_id}/read", status_code=202)
    def reread_document(lot_id: int, doc_id: int, request: Request) -> dict[str, Any]:
        user = owner(request)
        reader.reread(user, lot_id, doc_id)
        return lot_body(user, lot_id)

    @router.post("/api/lots/{lot_id}/points/{point_id}")
    def answer_point(lot_id: int, point_id: int, body: AnswerIn, request: Request) -> dict[str, Any]:
        user, by = owner(request), user_name(request)

        def change(lot: Lot) -> Lot:
            point = next((p for p in lot.points if p.id == point_id), None)
            restore = documents_lines(user, lot_id, lot.name) if point is not None and point.resolved_at else None
            try:
                return answer(lot, point_id, by, choice=body.choice, values=body.values, restore=restore)
            except AnswerError as exc:
                raise BadRequest(str(exc)) from None

        return write(user, lot_id, body.rev, change)

    def lot_change(user: int, lot_id: int, rev: int, change: Callable[[Lot], Lot]) -> dict[str, Any]:
        def checked(lot: Lot) -> Lot:
            try:
                return change(lot)
            except AnswerError as exc:
                raise BadRequest(str(exc)) from None
        return write(user, lot_id, rev, checked)

    @router.post("/api/lots/{lot_id}/lines", status_code=201)
    def new_line(lot_id: int, body: LineNewIn, request: Request) -> dict[str, Any]:
        by = user_name(request)
        return lot_change(owner(request), lot_id, body.rev, lambda lot: add_line(
            lot, by, body.sku, body.values, description=body.description, unit=body.unit))

    @router.post("/api/lots/{lot_id}/lines/{line_id}")
    def change_line(lot_id: int, line_id: str, body: LineEditIn, request: Request) -> dict[str, Any]:
        by = user_name(request)
        return lot_change(owner(request), lot_id, body.rev, lambda lot: edit_line(
            lot, line_id, by, body.values, sku=body.sku, description=body.description))

    @router.post("/api/lots/{lot_id}/lines/{line_id}/drop")
    def take_out_line(lot_id: int, line_id: str, body: RevIn, request: Request) -> dict[str, Any]:
        return lot_change(owner(request), lot_id, body.rev, lambda lot: drop_line(lot, line_id))

    @router.post("/api/lots/{lot_id}/lines/{line_id}/restore")
    def put_back_line(lot_id: int, line_id: str, body: RevIn, request: Request) -> dict[str, Any]:
        user = owner(request)
        restore = documents_lines(user, lot_id, store.get(user, lot_id).name)
        return lot_change(user, lot_id, body.rev, lambda lot: restore_line(lot, line_id, restore))

    @router.post("/api/lots/{lot_id}/confirm")
    def confirm_lot(lot_id: int, body: RevIn, request: Request) -> dict[str, Any]:
        """The user's "the lot is right": the extracted fields confirmed once no point is open (ADR-0001)."""
        user, by = owner(request), user_name(request)

        def change(lot: Lot) -> Lot:
            out = refresh(lot)
            try:
                confirm_rest(out, by)
            except LotNotReady as exc:
                raise _not_ready(exc) from None
            return out

        return write(user, lot_id, body.rev, change)

    @router.post("/api/lots/{lot_id}/compare")
    def compare_lot(lot_id: int, body: CompareIn, request: Request) -> dict[str, Any]:
        """Mode A: the lower bound and the single-type baselines of a confirmed lot. Mode B: the pieces the
        priority-order baseline places."""
        record = store.get(owner(request), lot_id)
        containers = _containers(body.containers, record.containers)
        params = Params(delta=body.delta, alpha=body.alpha)
        try:
            if body.mode == "b":
                return mode_b.baseline(_fill_instance(record.lot, containers, body.fill), params)
            instance = to_instance(record.lot, containers)
        except LotNotReady as exc:
            raise _not_ready(exc) from None
        return compare(instance, params)

    @router.post("/api/runs/{job_id}/compare")
    def compare_run(job_id: str, request: Request) -> dict[str, Any]:
        """What a run is compared with, from the lot and params it was packed with, not the lot as it is now:
        mode A's bound and single-type baselines, or mode B's priority-order baseline; and `lot_changed`, whether the
        product lot's data or cost table differ from the run's since."""
        user = owner(request)
        instance, params, lot_id = run_snapshot(user, job_id)
        out = mode_b.baseline(instance, params) if fill.META_KEY in instance.meta else compare(instance, params)
        return {**out, "lot_changed": lot_changed(user, lot_id, instance)}

    def run_snapshot(user: int, job_id: str) -> tuple[Instance, Params, int | None]:
        try:
            job = jobs.get(job_id, user)
        except LotNotFound:
            return runs.snapshot(user, job_id)
        assert job.instance is not None  # a product run always has its lot
        return job.instance, Params(delta=job.delta, alpha=job.alpha), job.lot_id

    def lot_changed(user: int, lot_id: int | None, instance: Instance) -> bool:
        if lot_id is None:
            return False
        try:
            record = store.get(user, lot_id)
            now = to_instance(record.lot, _containers(None, record.containers))
        except LotNotFound:
            return False  # the lot is gone: nothing to run again
        except LotNotReady:
            return True
        def data(x: Instance) -> tuple[Any, Any]:  # names and meta are not the lot's data
            d = instance_to_dict(x)
            return d["items"], d["container_types"]
        return data(now) != data(instance)

    @router.post("/api/lots/{lot_id}/runs", status_code=202)
    def run_lot_route(lot_id: int, body: RunIn, request: Request) -> dict[str, Any]:
        knobs = {"delta": body.delta, "alpha": body.alpha, "orient": body.orient}
        if body.mode == "b":
            return start_mode_b(store, jobs, owner(request), lot_id, body.fill, body.containers, body.time_limit, **knobs)
        if body.mode != "a":
            raise BadRequest("chế độ phải là a hoặc b")
        return start_mode_a(store, jobs, owner(request), lot_id, body.containers, body.time_limit, **knobs)

    @router.get("/api/lots/{lot_id}/chat")
    def chat_history(lot_id: int, request: Request) -> list[dict[str, Any]]:
        return store.messages(owner(request), lot_id)

    return router


def start_mode_a(store: LotStore, jobs: JobManager, user: int, lot_id: int, given: list[ContainerIn] | None = None,
                 time_limit: float | None = None, delta: float = DEFAULT_DELTA, alpha: float = DEFAULT_ALPHA,
                 orient: bool | None = None) -> dict[str, Any]:
    """Queue a mode-A run of a confirmed lot; a given cost table is kept with the lot for its next runs. `orient`
    True is honoured only when some line may tip (None: exactly then)."""
    record = store.get(user, lot_id)
    containers = _containers(given, record.containers)
    try:
        data, can_tip = run_lot(record.lot, containers)
    except LotNotReady as exc:
        raise _not_ready(exc) from None
    if given is not None:
        store.save(user, lot_id, record.lot, record.rev, containers=list(containers))
    job = jobs.start(ENGINE, data, time_limit=time_limit or DEFAULT_RUN_S, delta=delta, alpha=alpha,
                     orient=can_tip and (orient is None or orient), owner=user, lot_id=lot_id, mode="a")
    return jobs.state(job.id, user)


def start_mode_b(store: LotStore, jobs: JobManager, user: int, lot_id: int, settings: FillIn | None,
                 given: list[ContainerIn] | None = None, time_limit: float | None = None, delta: float = DEFAULT_DELTA,
                 alpha: float = DEFAULT_ALPHA, orient: bool | None = None) -> dict[str, Any]:
    """Queue a mode-B run of a confirmed lot: the containers at hand, by the user's priority order."""
    record = store.get(user, lot_id)
    containers = _containers(given, record.containers)
    try:
        instance = _fill_instance(record.lot, containers, settings)
    except LotNotReady as exc:
        raise _not_ready(exc) from None
    job = jobs.start(mode_b.ENGINE, instance_to_dict(instance), time_limit=time_limit or DEFAULT_RUN_S, delta=delta,
                     alpha=alpha, orient=orient_for(instance) and (orient is None or orient), owner=user, lot_id=lot_id,
                     mode="b")
    return jobs.state(job.id, user)


def _fill_instance(lot: Lot, containers: tuple[ContainerType, ...], settings: FillIn | None) -> Instance:
    if settings is None:
        raise BadRequest("xếp vào container có sẵn cần số container mỗi loại")
    try:
        return mode_b.fill_instance(lot, containers, settings.fleet, settings.priority, settings.partial)
    except LotNotReady:
        raise
    except ValueError as exc:
        raise BadRequest(f"thiết lập xếp vào container có sẵn không hợp lệ: {exc}") from None


def _containers(given: list[ContainerIn] | None, saved: list[ContainerType] | None) -> tuple[ContainerType, ...]:
    if given is not None:
        if not given:
            raise BadRequest("bảng cước trống")
        return tuple(ContainerType(**c.model_dump()) for c in given)
    return tuple(saved) if saved else DEFAULT_CONTAINERS


def _not_ready(exc: LotNotReady) -> NotReady:
    return NotReady(str(exc), [Issue("not confirmed", field=f) for f in exc.fields])


_MIMES = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "csv": "text/csv",
          "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


def _mime(name: str) -> str:
    return _MIMES.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")
