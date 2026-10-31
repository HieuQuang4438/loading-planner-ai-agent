"""Lots the client sends as JSON (`lot_from_client`)."""
from __future__ import annotations

import re
from typing import Any

from src.formats import Issue, instance_from_dict, instance_issues, line_from_dict
from src.model import Instance
from src.web.errors import BadRequest

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")
MAX_CLIENT_ITEMS = 20_000  # a client lot above this is refused (6A): the biggest benchmark lot has ~5000
MAX_CLIENT_LINES = 1_000


# --- lots from the client ---------------------------------------------------------------------------

_LINE_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,), "qty": (int,), "L": (int, float), "W": (int, float), "H": (int, float), "mass": (int, float),
    "tippable": (bool,), "tiers": (int, type(None)),
}
_TYPE_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,), "L": (int, float), "W": (int, float), "H": (int, float), "door_w": (int, float),
    "door_h": (int, float), "max_mass": (int, float), "cost": (int, float),
}


def lot_issues(data: Any) -> list[Issue]:
    """Every problem of a lot sent as JSON (the engine's JSON format, docs/reference/data-model.md), all at once: shape and types,
    each line's own posture checks, then `instance_issues` on the entries that passed, then the client
    size limits. Empty: the lot can run."""
    return read_client_lot(data)[1]


def lot_from_client(data: Any) -> Instance:
    """The instance of a lot sent as JSON; BadRequest with every problem when it cannot run."""
    instance, issues = read_client_lot(data)
    if issues:
        raise BadRequest(f"lô có {len(issues)} lỗi", issues)
    assert instance is not None
    return instance


def read_client_lot(data: Any) -> tuple[Instance | None, list[Issue]]:
    """(instance, issues). An entry with a shape or posture problem is left out of the value checks, so its
    problems do not hide those of the others; the instance is None unless every entry is sound."""
    if not isinstance(data, dict):
        return None, [Issue("lot must be a JSON object", code="lot_not_object")]
    issues: list[Issue] = []
    name = data.get("name")
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or name.startswith("."):
        issues.append(Issue("name must be letters, digits, '_', '.', '-' (not starting with '.')", field="name",
                            code="name_invalid"))
    types, items = data.get("container_types"), data.get("items")
    if not isinstance(types, list):
        issues.append(Issue("container_types must be a list", field="container_types", code="not_list"))
        types = []
    if not isinstance(items, list):
        issues.append(Issue("items must be a list", field="items", code="not_list"))
        items = []
    good_types, good_items = [], []
    for i, t in enumerate(types):
        found = _shape_issues(t, _TYPE_TYPES, set(), container=_label(t, i))
        issues += found
        if not found:
            good_types.append(t)
    for i, line in enumerate(items):
        found = _shape_issues(line, _LINE_TYPES, {"load", "orientations", "tiltable"}, line=_label(line, i))
        if not found:
            try:  # ItemLine's own checks (posture set, `tiltable` against `tippable`): one issue per bad line
                line_from_dict(line)
            except (TypeError, ValueError) as exc:
                found = [Issue(str(exc), line=_label(line, i), code="posture_invalid",
                               field="orientations" if "orientations" in line else "tippable")]
        issues += found
        if not found:
            good_items.append(line)
    try:
        instance = instance_from_dict({"name": name if isinstance(name, str) else "", "container_types": good_types,
                                       "items": good_items, "meta": data.get("meta", {})})
    except (TypeError, ValueError, KeyError) as exc:  # not expected once every entry passed its own checks
        return None, issues + [Issue(str(exc), code="lot_invalid")]
    left_out = len(good_types) < len(types), len(good_items) < len(items)
    for issue in instance_issues(instance):
        if issue.code == "container_types_none" and left_out[0] or issue.code == "items_none" and left_out[1]:
            continue  # empty only because its entries are already reported
        issues.append(issue)
    if instance.n_items > MAX_CLIENT_ITEMS:
        issues.append(Issue(f"lot has {instance.n_items} items; at most {MAX_CLIENT_ITEMS}", field="qty",
                            code="lot_too_many_items", params={"n": instance.n_items, "max": MAX_CLIENT_ITEMS}))
    if len(instance.items) > MAX_CLIENT_LINES:
        issues.append(Issue(f"lot has {len(instance.items)} item lines; at most {MAX_CLIENT_LINES}", field="items",
                            code="lot_too_many_lines", params={"n": len(instance.items), "max": MAX_CLIENT_LINES}))
    return (None if issues else instance), issues


def _label(entry: Any, index: int) -> str:
    """The id of a JSON entry, or its position (`#1`, `#2`, ...) when it has none."""
    return entry["id"] if isinstance(entry, dict) and isinstance(entry.get("id"), str) else f"#{index + 1}"


def _shape_issues(
    entry: Any, required: dict[str, tuple[type, ...]], optional: set[str], **where: str,
) -> list[Issue]:
    if not isinstance(entry, dict):
        return [Issue("must be a JSON object", code="not_object", **where)]
    issues = []
    for key, kinds in required.items():
        value = entry.get(key)
        if key not in entry:
            issues.append(Issue(f"missing {key}", field=key, code="field_missing", **where))
        elif isinstance(value, bool) and bool not in kinds or not isinstance(value, kinds):
            issues.append(Issue(f"{key} has the wrong type", field=key, code="field_type", **where))
    for key in sorted(entry.keys() - required.keys() - optional):
        issues.append(Issue(f"unknown field {key}", field=key, code="field_unknown", **where))
    if "load" in entry and entry["load"] is not None and (isinstance(entry["load"], bool) or not isinstance(entry["load"], (int, float))):
        issues.append(Issue("load must be a number or null", field="load", code="field_type", **where))
    return issues
