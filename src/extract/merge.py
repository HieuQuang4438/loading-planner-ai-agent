"""The documents' readings merged into a lot (ADR-0001), by fixed rules, the same however the user asks
(docs/product/brief.md §2.3). Each packing-list row is a line; specs and labels add sources to every line of their
code. A field is `extracted` only when its sources agree and none is in doubt; otherwise `needs_review`, and when the
sources disagree its value is left empty: the user chooses (words the question), never this code.

Doubt, by rule: a size or mass without a unit that matches no other source; a net mass only; a quantity counted in
pallets (what a pallet holds must be confirmed); a quantity on a packing-list row whose code is on another row too
(two rows or one, src.lot.review asks); a handling mark read from a label photo (a proposed constraint,
docs/product/brief.md §2.1). A size or mass on a label that agrees with the other sources is extracted like any other."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.extract import units
from src.extract.readings import DocumentReading, ItemReading
from src.lot.schema import NOT_SHIPPED, Dims, Excluded, Line, Lot, LotField, Source, Stacking, line_ids


@dataclass(frozen=True)
class Doc:
    """One document's reading and its file name."""

    file: str
    reading: DocumentReading


@dataclass
class _Evidence:
    """What the sources of one field say: the values that agree or not, the doubts, every source."""

    values: list[Any] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    doubt: bool = False

    def add(self, source: Source, value: Any = None, doubt: bool = False) -> None:
        self.sources.append(source)
        if value is not None:
            self.values.append(value)
        self.doubt = self.doubt or doubt

    def field(self) -> LotField[Any]:
        distinct = []
        for v in self.values:
            if not any(_same(v, d) for d in distinct):
                distinct.append(v)
        if len(distinct) == 1 and not self.doubt:
            return LotField(value=distinct[0], status="extracted", sources=self.sources)
        return LotField(value=distinct[0] if len(distinct) == 1 else None, status="needs_review", sources=self.sources)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, Dims) and isinstance(b, Dims):  # a carton's sides may be listed in any order
        return all(abs(x - y) < 1e-6 for x, y in zip(sorted((a.L, a.W, a.H)), sorted((b.L, b.W, b.H))))
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < 1e-6
    return a == b


def merge(name: str, docs: list[Doc]) -> Lot:
    rows = [(d, r) for d in docs if d.reading.kind == "packing_list" for r in d.reading.items if r.in_shipment is not False]
    in_rows = {id(r) for _, r in rows}  # by identity: two rows may read the same
    refs = [(d, r) for d in docs for r in d.reading.items if id(r) not in in_rows]
    ids = line_ids([r.sku for _, r in rows])
    repeated = {sku for sku in (r.sku for _, r in rows) if sum(1 for _, x in rows if x.sku == sku) > 1}
    lines = [_line(line_id, doc, row, [(d, r) for d, r in refs if r.sku == row.sku], row.sku in repeated)
             for line_id, (doc, row) in zip(ids, rows)]
    shipped = {r.sku for _, r in rows}
    excluded = []
    # No packing list read (none given, or it failed): nothing is left out, the codes wait for one.
    has_list = any(d.reading.kind == "packing_list" for d in docs)
    for sku in dict.fromkeys(r.sku for _, r in refs if has_list and r.sku not in shipped):
        said = [(d, r) for d, r in refs if r.sku == sku]
        not_shipped = [(d, r) for d, r in said if r.in_shipment is False]
        reason = ("Tài liệu ghi không có trong lô hàng" if not_shipped
                  else "Bảng kê hàng không có mã này, nên không có số lượng")
        excluded.append(Excluded(sku=sku, description=said[0][1].description or "", reason=reason,
                                 sources=[_source(d, r, r.qty_text) for d, r in (not_shipped or said)]))
    return Lot(name=name, lines=lines, excluded=excluded)


def _source(doc: Doc, reading: ItemReading, raw: str | None) -> Source:
    return Source(file=doc.file, where=reading.where, raw=raw)


