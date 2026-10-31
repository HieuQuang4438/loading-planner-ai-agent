"""The product's lot (ADR-0001): item lines whose every field carries its value, status and sources, the points the
user must confirm, and the codes left out of the lot. Values are normalised (m, kg); the documents' own text, units
included, is in `Source.raw`. A whole lot is one JSON document with `schema_version`.

What fills it is elsewhere: reading documents, finding conflicts. What runs it: `src.lot.engine.to_instance`.
"""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
NOT_SHIPPED = "not in shipment"  # starts `Source.raw` of a document saying a packing-list code is not shipped
MAX_DIM_M = 20.0  # a side longer than any container (45HC: 13.56 m) is a reading error, refused at once

Status = Literal["extracted", "needs_review", "confirmed"]
PieceUnit = Literal["carton", "pallet", "piece"]
Posture = Literal["upright", "tippable"]  # upright: only standing, turns about the vertical; tippable: may also lie
T = TypeVar("T")


class Source(BaseModel):
    """Where a value was read: the file, the place in it, and the text as written there (None: the place is empty)."""

    model_config = ConfigDict(extra="forbid")

    file: str
    where: str  # "Sheet1 · dòng 5", "trang 1", "nhãn thùng"
    raw: str | None


class Dims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    L: float = Field(gt=0, le=MAX_DIM_M)
    W: float = Field(gt=0, le=MAX_DIM_M)
    H: float = Field(gt=0, le=MAX_DIM_M)


class Stacking(BaseModel):
    """What may rest on a piece: `free` (no limit), `limited` (at most `tiers` pieces high, itself included), `none`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["free", "limited", "none"]
    tiers: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _tiers_with_limited_only(self) -> Stacking:
        if (self.kind == "limited") != (self.tiers is not None):
            raise ValueError("tiers is given for kind 'limited' only, and always then")
        return self


class LotField(BaseModel, Generic[T]):
    """One field of a line. `value` None: no document gives it; such a field is `needs_review` until confirmed."""

    model_config = ConfigDict(extra="forbid")

    value: T | None
    status: Status
    sources: list[Source] = []
    confirmed_by: str | None = None
    confirmed_at: str | None = None  # ISO 8601, UTC

    @field_validator("status")
    @classmethod
    def _missing_value_needs_review(cls, status: str, info: Any) -> str:
        if info.data.get("value") is None and status != "needs_review":
            raise ValueError("a field without a value is needs_review")
        return status


class Line(BaseModel):
    """One item line. `id` is the engine's line id (unique in the lot, from `sku`); `sku` is the code as written."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[^#\s]+$")  # the engine names a piece "<line id>#<n>"
    sku: str
    description: str = ""
    unit: PieceUnit = "carton"
    qty: LotField[int]
    dims: LotField[Dims]
    mass: LotField[float]  # kg, one piece, gross
    posture: LotField[Posture]
    stacking: LotField[Stacking]
    fragile: LotField[bool]  # shown to the user; the engine does not read it

    @field_validator("qty")
    @classmethod
    def _positive_qty(cls, f: LotField[int]) -> LotField[int]:
        if f.value is not None and f.value <= 0:
            raise ValueError("qty must be > 0")
        return f

    @field_validator("mass")
    @classmethod
    def _positive_mass(cls, f: LotField[float]) -> LotField[float]:
        if f.value is not None and f.value <= 0:
            raise ValueError("mass must be > 0")
        return f

    def fields(self) -> dict[str, LotField[Any]]:
        return {name: getattr(self, name) for name in FIELD_NAMES}


FIELD_NAMES = ("qty", "dims", "mass", "posture", "stacking", "fragile")


class Option(BaseModel):
    """One answer to a point: a label, the values it sets (`"<line id>.<field>"` -> value) and where they come from.
    `"<line id>.line": "drop"` takes the line out of the lot (src.lot.review)."""

    model_config = ConfigDict(extra="forbid")

    label: str
    sets: dict[str, Any] = {}
    sources: list[Source] = []


class Point(BaseModel):
    """Something the user must confirm (docs/product/ux.md §4). `fields`: what it settles, as `"<line id>.<field>"`."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    title: str
    question: str
    fields: list[str]
    options: list[Option] = []
    chosen: int | None = None  # index into `options`; None: open (or answered with a value of the user's own)
    resolved_by: str | None = None
    resolved_at: str | None = None


class Excluded(BaseModel):
    """A code the documents name that is not in the lot, and why."""

    model_config = ConfigDict(extra="forbid")

    sku: str
    description: str = ""
    reason: str
    sources: list[Source] = []


class Lot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    name: str
    lines: list[Line]
    points: list[Point] = []
    excluded: list[Excluded] = []

    @field_validator("lines")
    @classmethod
    def _unique_line_ids(cls, lines: list[Line]) -> list[Line]:
        ids = [line.id for line in lines]
        if len(ids) != len(set(ids)):
            raise ValueError("line ids must be unique")
        return lines

    def open_fields(self) -> list[str]:
        """Every field not yet confirmed, as `"<line id>.<field>"`, in page order."""
        return [f"{line.id}.{name}" for line in self.lines for name, f in line.fields().items() if f.status != "confirmed"]

    def open_points(self) -> list[Point]:
        return [p for p in self.points if p.resolved_at is None]


def line_ids(skus: list[str]) -> list[str]:
    """Engine line ids for `skus` in order: the code itself, then `-2`, `-3`... when it repeats; spaces and `#` become
    `-`. The original code stays in `Line.sku`."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for sku in skus:
        base = "".join("-" if c.isspace() or c == "#" else c for c in sku.strip()) or "line"
        seen[base] = seen.get(base, 0) + 1
        candidate = base if seen[base] == 1 else f"{base}-{seen[base]}"
        while candidate in out:  # a code that already ends in "-2"
            seen[base] += 1
            candidate = f"{base}-{seen[base]}"
        out.append(candidate)
    return out
