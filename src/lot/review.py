"""The points the user must confirm, found by fixed rules from a lot's fields, and the user's answers applied
(docs/product/ux.md §4, docs/product/brief.md §2.3). No model is called: the same lot always gives the same points,
worded by templates; a chat may word them again, but the options are these.

A point is opened for every field `needs_review` (src.extract.merge decides which), grouped by cause:
- a code on several packing-list rows: one point per code, "keep every row" or "drop row k";
- a code a document says is not shipped: one point per row, "keep" or "drop";
- a quantity counted in pallets: one point per row for its quantity, size and mass;
- handling marks (posture, stacking, fragile) read with a doubt: one point per row;
- fields no document gives among posture, stacking, fragile: one point for the whole lot, the engine's defaults;
- otherwise one point per code and field (rows with the same options share it): sources that disagree, a net mass
  only, a number without a unit, a field missing.
Options come from the sources: each value they give, read again from the source's text, with the sources that give it.
A value of the user's own ("Giá trị khác") is always possible, by `answer(values=...)`.

Points answered stay as they were; `find_points` opens new ones only for fields no answered point covers, and numbers
all of them in page order (rows, then fields; the lot-wide point last).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from src.extract import units
from src.lot.engine import confirm, default_for, now
from src.lot.schema import (FIELD_NAMES, MAX_DIM_M, NOT_SHIPPED, Dims, Excluded, Line, Lot, LotField, Option, Point,
                            Posture, Source, Stacking)

MARKS = ("posture", "stacking", "fragile")  # handling marks: what no document gives takes the engine's default
DROP = "drop"
DROPPED_REASON = "Người dùng bỏ dòng {line} khỏi lô"
FIELD_LABEL = {"qty": "số lượng", "dims": "kích thước", "mass": "khối lượng", "posture": "tư thế", "stacking": "chồng",
               "fragile": "dễ vỡ"}
UNIT_LABEL = {"carton": "thùng", "pallet": "pallet", "piece": "kiện"}
_TYPES = {"qty": TypeAdapter(int), "dims": TypeAdapter(Dims), "mass": TypeAdapter(float),
          "posture": TypeAdapter(Posture), "stacking": TypeAdapter(Stacking), "fragile": TypeAdapter(bool)}


class AnswerError(ValueError):
    """An answer the lot cannot take; the message says why, in the user's language."""


@dataclass
class _Draft:
    title: str
    question: str
    fields: list[str]
    options: list[Option] = field(default_factory=list)


# --- finding --------------------------------------------------------------------------------------------------------


def find_points(lot: Lot) -> list[Point]:
    """Every point of `lot`: the answered ones as they are, and new ones for the fields that need review and no
    answered point covers; numbered 1.. in page order."""
    answered = [p for p in lot.points if p.resolved_at is not None]
    covered = {f for p in answered for f in p.fields}
    order = {line.id: i for i, line in enumerate(lot.lines)}
    drafts = _drafts(lot, covered)
    ranked: list[tuple[tuple[int, int], Point | _Draft]] = [(_place(p.fields, order, lot), p) for p in answered]
    ranked += [(_place(d.fields, order, lot), d) for d in drafts]
    ranked.sort(key=lambda item: item[0])
    out = []
    for n, (_, p) in enumerate(ranked, start=1):
        if isinstance(p, Point):
            out.append(p.model_copy(update={"id": n}))
        else:
            out.append(Point(id=n, title=p.title, question=p.question, fields=p.fields, options=p.options))
    return out


def refresh(lot: Lot) -> Lot:
    """A copy of `lot` with its points found again (`find_points`)."""
    return lot.model_copy(update={"points": find_points(lot)}, deep=True)


def _place(fields: list[str], order: dict[str, int], lot: Lot) -> tuple[int, int]:
    """Page position of a point: its first row, then its first field; the dup point of a code comes first in its row,
    the lot-wide point last."""
    if len({f.rsplit(".", 1)[0] for f in fields}) > 1 and all(f.rsplit(".", 1)[1] in MARKS for f in fields):
        return (len(lot.lines), 0)  # the lot-wide point of the engine's defaults
    places = []
    for f in fields:
        line_id, name = f.rsplit(".", 1)
        if line_id in order:
            places.append((order[line_id], FIELD_NAMES.index(name) if name in FIELD_NAMES else -1))
    if not places:
        return (len(lot.lines), 0)
    return min(places)


