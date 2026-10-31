"""Lots kept per user in `app.db` (docs/product/brief.md §3): the lot itself (ADR-0001) as one JSON document,
its uploaded documents as blobs with what the model read from them, and its chat. Every query has the owner's id, so
another user's lot and a missing one are the same `LotNotFound`.

A lot is written with the revision it was read at; an older one is a `Conflict` (the chat and the page may both
write). A what-if copy is a lot with `parent_id`; lists show the lots without one. Deleting a lot marks it, so it can
be restored; marked lots are removed for good after `UNDO_DAYS`.
"""
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from src.lot.schema import Lot
from src.model import ContainerType
from src.web.db import connect, migrate
from src.web.errors import BadRequest, Conflict, LotNotFound

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
UNDO_DAYS = 1
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class DocumentRow:
    id: int
    name: str
    mime: str
    size: int
    status: str  # waiting | reading | read | failed
    error: str | None
    created_at: str


@dataclass(frozen=True)
class LotRecord:
    id: int
    name: str
    rev: int
    lot: Lot
    parent_id: int | None
    note: str | None
    containers: list[ContainerType] | None  # the run settings' cost table last used; None: the default one
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LotSummary:
    id: int
    name: str
    documents: int
    open_points: int
    lines: int
    confirmed: bool  # every field confirmed: the lot can run
    updated_at: str


