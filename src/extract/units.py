"""Numbers and units as documents write them, to metres and kilograms (ADR-0001: the lot holds normalised values).
Deterministic: the model only copies the text, this module reads it. A number without a unit is not guessed."""
from __future__ import annotations

import re

LENGTH = {"mm": 0.001, "cm": 0.01, "m": 1.0}
MASS = {"g": 0.001, "kg": 1.0, "kgs": 1.0, "t": 1000.0, "tấn": 1000.0}
_NUMBER = r"\d+(?:[.,]\d+)?"
_DIMS = re.compile(rf"({_NUMBER})\s*(mm|cm|m)?\s*[x×*]\s*({_NUMBER})\s*(mm|cm|m)?\s*[x×*]\s*({_NUMBER})\s*(mm|cm|m)?\b",
                   re.IGNORECASE)
_MASS = re.compile(rf"({_NUMBER})\s*(kgs|kg|g|tấn|t)?\b", re.IGNORECASE)
_INT = re.compile(r"\d+")


def number(text: str) -> float:
    """`12,5` and `12.5` are both 12.5 (a document may use either decimal mark)."""
    return float(text.replace(",", "."))


def dims_numbers(text: str | None) -> tuple[tuple[float, float, float], str | None] | None:
    """The three numbers of a size such as `60x40x50 cm`, `800 x 600 x 500 mm`, `50*50*60`, and the unit written
    after the last (or any) of them; None when the text holds no size."""
    if not text:
        return None
    m = _DIMS.search(text)
    if m is None:
        return None
    units = [u.lower() for u in (m.group(2), m.group(4), m.group(6)) if u]
    if len(set(units)) > 1:
        return None  # mixed units in one size: not read
    return (number(m.group(1)), number(m.group(3)), number(m.group(5))), (units[0] if units else None)


def dims_m(text: str | None) -> tuple[float, float, float] | None:
    """A size in metres, or None when there is none or it has no unit."""
    found = dims_numbers(text)
    if found is None or found[1] is None:
        return None
    (a, b, c), unit = found
    f = LENGTH[unit]
    return round(a * f, 6), round(b * f, 6), round(c * f, 6)


def unitless_matches(text: str | None, dims: tuple[float, float, float]) -> bool:
    """Whether a size written without a unit (`50*50*60`) equals `dims` (m) read in mm, cm or m: then it agrees with a
    source that has the unit, and nothing is guessed."""
    found = dims_numbers(text)
    if found is None or found[1] is not None:
        return False
    return any(all(abs(x * f - y) < 1e-6 for x, y in zip(found[0], dims)) for f in LENGTH.values())


def mass_kg(text: str | None) -> float | None:
    """A mass in kg (`12 kg`, `12.5 KG`, `160kg`), or None when there is none or it has no unit (`25`)."""
    if not text:
        return None
    for m in _MASS.finditer(text):
        if m.group(2):
            return round(number(m.group(1)) * MASS[m.group(2).lower()], 6)
    return None


def unitless_mass(text: str | None) -> float | None:
    """The number of a mass written without a unit (`25`), else None."""
    if not text:
        return None
    m = _MASS.search(text)
    return number(m.group(1)) if m and not m.group(2) else None


def first_int(text: str | None) -> int | None:
    """The first whole number of a quantity (`200 thùng`, `10 pallet x 24 thùng` -> 10)."""
    if not text:
        return None
    m = _INT.search(text)
    return int(m.group(0)) if m else None