def _drafts(lot: Lot, covered: set[str]) -> list[_Draft]:
    def open_(line: Line, name: str) -> bool:
        return f"{line.id}.{name}" not in covered and getattr(line, name).status == "needs_review"

    drafts: list[_Draft] = []
    taken: set[str] = set()

    by_sku: dict[str, list[Line]] = {}
    for line in lot.lines:
        by_sku.setdefault(line.sku, []).append(line)
    for sku, lines in by_sku.items():
        if len(lines) > 1 and any(open_(x, "qty") for x in lines) and not _not_shipped(lines[0].qty):
            drafts.append(_repeated(sku, lines))
            taken |= {f"{x.id}.qty" for x in lines}

    defaults: list[str] = []
    grouped: dict[tuple[Any, ...], _Draft] = {}
    for line in lot.lines:
        names = [n for n in FIELD_NAMES if open_(line, n) and f"{line.id}.{n}" not in taken]
        if not names:
            continue
        if "qty" in names and _not_shipped(line.qty):
            drafts.append(_shipped(line))
            names.remove("qty")
        if line.unit == "pallet" and any(n in names for n in ("qty", "dims", "mass")):
            pallet = [n for n in ("qty", "dims", "mass") if n in names]
            drafts.append(_pallet(line, pallet))
            names = [n for n in names if n not in pallet]
        marks = [n for n in names if n in MARKS and getattr(line, n).value is not None]
        if marks:
            drafts.append(_marks(line, marks))
            names = [n for n in names if n not in marks]
        for name in names:
            f = getattr(line, name)
            if not f.sources and name in MARKS:
                defaults.append(f"{line.id}.{name}")
                continue
            cause, options = _cause(name, f, line)
            key = (line.sku, name, cause, tuple((o.label, repr(sorted(o.sets.items()))) for o in options))
            fid = f"{line.id}.{name}"
            if key in grouped:
                grouped[key].fields.append(fid)
                for option in grouped[key].options:
                    option.sets[fid] = next(iter(option.sets.values()))
            else:
                grouped[key] = _field_draft(line, name, cause, options, fid)
                drafts.append(grouped[key])
    if defaults:
        drafts.append(_defaults(lot, defaults))
    return drafts


def _not_shipped(f: LotField[Any]) -> bool:
    return any(s.raw is not None and s.raw.startswith(NOT_SHIPPED) for s in f.sources)


# --- the points, by cause -------------------------------------------------------------------------------------------


def _repeated(sku: str, lines: list[Line]) -> _Draft:
    rows = "; ".join(f"{_where(x.qty)}: {fmt('qty', x.qty.value, x)}" for x in lines)
    keep = Option(label=f"Giữ cả {len(lines)} dòng",
                  sets={f"{x.id}.qty": x.qty.value for x in lines if x.qty.value is not None},
                  sources=[s for x in lines for s in x.qty.sources])
    drops = [Option(label=f"Bỏ dòng {_where(x.qty)} ({fmt('qty', x.qty.value, x)})",
                    sets={f"{x.id}.line": DROP} | {f"{y.id}.qty": y.qty.value for y in lines
                                                    if y is not x and y.qty.value is not None},
                    sources=x.qty.sources) for x in lines]
    return _Draft(title=f"{sku}: {len(lines)} dòng cùng mã",
                  question=f"Bảng kê hàng có {len(lines)} dòng cùng mã {sku} ({rows}). Đây là các đợt hàng khác nhau "
                           f"(giữ cả {len(lines)} dòng) hay một dòng ghi trùng?",
                  fields=[f"{x.id}.qty" for x in lines], options=[keep, *drops])


def _shipped(line: Line) -> _Draft:
    said = [s for s in line.qty.sources if s.raw is not None and s.raw.startswith(NOT_SHIPPED)]
    listed = [s for s in line.qty.sources if s not in said]
    options = []
    value = line.qty.value if line.qty.value is not None else _first(units.first_int(s.raw) for s in listed)
    if value is not None:
        options.append(Option(label=f"Giữ trong lô: {fmt('qty', value, line)}", sets={f"{line.id}.qty": value},
                              sources=listed))
    options.append(Option(label="Loại khỏi lô", sets={f"{line.id}.line": DROP}, sources=said))
    return _Draft(title=f"{line.sku}: có trong lô hàng không?",
                  question=f"Bảng kê hàng liệt kê {line.sku} ({_where(line.qty)}), nhưng {_files(said)} ghi mã này "
                           "không có trong lô hàng. Giữ hay loại?",
                  fields=[f"{line.id}.qty"], options=options)