@dataclass
class LotStore:
    db_path: str | Path
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        with closing(connect(self.db_path)) as conn:
            migrate(conn)
            self._purge(conn)

    def _stamp(self) -> str:
        return self.now().strftime(_STAMP)

    def _purge(self, conn: Any) -> None:
        cutoff = (self.now() - timedelta(days=UNDO_DAYS)).strftime(_STAMP)
        conn.execute("DELETE FROM lots WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))

    # ---- lots ---------------------------------------------------------------------------------------------------
    def create(self, owner: int, lot: Lot, parent_id: int | None = None, note: str | None = None,
               containers: list[ContainerType] | None = None) -> int:
        stamp = self._stamp()
        with closing(connect(self.db_path)) as conn:
            if parent_id is not None:
                self._owned(conn, owner, parent_id)
            cur = conn.execute(
                "INSERT INTO lots (user_id, parent_id, name, note, rev, lot, containers, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (owner, parent_id, lot.name, note, lot.model_dump_json(), _containers_json(containers), stamp, stamp))
            return int(cur.lastrowid)

    def get(self, owner: int, lot_id: int) -> LotRecord:
        with closing(connect(self.db_path)) as conn:
            row = self._owned(conn, owner, lot_id)
        return LotRecord(id=row["id"], name=row["name"], rev=row["rev"], lot=Lot.model_validate_json(row["lot"]),
                         parent_id=row["parent_id"], note=row["note"],
                         containers=[ContainerType(**c) for c in json.loads(row["containers"])] if row["containers"] else None,
                         created_at=row["created_at"], updated_at=row["updated_at"])

    def save(self, owner: int, lot_id: int, lot: Lot, rev: int, containers: list[ContainerType] | None = None) -> int:
        """Write `lot` over revision `rev`; the new revision. `Conflict` when the lot has moved on since `rev`."""
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            sets, args = "name = ?, lot = ?, rev = rev + 1, updated_at = ?", [lot.name, lot.model_dump_json(), self._stamp()]
            if containers is not None:
                sets += ", containers = ?"
                args.append(_containers_json(containers))
            cur = conn.execute(f"UPDATE lots SET {sets} WHERE id = ? AND user_id = ? AND rev = ?",
                               (*args, lot_id, owner, rev))
            if cur.rowcount == 0:
                raise Conflict("lô vừa được sửa ở chỗ khác; tải lại lô rồi làm lại")
            return rev + 1

    def list(self, owner: int) -> list[LotSummary]:
        """The owner's lots without a parent, most recently changed first."""
        with closing(connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT l.id, l.name, l.lot, l.updated_at, (SELECT COUNT(*) FROM documents d WHERE d.lot_id = l.id) AS docs"
                " FROM lots l WHERE l.user_id = ? AND l.parent_id IS NULL AND l.deleted_at IS NULL"
                " ORDER BY l.updated_at DESC", (owner,)).fetchall()
        out = []
        for r in rows:
            lot = Lot.model_validate_json(r["lot"])
            out.append(LotSummary(id=r["id"], name=r["name"], documents=r["docs"], open_points=len(lot.open_points()),
                                  lines=len(lot.lines), confirmed=bool(lot.lines) and not lot.open_fields(),
                                  updated_at=r["updated_at"]))
        return out

    def family(self, owner: int, lot_id: int) -> list[int]:
        """The ids of a lot's family: its root and every copy made from it, the root first."""
        with closing(connect(self.db_path)) as conn:
            root = self._owned(conn, owner, lot_id)
            while root["parent_id"] is not None:
                root = self._owned(conn, owner, root["parent_id"])
            ids, frontier = [root["id"]], [root["id"]]
            while frontier:
                rows = conn.execute(f"SELECT id FROM lots WHERE user_id = ? AND deleted_at IS NULL AND parent_id IN"
                                    f" ({', '.join('?' * len(frontier))}) ORDER BY id", (owner, *frontier)).fetchall()
                frontier = [r["id"] for r in rows]
                ids += frontier
        return ids

    def delete(self, owner: int, lot_id: int) -> None:
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            conn.execute("UPDATE lots SET deleted_at = ? WHERE id = ? AND user_id = ?", (self._stamp(), lot_id, owner))

    def restore(self, owner: int, lot_id: int) -> None:
        with closing(connect(self.db_path)) as conn:
            if conn.execute("UPDATE lots SET deleted_at = NULL WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL",
                            (lot_id, owner)).rowcount == 0:
                raise _missing(lot_id)

    def _owned(self, conn: Any, owner: int, lot_id: int) -> Any:
        row = conn.execute("SELECT * FROM lots WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                           (lot_id, owner)).fetchone()
        if row is None:
            raise _missing(lot_id)
        return row

    # ---- documents ----------------------------------------------------------------------------------------------
    def add_document(self, owner: int, lot_id: int, name: str, mime: str, data: bytes) -> int:
        if len(data) > MAX_DOCUMENT_BYTES:
            raise BadRequest(f"{name}: tệp lớn hơn {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB")
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            cur = conn.execute("INSERT INTO documents (lot_id, name, mime, size, data, status, created_at)"
                               " VALUES (?, ?, ?, ?, ?, 'waiting', ?)", (lot_id, name, mime, len(data), data, self._stamp()))
            return int(cur.lastrowid)

    def documents(self, owner: int, lot_id: int) -> list[DocumentRow]:
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            rows = conn.execute("SELECT id, name, mime, size, status, error, created_at FROM documents"
                                " WHERE lot_id = ? ORDER BY id", (lot_id,)).fetchall()
        return [DocumentRow(**dict(r)) for r in rows]

    def document_data(self, owner: int, lot_id: int, doc_id: int) -> tuple[str, str, bytes]:
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            row = conn.execute("SELECT name, mime, data FROM documents WHERE id = ? AND lot_id = ?",
                               (doc_id, lot_id)).fetchone()
        if row is None:
            raise LotNotFound(f"không có tài liệu {doc_id}")
        return row["name"], row["mime"], bytes(row["data"])

    def delete_document(self, owner: int, lot_id: int, doc_id: int) -> str:
        """Remove a document for good (its file and its reading); its name. Refused while a document of the lot is
        waiting or being read: the merge after that reading would not know this one is gone."""
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            row = conn.execute("SELECT name FROM documents WHERE id = ? AND lot_id = ?", (doc_id, lot_id)).fetchone()
            if row is None:
                raise LotNotFound(f"không có tài liệu {doc_id}")
            if conn.execute("SELECT 1 FROM documents WHERE lot_id = ? AND status IN ('waiting', 'reading')",
                            (lot_id,)).fetchone():
                raise Conflict("đang đọc tài liệu của lô; đợi đọc xong rồi xóa")
            conn.execute("DELETE FROM documents WHERE id = ? AND lot_id = ?", (doc_id, lot_id))
        return str(row["name"])

    def retry_document(self, owner: int, lot_id: int, doc_id: int) -> None:
        """A document whose reading failed back to `waiting`, its error cleared. Refused for any other status."""
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            row = conn.execute("SELECT status FROM documents WHERE id = ? AND lot_id = ?", (doc_id, lot_id)).fetchone()
            if row is None:
                raise LotNotFound(f"không có tài liệu {doc_id}")
            if row["status"] != "failed":
                raise Conflict("chỉ đọc lại được tài liệu đọc lỗi")
            conn.execute("UPDATE documents SET status = 'waiting', error = NULL WHERE id = ?", (doc_id,))

    def readings(self, owner: int, lot_id: int) -> list[tuple[str, dict[str, Any]]]:
        """(file name, reading) of every document read so far, in upload order."""
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            rows = conn.execute("SELECT name, reading FROM documents WHERE lot_id = ? AND status = 'read' ORDER BY id",
                                (lot_id,)).fetchall()
        return [(r["name"], json.loads(r["reading"])) for r in rows]

    def set_document(self, lot_id: int, doc_id: int, status: str, reading: dict[str, Any] | None = None,
                     error: str | None = None) -> None:
        """The reading of a document; called by the reader, which was handed the lot by its owner."""
        with closing(connect(self.db_path)) as conn:
            conn.execute("UPDATE documents SET status = ?, reading = ?, error = ? WHERE id = ? AND lot_id = ?",
                         (status, json.dumps(reading, ensure_ascii=False) if reading is not None else None, error,
                          doc_id, lot_id))

    # ---- chat ---------------------------------------------------------------------------------------------------
    def add_message(self, owner: int, lot_id: int, role: str, content: dict[str, Any]) -> int:
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            cur = conn.execute("INSERT INTO chat_messages (lot_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                               (lot_id, role, json.dumps(content, ensure_ascii=False), self._stamp()))
            return int(cur.lastrowid)

    def messages(self, owner: int, lot_id: int) -> list[dict[str, Any]]:
        with closing(connect(self.db_path)) as conn:
            self._owned(conn, owner, lot_id)
            rows = conn.execute("SELECT id, role, content, created_at FROM chat_messages WHERE lot_id = ? ORDER BY id",
                                (lot_id,)).fetchall()
        return [{"id": r["id"], "role": r["role"], "content": json.loads(r["content"]), "created_at": r["created_at"]}
                for r in rows]


def _containers_json(containers: list[ContainerType] | None) -> str | None:
    return json.dumps([asdict(c) for c in containers]) if containers is not None else None


def _missing(lot_id: int) -> LotNotFound:
    return LotNotFound(f"không có lô {lot_id}")
