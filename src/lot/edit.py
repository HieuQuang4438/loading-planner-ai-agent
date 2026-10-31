"""The user's own changes to a lot's rows: a row edited, a row added, a row taken out and put back. What
the user enters is confirmed data (docs/product/brief.md §2.3), checked like an answer to a point (src.lot.review).

A row added has no source in any field; that is how `carry` keeps it when the lot is merged again (ADR-0001). A row
read from the documents and taken out goes to `excluded` with `DROPPED_REASON`, the same as a row dropped at a point,
and stays out when the lot is merged again until it is put back.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.lot.engine import confirm, now
from src.lot.review import (_TYPES, DROPPED_REASON, AnswerError, dropped_id, is_manual, refresh, unique_id)
from src.lot.schema import FIELD_NAMES, Excluded, Line, Lot, PieceUnit, line_ids


def edit_line(lot: Lot, line_id: int | str, by: str, values: dict[str, Any], sku: str | None = None,
              description: str | None = None, at: str | None = None) -> Lot:
    """`lot` with row `line_id` changed by `by`: each field of `values` (field name -> value) confirmed with that value.
    A field an open point settles is answered there, not here. The code and description change on a row added only:
    a row read from the documents is matched to them by its code."""
    out = lot.model_copy(deep=True)
    line = _line(out, str(line_id))
    asked = {f for p in out.open_points() for f in p.fields}
    stamp = at or now()
    for name, value in values.items():
        if name not in FIELD_NAMES:
            raise AnswerError(f"Không có trường {name}")
        if f"{line.id}.{name}" in asked:
            n = next(p.id for p in out.open_points() if f"{line.id}.{name}" in p.fields)
            raise AnswerError(f"{line.sku}: {name} đang chờ trả lời ở câu hỏi H{n}")
        confirm(getattr(line, name), by, _typed(name, value), stamp)
    if sku is not None or description is not None:
        if not is_manual(line):
            raise AnswerError("Mã và mô tả của dòng đọc từ tài liệu không sửa được; bỏ dòng rồi thêm dòng mới")
        if sku is not None:
            line.sku = _code(sku)
        if description is not None:
            line.description = description.strip()
    return _checked(out)


def add_line(lot: Lot, by: str, sku: str, values: dict[str, Any], description: str = "", unit: PieceUnit = "carton",
             at: str | None = None) -> Lot:
    """`lot` with a row of the user's own, every field given and confirmed, no source."""
    missing = [n for n in FIELD_NAMES if values.get(n) is None]
    if missing:
        raise AnswerError(f"Thiếu {', '.join(missing)}")
    stamp = at or now()
    code = _code(sku)
    fields = {n: {"value": _typed(n, values[n]), "status": "confirmed", "confirmed_by": by, "confirmed_at": stamp}
              for n in FIELD_NAMES}
    out = lot.model_copy(deep=True)
    new_id = unique_id(line_ids([code])[0], {x.id for x in out.lines})
    try:
        out.lines.append(Line(id=new_id, sku=code, description=description.strip(), unit=unit, **fields))
    except ValidationError as exc:
        raise AnswerError(f"Giá trị không hợp lệ: {exc.errors()[0]['msg']}") from None
    return _checked(out)


def drop_line(lot: Lot, line_id: int | str) -> Lot:
    """`lot` without row `line_id`: a row added is gone; a row read from the documents goes to `excluded`."""
    out = lot.model_copy(deep=True)
    line = _line(out, str(line_id))
    out.lines.remove(line)
    if not is_manual(line):
        out.excluded.append(Excluded(sku=line.sku, description=line.description,
                                     reason=DROPPED_REASON.format(line=line.id), sources=line.qty.sources))
    return _checked(out)


def restore_line(lot: Lot, line_id: str, restore: dict[str, Line]) -> Lot:
    """`lot` with row `line_id`, taken out by the user (from the table or at a point), back as the documents give it
    (`restore`: the lot's documents merged again). Answers that touched the row are void: its fields are asked again."""
    out = lot.model_copy(deep=True)
    if not any(dropped_id(e.reason) == line_id for e in out.excluded):
        raise AnswerError(f"Dòng {line_id} không bị bỏ")
    line = restore.get(line_id)
    if line is None:
        raise AnswerError(f"Không lấy lại được dòng {line_id}: tài liệu của lô không còn dòng này")
    if any(x.id == line_id for x in out.lines):
        raise AnswerError(f"Lô đã có dòng {line_id}")
    out.excluded = [e for e in out.excluded if dropped_id(e.reason) != line_id]
    out.lines.append(line.model_copy(deep=True))
    order = {x: i for i, x in enumerate(restore)}
    out.lines.sort(key=lambda x: order.get(x.id, len(order)))
    out.points = [p for p in out.points if not any(f.rsplit(".", 1)[0] == line_id for f in p.fields)]
    return _checked(out)


def _line(lot: Lot, line_id: str) -> Line:
    line = next((x for x in lot.lines if x.id == line_id), None)
    if line is None:
        raise AnswerError(f"Không có dòng {line_id}")
    return line


def _code(sku: str) -> str:
    code = sku.strip()
    if not code:
        raise AnswerError("Mã hàng không được để trống")
    return code


def _typed(name: str, value: Any) -> Any:
    try:
        return _TYPES[name].validate_python(value)
    except ValidationError as exc:
        raise AnswerError(f"{name}: giá trị không hợp lệ ({exc.errors()[0]['msg']})") from None


def _checked(lot: Lot) -> Lot:
    try:
        return refresh(Lot.model_validate(lot.model_dump()))
    except ValidationError as exc:
        raise AnswerError(f"Giá trị không hợp lệ: {exc.errors()[0]['msg']}") from None