def _pallet(line: Line, names: list[str]) -> _Draft:
    values = {n: getattr(line, n).value for n in names}
    given = {n: v for n, v in values.items() if v is not None}
    raw = line.qty.sources[0].raw if line.qty.sources else None
    options = []
    if given:
        label = " · ".join(fmt(n, v, line) for n, v in given.items())
        missing = [FIELD_LABEL[n] for n in names if n not in given]
        options.append(Option(label=f"Xếp theo pallet: {label}" + (f" (nhập thêm {', '.join(missing)})" if missing else ""),
                              sets={f"{line.id}.{n}": _plain(v) for n, v in given.items()},
                              sources=[s for n in names for s in getattr(line, n).sources]))
    return _Draft(title=f"{line.sku}: kiện là pallet",
                  question=f"Bảng kê hàng đếm {line.sku} theo pallet" + (f" (\"{raw}\")" if raw else "")
                           + ". Engine xếp mỗi pallet như một khối. Xếp theo pallet với số liệu dưới đây?",
                  fields=[f"{line.id}.{n}" for n in names], options=options)


def _marks(line: Line, names: list[str]) -> _Draft:
    sources = [s for n in names for s in getattr(line, n).sources]
    raws = ", ".join(dict.fromkeys(f"\"{s.raw}\"" for s in sources if s.raw))
    label = " · ".join(fmt(n, getattr(line, n).value, line) for n in names)
    return _Draft(title=f"{line.sku}: ràng buộc xếp từ nhãn",
                  question=f"Tài liệu của {line.sku} ghi {raws}. Đây là ràng buộc đề xuất, chưa phải dữ liệu đã chốt. "
                           "Áp dụng?",
                  fields=[f"{line.id}.{n}" for n in names],
                  options=[Option(label=f"Áp dụng: {label}", sets={f"{line.id}.{n}": _plain(getattr(line, n).value)
                                                                    for n in names}, sources=sources)])


def _defaults(lot: Lot, fields: list[str]) -> _Draft:
    names = [n for n in MARKS if any(f.endswith(f".{n}") for f in fields)]
    skus = list(dict.fromkeys(x.sku for x in lot.lines if any(f.startswith(f"{x.id}.") for f in fields)))
    label = " · ".join(fmt(n, default_for(n), None) for n in names)
    return _Draft(title=f"{_cap(', '.join(FIELD_LABEL[n] for n in names))} chưa có trong tài liệu",
                  question=f"Không tài liệu nào ghi {', '.join(FIELD_LABEL[n] for n in names)} của "
                           f"{', '.join(skus)}. Dùng mặc định của engine?",
                  fields=fields,
                  options=[Option(label=f"Dùng mặc định: {label}",
                                  sets={f: _plain(default_for(f.rsplit('.', 1)[1])) for f in fields})])


def _field_draft(line: Line, name: str, cause: str, options: list[Option], fid: str) -> _Draft:
    what = FIELD_LABEL[name]
    title, question = {
        "conflict": (f"{line.sku}: {what} khác nhau giữa các tài liệu",
                     f"Các tài liệu ghi {what} của {line.sku} khác nhau. Dùng giá trị nào?"),
        "net": (f"{line.sku}: khối lượng tịnh hay cả bì",
                f"Một tài liệu chỉ ghi khối lượng tịnh (N.W.) của {line.sku}; engine cần khối lượng cả bì một kiện. "
                "Dùng giá trị nào?"),
        "unitless": (f"{line.sku}: {what} không có đơn vị",
                     f"Tài liệu ghi {what} của {line.sku} không kèm đơn vị. Hiểu thế nào?"),
        "missing": (f"{line.sku}: thiếu {what}", f"Không tài liệu nào ghi {what} của {line.sku}. Nhập giá trị."),
        "review": (f"{line.sku}: {what} cần xem lại",
                   f"Không đọc được {what} của {line.sku} từ tài liệu thành một giá trị hợp lệ. Nhập giá trị."),
    }[cause]
    for option in options:
        option.sets = {fid: next(iter(option.sets.values()))}
    return _Draft(title=title, question=question, fields=[fid], options=options)