def _line(line_id: str, doc: Doc, row: ItemReading, refs: list[tuple[Doc, ItemReading]], repeated: bool) -> Line:
    unit = row.unit or "carton"
    everyone = [(doc, row)] + refs
    label = {id(r) for d, r in everyone if d.reading.kind == "label"}

    qty = _Evidence()
    qty.add(_source(doc, row, row.qty_text), units.first_int(row.qty_text), doubt=unit == "pallet" or repeated)
    for d, r in refs:
        if r.in_shipment is False:  # a spec saying "not shipped" against a packing-list row: the user decides
            qty.add(_source(d, r, f"{NOT_SHIPPED}: {r.qty_text}" if r.qty_text else NOT_SHIPPED), doubt=True)

    dims, mass, posture, stacking, fragile = _Evidence(), _Evidence(), _Evidence(), _Evidence(), _Evidence()
    for d, r in everyone:
        in_label = id(r) in label
        if r.dims_text and (r.dims_of or "carton") == unit:
            dims.add(_source(d, r, r.dims_text), *_dims_value(r.dims_text), )
        if r.mass_text and (r.mass_of or "carton") == unit:
            kg = units.mass_kg(r.mass_text)
            if r.mass_kind == "net":
                mass.add(_source(d, r, f"N.W. {r.mass_text}"), doubt=True)  # packing goes by gross mass
            elif kg is None:
                mass.add(_source(d, r, r.mass_text), doubt=True)  # no unit: never guessed
            else:
                mass.add(_source(d, r, r.mass_text), kg)
        if r.upright_text:
            posture.add(_source(d, r, r.upright_text), "upright", doubt=in_label)
        if r.no_stack or r.stack_limit:
            value = Stacking(kind="none") if r.no_stack else Stacking(kind="limited", tiers=r.stack_limit)
            stacking.add(_source(d, r, r.stack_text), value, doubt=in_label)
        if r.fragile_text:
            fragile.add(_source(d, r, r.fragile_text), True, doubt=in_label)
    _settle_unitless_dims(dims)
    _settle_unitless_mass(mass, everyone, unit)
    return Line(id=line_id, sku=row.sku, description=row.description or "", unit=unit, qty=qty.field(),
                dims=dims.field(), mass=mass.field(), posture=posture.field(), stacking=stacking.field(),
                fragile=fragile.field())


def _dims_value(text: str) -> tuple[Dims | None, bool]:
    """(value, doubt) of a size: no unit is a doubt until another source settles it (`_settle_unitless_dims`)."""
    m = units.dims_m(text)
    if m is None:
        return None, True
    try:
        return Dims(L=m[0], W=m[1], H=m[2]), False
    except ValueError:  # out of range: a reading error, shown to the user with its source
        return None, True


def _settle_unitless_dims(ev: _Evidence) -> None:
    """A size written without a unit that equals the one size the other sources agree on is no longer in doubt."""
    if not ev.doubt or not ev.values:
        return
    first = ev.values[0]
    if not all(_same(v, first) for v in ev.values):
        return
    target = (first.L, first.W, first.H)
    unresolved = [s for s in ev.sources if units.dims_m(s.raw) is None and not units.unitless_matches(s.raw, target)]
    ev.doubt = bool(unresolved)


def _settle_unitless_mass(ev: _Evidence, everyone: list[tuple[Doc, ItemReading]], unit: str) -> None:
    """A mass without a unit (`25`) equal to the one gross mass the other sources agree on is no longer in doubt;
    a net mass still is."""
    if not ev.doubt or not ev.values or not all(_same(v, ev.values[0]) for v in ev.values):
        return
    if any(r.mass_kind == "net" and r.mass_text and (r.mass_of or "carton") == unit for _, r in everyone):
        return
    for d, r in everyone:
        if r.mass_text and units.mass_kg(r.mass_text) is None and units.unitless_mass(r.mass_text) != ev.values[0]:
            return
    ev.doubt = False
