"""JSON files for instances and solutions, and data checks on an instance.

Writers are deterministic: same object, same bytes, on every OS (LF line ends, fixed key order).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field as dc_field
from pathlib import Path
from typing import Any

from src.model import ContainerType, Instance, ItemLine, Params, Placement, Solution, UsedContainer

EPS = 1e-9


# The field `tippable` was called `tiltable` until bench-v3. Readers take both; a writer uses the
# old key only for a benchmark version whose committed sha256 was made with it (`src.bench.common`).
OLD_TIPPABLE_KEY = "tiltable"


def instance_to_dict(instance: Instance, old_key: bool = False) -> dict[str, Any]:
    """`old_key`: write `tiltable` instead of `tippable` (bench-v1 and bench-v2 files keep their bytes)."""
    return {
        "name": instance.name,
        "meta": instance.meta,
        "container_types": [asdict(t) for t in instance.container_types],
        "items": [_line_to_dict(line, old_key) for line in instance.items],
    }


def _line_to_dict(line: ItemLine, old_key: bool = False) -> dict[str, Any]:
    """A line as a dict; `orientations` is written only when it differs from the `tippable` default."""
    data = asdict(line)
    if data.pop("tiers_unlimited"):
        data["tiers"] = None
    if old_key:
        data = {(OLD_TIPPABLE_KEY if key == "tippable" else key): value for key, value in data.items()}
    if data["orientations"] is None:
        del data["orientations"]
    else:
        data["orientations"] = list(data["orientations"])
    return data


def instance_from_dict(data: dict[str, Any]) -> Instance:
    return Instance(
        name=data["name"],
        container_types=tuple(ContainerType(**t) for t in data["container_types"]),
        items=tuple(line_from_dict(line, _lot_pieces(data["items"])) for line in data["items"]),
        meta=data.get("meta", {}),
    )


def _lot_pieces(lines: Any) -> int:
    """Piece count of a lot read from JSON; malformed `qty` values count 0 (validation reports them)."""
    try:
        return sum(q for q in (line["qty"] for line in lines) if isinstance(q, int) and not isinstance(q, bool))
    except (TypeError, KeyError):
        return 0


def line_from_dict(data: dict[str, Any], lot_pieces: int = 0) -> ItemLine:
    """`"tiers": null` means no limit: the line gets `tiers_unlimited` and the effective cap `lot_pieces`
    (the lot's piece count, which no stack can exceed; the line's own `qty` when not given)."""
    data = dict(data)
    if "tiers" in data and data["tiers"] is None:
        qty = data.get("qty")
        data["tiers"] = max(1, lot_pieces, qty if isinstance(qty, int) and not isinstance(qty, bool) else 1)
        data["tiers_unlimited"] = True
    if OLD_TIPPABLE_KEY in data:
        old = data.pop(OLD_TIPPABLE_KEY)
        if "tippable" in data and data["tippable"] != old:
            raise ValueError(f"item line {data.get('id')}: `tiltable` and `tippable` differ")
        data["tippable"] = old
    codes = data.get("orientations")
    return ItemLine(**{**data, "orientations": None if codes is None else tuple(codes)})


def solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "instance": solution.instance,
        "params": asdict(solution.params),
        "containers": [asdict(c) for c in solution.containers],
        "placements": [asdict(p) for p in solution.placements],
        "meta": solution.meta,
    }


def solution_from_dict(data: dict[str, Any]) -> Solution:
    return Solution(
        instance=data["instance"],
        params=Params(**data["params"]),
        containers=[UsedContainer(**c) for c in data["containers"]],
        placements=[Placement(**p) for p in data["placements"]],
        meta=data.get("meta", {}),
    )


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(data), encoding="utf-8", newline="\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_instance(path: Path, instance: Instance, old_key: bool = False) -> None:
    write_json(path, instance_to_dict(instance, old_key))


def read_instance(path: Path) -> Instance:
    return instance_from_dict(read_json(path))


def write_solution(path: Path, solution: Solution) -> None:
    write_json(path, solution_to_dict(solution))


def read_solution(path: Path) -> Solution:
    return solution_from_dict(read_json(path))


@dataclass(frozen=True)
class Issue:
    """One data problem; `line` or `container` names the item line or container type it is about, `field` the key.
    `code` and `params` say what is wrong in a form a page can word in its own language;
    `message` stays English for the command line."""

    message: str
    line: str | None = None
    container: str | None = None
    field: str | None = None
    code: str = ""
    params: dict[str, Any] = dc_field(default_factory=dict)


def validate_instance(instance: Instance) -> list[str]:
    """Data problems that make an instance unusable; empty list means valid."""
    return [issue.message for issue in instance_issues(instance)]


def instance_issues(instance: Instance) -> list[Issue]:
    """`validate_instance` with each problem tied to its item line or container type. Every
    problem is reported at once: a line with no problem of its own is checked against the container types
    with none."""
    issues = _validate_container_types(instance.container_types)
    issues += _validate_items(instance.items)
    types = [t for t in instance.container_types if not _type_problem(t)]
    if types:
        for line in instance.items:
            if not _line_problem(line):
                issues += _fit_issues(line, types)
    return issues


def fits_container(line: ItemLine, ctype: ContainerType) -> bool:
    """Whether one item of the line can go into an empty container of this type, alone."""
    return line.mass <= ctype.max_mass + EPS and _fits_shape(line, ctype, door=True)


def _fits_shape(line: ItemLine, ctype: ContainerType, door: bool) -> bool:
    """Whether an allowed orientation of the line lies inside the container (and, with `door`, goes through its door)."""
    for o in line.allowed:
        l, w, h = line.dims(o)
        inside = l <= ctype.L + EPS and w <= ctype.W + EPS and h <= ctype.H + EPS
        if inside and (not door or w <= ctype.door_w + EPS and h <= ctype.door_h + EPS):
            return True
    return False


def _fit_issues(line: ItemLine, types: list[ContainerType]) -> list[Issue]:
    """Why a line fits no container type, one issue per reason: size or door, then mass."""
    if any(fits_container(line, t) for t in types):
        return []
    dims = {"L": line.L, "W": line.W, "H": line.H, "tippable": line.tippable}
    shaped = [t for t in types if _fits_shape(line, t, door=True)]
    out = []
    if not shaped:
        if any(_fits_shape(line, t, door=False) for t in types):
            out.append(Issue(f"item line {line.id}: fits no container type (through no door)", line=line.id,
                             code="fit_door", params={**dims, "door_w": max(t.door_w for t in types),
                                                      "door_h": max(t.door_h for t in types)}))
        else:
            out.append(Issue(f"item line {line.id}: fits no container type (too large)", line=line.id,
                             code="fit_size", params={**dims, "max_L": max(t.L for t in types),
                                                      "max_W": max(t.W for t in types),
                                                      "max_H": max(t.H for t in types)}))
    candidates = shaped or types  # the types the size allows, else every type
    if all(line.mass > t.max_mass + EPS for t in candidates):
        out.append(Issue(f"item line {line.id}: fits no container type (too heavy)", line=line.id, field="mass",
                         code="fit_mass", params={"mass": line.mass, "max_mass": max(t.max_mass for t in candidates),
                                                  "size_fits": bool(shaped)}))
    return out


def _type_problem(t: ContainerType) -> bool:
    return min(t.L, t.W, t.H, t.door_w, t.door_h, t.max_mass, t.cost) <= 0 or t.door_w > t.W + EPS or t.door_h > t.H + EPS


def _line_problem(line: ItemLine) -> bool:
    return ("#" in line.id or not isinstance(line.qty, int) or line.qty < 1 or min(line.L, line.W, line.H, line.mass) <= 0
            or not isinstance(line.tiers, int) or isinstance(line.tiers, bool) or line.tiers < 1
            or line.load is not None and line.load < 0)


def _validate_container_types(types: tuple[ContainerType, ...]) -> list[Issue]:
    issues: list[Issue] = []
    if not types:
        issues.append(Issue("no container types", field="container_types", code="container_types_none"))
    ids = [t.id for t in types]
    if len(set(ids)) != len(ids):
        issues.append(Issue("duplicate container type ids", field="id", code="container_duplicate_ids"))
    for t in types:
        if min(t.L, t.W, t.H, t.door_w, t.door_h, t.max_mass, t.cost) <= 0:
            issues.append(Issue(f"container type {t.id}: non-positive field", container=t.id, code="container_non_positive"))
        if t.door_w > t.W + EPS or t.door_h > t.H + EPS:
            issues.append(Issue(f"container type {t.id}: door larger than interior", container=t.id, field="door_w",
                                code="container_door"))
    return issues


def _validate_items(lines: tuple[ItemLine, ...]) -> list[Issue]:
    issues: list[Issue] = []
    if not lines:
        issues.append(Issue("no items", field="items", code="items_none"))
    ids = [line.id for line in lines]
    if len(set(ids)) != len(ids):
        issues.append(Issue("duplicate item line ids", field="id", code="line_duplicate_ids"))
    for line in lines:
        if "#" in line.id:
            issues.append(Issue(f"item line {line.id}: id contains '#'", line=line.id, field="id", code="line_id_hash"))
        if not isinstance(line.qty, int) or line.qty < 1:
            issues.append(Issue(f"item line {line.id}: qty must be an integer >= 1", line=line.id, field="qty",
                                code="qty_invalid"))
        if min(line.L, line.W, line.H, line.mass) <= 0:
            issues.append(Issue(f"item line {line.id}: non-positive size or mass", line=line.id, code="size_non_positive"))
        if not isinstance(line.tiers, int) or isinstance(line.tiers, bool) or line.tiers < 1:
            issues.append(Issue(f"item line {line.id}: tiers must be an integer >= 1", line=line.id, field="tiers",
                                code="tiers_invalid"))
        if line.load is not None and line.load < 0:
            issues.append(Issue(f"item line {line.id}: negative load", line=line.id, field="load", code="load_negative"))
    return issues