def _cause(name: str, f: LotField[Any], line: Line) -> tuple[str, list[Option]]:
    """Why a field needs review, and the options its sources give."""
    if not f.sources:
        return "missing", []
    readings = [(v, note, s) for s in f.sources for v, note in _read(name, s.raw)]
    options: list[Option] = []
    for value, note, source in sorted(readings, key=lambda r: r[1] != ""):
        label = fmt(name, value, line) + (f" ({note})" if note else "")
        same = next((o for o in options if o.label == label), None)
        if same is None:
            options.append(Option(label=label, sets={"_": _plain(value)}, sources=[source]))
        elif source not in same.sources:
            same.sources.append(source)
    if f.value is not None and not any(o.sets["_"] == _plain(f.value) for o in options):
        options.insert(0, Option(label=fmt(name, f.value, line), sets={"_": _plain(f.value)}, sources=f.sources))
    notes = {note for _, note, _ in readings}
    plain = {repr(_plain(v)) for v, note, _ in readings if not note}
    if len(plain) > 1:
        return "conflict", options
    if NET in notes:
        return "net", options
    if any(note.startswith(UNITLESS) for note in notes):
        return "unitless", options
    if len(options) > 1:
        return "conflict", options
    return "review", options


NET = "khối lượng tịnh, N.W."
UNITLESS = "không ghi đơn vị, hiểu là"


def _read(name: str, raw: str | None) -> list[tuple[Any, str]]:
    """The values a source's text gives for a field, with a note when the reading is not plain (net, no unit)."""
    if not raw:
        return []
    if name == "qty":
        n = None if raw.startswith(NOT_SHIPPED) else units.first_int(raw)
        return [(n, "")] if n else []
    if name == "dims":
        m = units.dims_m(raw)
        if m is not None:
            return [(d, "")] if (d := _dims(m)) else []
        found = units.dims_numbers(raw)
        if found is None:
            return []
        out = []
        for unit, scale in (("cm", 0.01), ("mm", 0.001)):
            if d := _dims(tuple(x * scale for x in found[0])):
                out.append((d, f"{UNITLESS} {unit}"))
        return out
    if name == "mass":
        net = raw.startswith("N.W.")
        text = raw[4:].strip() if net else raw
        kg = units.mass_kg(text)
        if kg is not None:
            return [(kg, NET if net else "")]
        n = units.unitless_mass(text)
        if n is None:
            return []
        return [(n, NET if net else f"{UNITLESS} kg")]
    return []


def _dims(m: tuple[float, ...]) -> Dims | None:
    if all(0 < x <= MAX_DIM_M for x in m):
        return Dims(L=round(m[0], 6), W=round(m[1], 6), H=round(m[2], 6))
    return None


# --- answering ------------------------------------------------------------------------------------------------------


