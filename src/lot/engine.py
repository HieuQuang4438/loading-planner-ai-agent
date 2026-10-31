"""The one way from the product's lot to the engine (ADR-0001, docs/product/brief.md §2.3): only confirmed fields go
through. `to_instance` refuses a lot with any field not confirmed; the container types and their costs come with the
run, not with the lot."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from src.lot.schema import Lot, LotField, Posture, Stacking
from src.model import ContainerType, Instance, ItemLine

DEFAULT_POSTURE: Posture = "upright"  # what a confirmed "no document says" means (docs/product/ux.md §4)
DEFAULT_STACKING = Stacking(kind="free")


class LotNotReady(ValueError):
    """The lot has fields not confirmed yet; `fields` lists them as `"<line id>.<field>"`."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__(f"{len(fields)} trường chưa xác nhận: {', '.join(fields[:10])}{' …' if len(fields) > 10 else ''}")
        self.fields = fields


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def confirm(field: LotField[Any], by: str, value: Any = None, at: str | None = None) -> None:
    """Confirm `field` as `by`, with `value` when given (the user's answer) else its current one. A field without a
    value takes no confirmation without one."""
    if value is not None:
        field.value = value
    if field.value is None:
        raise ValueError("a field without a value cannot be confirmed; give the value")
    field.status, field.confirmed_by, field.confirmed_at = "confirmed", by, at or now()


def default_for(name: str) -> Any:
    """The engine default a user confirms for a field no document gives (posture, stacking, fragile)."""
    return {"posture": DEFAULT_POSTURE, "stacking": DEFAULT_STACKING, "fragile": False}[name]


def confirm_rest(lot: Lot, by: str, at: str | None = None) -> None:
    """The user's "the lot is right" once no field needs review: every `extracted` field becomes `confirmed`. Refused
    while a field still needs review."""
    review = [f"{line.id}.{name}" for line in lot.lines for name, f in line.fields().items() if f.status == "needs_review"]
    if review:
        raise LotNotReady(review)
    stamp = at or now()
    for line in lot.lines:
        for f in line.fields().values():
            if f.status == "extracted":
                confirm(f, by, at=stamp)


def to_instance(lot: Lot, container_types: tuple[ContainerType, ...]) -> Instance:
    """The engine's instance of a fully confirmed lot; `LotNotReady` otherwise."""
    open_fields = lot.open_fields()
    if open_fields:
        raise LotNotReady(open_fields)
    pieces = sum(line.qty.value for line in lot.lines)
    items = []
    for line in lot.lines:
        dims, stacking = line.dims.value, line.stacking.value
        if stacking.kind == "free":
            tiers, unlimited, load = pieces, True, None  # an effective cap no stack reaches, as src.formats does
        elif stacking.kind == "limited":
            tiers, unlimited, load = stacking.tiers, False, None
        else:
            tiers, unlimited, load = 1, False, 0.0
        items.append(ItemLine(id=line.id, qty=line.qty.value, L=dims.L, W=dims.W, H=dims.H, mass=line.mass.value,
                              tippable=line.posture.value == "tippable", tiers=tiers, load=load,
                              tiers_unlimited=unlimited))
    return Instance(name=_engine_name(lot.name), container_types=tuple(container_types), items=tuple(items),
                    meta={"lot": lot.name})


def _engine_name(name: str) -> str:
    """The engine's lot name: letters, digits, `_`, `.`, `-` only (src.web.lots), not starting with `.`; Vietnamese
    marks dropped ("Lô xuất" -> "Lo-xuat")."""
    plain = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    safe = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9_.-]", "-", plain)).strip("-.") or "lot"
    return safe[:80]