def answer(lot: Lot, point_id: int, by: str, choice: int | None = None, values: dict[str, Any] | None = None,
           at: str | None = None, restore: dict[str, Line] | None = None) -> Lot:
    """`lot` with point `point_id` answered by `by`: the values of option `choice`, then `values` (the user's own,
    `"<line id>.<field>"` -> value) over them. Every field the point settles that needs review must end confirmed;
    `AnswerError` otherwise, and the lot is left as it was. The answered lot's points are found again.

    A point already answered may be answered again: the new answer replaces the old. Rows the old answer dropped come
    back from `restore` (the lot's documents merged again, line id -> line) before the new answer applies."""
    out = lot.model_copy(deep=True)
    point = next((p for p in out.points if p.id == point_id), None)
    if point is None:
        raise AnswerError(f"Không có câu hỏi H{point_id}")
    if point.resolved_at is not None:
        _undo_drops(out, point, restore or {})
    if choice is not None and not 0 <= choice < len(point.options):
        raise AnswerError(f"Câu hỏi H{point_id} không có lựa chọn {choice + 1}")
    sets = dict(point.options[choice].sets) if choice is not None else {}
    sets.update(values or {})
    if not sets:
        raise AnswerError("Chưa chọn lựa chọn nào, cũng chưa nhập giá trị")
    lines = {x.id: x for x in out.lines}
    allowed = set(point.fields) | {f"{f.rsplit('.', 1)[0]}.line" for f in point.fields}
    for key in sets:
        if key not in allowed:
            raise AnswerError(f"Câu hỏi H{point_id} không xác nhận {key}")
    drops = {key.rsplit(".", 1)[0] for key, v in sets.items() if key.endswith(".line") and v == DROP}
    stamp = at or now()
    for key, value in sets.items():
        line_id, name = key.rsplit(".", 1)
        if name == "line" or line_id in drops:
            continue
        try:
            typed = _TYPES[name].validate_python(value)
        except ValidationError as exc:
            raise AnswerError(f"{key}: giá trị không hợp lệ ({exc.errors()[0]['msg']})") from None
        confirm(getattr(lines[line_id], name), by, typed, stamp)
    for line_id in drops:
        line = lines[line_id]
        out.lines.remove(line)
        out.excluded.append(Excluded(sku=line.sku, description=line.description,
                                     reason=DROPPED_REASON.format(line=line.id), sources=line.qty.sources))
    unsettled = [f for f in point.fields if f.rsplit(".", 1)[0] in lines and f.rsplit(".", 1)[0] not in drops
                 and getattr(lines[f.rsplit(".", 1)[0]], f.rsplit(".", 1)[1]).status == "needs_review"]
    if unsettled:
        words = [f"{FIELD_LABEL[f.rsplit('.', 1)[1]]} của {f.rsplit('.', 1)[0]}" for f in unsettled]
        raise AnswerError(f"Còn thiếu {', '.join(words)}: nhập ở lựa chọn hoặc ở \"Giá trị khác\"")
    point.chosen, point.resolved_by, point.resolved_at = choice, by, stamp
    try:
        checked = Lot.model_validate(out.model_dump())
    except ValidationError as exc:
        raise AnswerError(f"Giá trị không hợp lệ: {exc.errors()[0]['msg']}") from None
    return refresh(checked)


def _undo_drops(lot: Lot, point: Point, restore: dict[str, Line]) -> None:
    """Put back, in document order, the rows the previous answer of `point` dropped."""
    if point.chosen is None:
        return
    dropped = [k.rsplit(".", 1)[0] for k, v in point.options[point.chosen].sets.items() if k.endswith(".line") and v == DROP]
    for line_id in dropped:
        line = restore.get(line_id)
        if line is None:
            raise AnswerError(f"Không lấy lại được dòng {line_id} đã bỏ: tài liệu của lô không còn dòng này")
        lot.lines.append(line.model_copy(deep=True))
        lot.excluded = [e for e in lot.excluded if e.reason != DROPPED_REASON.format(line=line_id)]
    if dropped:
        order = {line_id: i for i, line_id in enumerate(restore)}
        lot.lines.sort(key=lambda x: order.get(x.id, len(order)))
        # other answers on a row back as read are void: its fields are asked again
        back = set(dropped)
        lot.points = [p for p in lot.points if p is point or not any(f.rsplit(".", 1)[0] in back for f in p.fields)]


def carry(old: Lot, new: Lot) -> Lot:
    """`new` (the lot read again after a document was added) keeping what the user confirmed in `old`. A confirmed
    field stays confirmed when every source the new reading gives was already there, or the new reading agrees with
    the confirmed value; a source that is new and says otherwise sends the field back to review, to be asked again
    (ADR-0001). Answered points whose fields all stay confirmed are kept; rows the user dropped stay dropped."""
    out = new.model_copy(deep=True)
    before = {x.id: x for x in old.lines}
    for line in out.lines:
        was = before.get(line.id)
        if was is None or was.sku != line.sku:
            continue
        for name in FIELD_NAMES:
            f, w = getattr(line, name), getattr(was, name)
            if w.status != "confirmed":
                continue
            known = all(s in w.sources for s in f.sources)
            agrees = f.value is not None and _plain(f.value) == _plain(w.value) and f.status == "extracted"
            if known or agrees:
                setattr(line, name, w.model_copy(update={"sources": _union(w.sources, f.sources)}, deep=True))
    keep = []
    lines = {x.id: x for x in out.lines}
    for p in old.points:
        if p.resolved_at is None:
            continue
        dropped = [k.rsplit(".", 1)[0] for o in ([p.options[p.chosen]] if p.chosen is not None else [])
                   for k, v in o.sets.items() if k.endswith(".line") and v == DROP]
        for line_id in dropped:
            if line_id in lines:
                line = lines.pop(line_id)
                out.lines.remove(line)
                out.excluded.append(Excluded(sku=line.sku, description=line.description,
                                             reason=DROPPED_REASON.format(line=line.id), sources=line.qty.sources))
        if all(f.rsplit(".", 1)[0] in dropped or (f.rsplit(".", 1)[0] in lines and getattr(
                lines[f.rsplit(".", 1)[0]], f.rsplit(".", 1)[1]).status == "confirmed") for f in p.fields):
            keep.append(p)
    for e in old.excluded:  # rows the user took out from the table (src.lot.edit.drop_line), out again
        line_id = dropped_id(e.reason)
        if line_id is not None and line_id in lines:
            line = lines.pop(line_id)
            out.lines.remove(line)
            out.excluded.append(e.model_copy(deep=True))
    for line in old.lines:  # rows the user added: no document gives them, so the merge does not either
        if is_manual(line):
            taken = {x.id for x in out.lines}
            out.lines.append(line.model_copy(update={"id": unique_id(line.id, taken)}, deep=True))
    out.points = keep
    return refresh(out)


def is_manual(line: Line) -> bool:
    """A row the user added: no field has a source (a row read from a document always has its quantity's)."""
    return not any(f.sources for f in line.fields().values())


def dropped_id(reason: str) -> str | None:
    """The line id of an `Excluded` the user dropped (`DROPPED_REASON`), else None."""
    head, tail = DROPPED_REASON.split("{line}")
    if reason.startswith(head) and reason.endswith(tail) and len(reason) > len(head) + len(tail):
        return reason[len(head):len(reason) - len(tail)]
    return None


def unique_id(wanted: str, taken: set[str]) -> str:
    """`wanted`, or `wanted-2`, `-3`... when the lot has it already (as `line_ids`)."""
    if wanted not in taken:
        return wanted
    n = 2
    while f"{wanted}-{n}" in taken:
        n += 1
    return f"{wanted}-{n}"


def forget(lot: Lot, file: str) -> Lot:
    """A copy of `lot` before it is merged again without document `file` (removed): every field confirmed with a
    source in that file loses its confirmation, so `carry` takes it as the remaining documents give it, asked again if
    they disagree or say nothing. Kept: fields confirmed on other sources, and a quantity, size or mass the user typed
    (a value no source of that file reads as). Handling marks are read by the model, not from the text: any source of
    the file voids them."""
    out = lot.model_copy(deep=True)
    for line in out.lines:
        for name in FIELD_NAMES:
            f = getattr(line, name)
            gone = [s for s in f.sources if s.file == file]
            if f.status != "confirmed" or not gone:
                continue
            if name in MARKS or any(_plain(v) == _plain(f.value) for s in gone for v, _ in _read(name, s.raw)):
                f.status, f.confirmed_by, f.confirmed_at = "needs_review", None, None
            else:
                f.sources = [s for s in f.sources if s.file != file]
    return out


def _union(a: list[Source], b: list[Source]) -> list[Source]:
    return a + [s for s in b if s not in a]


# --- wording --------------------------------------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """A value as JSON holds it (an option's `sets`)."""
    return value.model_dump() if hasattr(value, "model_dump") else value


def _num(x: float, digits: int) -> str:
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def fmt(name: str, value: Any, line: Line | None) -> str:
    """A value as the screens write it (docs/product/ux.md §2)."""
    if value is None:
        return "trống"
    if name == "qty":
        return f"{value} {UNIT_LABEL[line.unit] if line else 'kiện'}"
    if name == "dims":
        d = value if isinstance(value, Dims) else Dims(**value)
        return f"{_num(d.L, 2)} × {_num(d.W, 2)} × {_num(d.H, 2)} m"
    if name == "mass":
        return f"{_num(value, 1).removesuffix(',0')} kg"
    if name == "posture":
        return "chỉ đứng" if value == "upright" else "được lật"
    if name == "stacking":
        s = value if isinstance(value, Stacking) else Stacking(**value)
        return {"free": "chồng tự do", "none": "không chồng"}.get(s.kind) or f"chồng tối đa {s.tiers} tầng"
    return "dễ vỡ" if value else "không dễ vỡ"


def _where(f: LotField[Any]) -> str:
    return f.sources[0].where if f.sources else "?"


def _files(sources: list[Source]) -> str:
    return ", ".join(dict.fromkeys(s.file for s in sources))


def _first(values: Any) -> Any:
    return next((v for v in values if v is not None), None)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]
