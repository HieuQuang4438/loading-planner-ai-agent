"""The payload the page draws for one solution: boxes in placement order
with the checker's constraint 7/8 measures, replay order per container, per-container load, verdict, bound."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.bound import bound_to_dict, lower_bound
from src.checker import StackMeasure, check, stack_measures
from src.engines import fill
from src.model import ContainerType, Instance, ItemLine, Params, Solution, is_tipped, line_of
from src.web.replay import Box, boxes_of, replay_orders

MAX_DIAGNOSTICS = 40


def build_view(
    instance: Instance,
    solution: Solution,
    run: dict[str, Any],
    params: Params | None = None,
) -> dict[str, Any]:
    """Everything the page needs to draw and replay one solution: boxes in placement order with the
    checker's constraint 7/8 measures, the replay order per container, the checker's verdict,
    the cost lower bound. A mode B solution (`src.engines.fill`) is drawn and checked as the lot of the pieces it
    places; `fill` then gives each line's placed and total count."""
    params = params or solution.params
    whole = instance
    if fill.META_KEY in instance.meta:
        instance = fill.placed_instance(instance, solution)
    result = check(instance, solution, params)
    boxes = boxes_of(instance, solution)
    measures = stack_measures(instance, solution)
    min_h = min_item_height(instance)
    orders = replay_orders(instance, solution)
    types = {t.id: t for t in instance.container_types}
    lines = {line.id: line for line in instance.items}
    containers = []
    for used in solution.containers:
        ctype = types.get(used.type)
        order = orders.get(used.k)
        containers.append({
            "k": used.k,
            "type": used.type,
            "L": ctype.L if ctype else None,
            "W": ctype.W if ctype else None,
            "H": ctype.H if ctype else None,
            "door_w": ctype.door_w if ctype else None,
            "door_h": ctype.door_h if ctype else None,
            "max_mass": ctype.max_mass if ctype else None,
            "cost": ctype.cost if ctype else None,
            **container_load(instance, solution, boxes, used.k, ctype, lines),
            "free_tops": free_tops(solution, boxes, used.k, ctype, lines, measures, min_h),
            "replay": list(order.indices) if order else [],
            "replay_source": order.source if order else "engine",
        })
    return {
        "instance": instance.name,
        "note": instance.meta.get("note"),
        "lines": [{"id": line.id, "qty": line.qty, "L": line.L, "W": line.W, "H": line.H, "mass": line.mass,
                   "tippable": line.tippable, "orientations": list(line.orientations) if line.orientations else None,
                   "tiers": None if line.tiers_unlimited else line.tiers, "load": line.load} for line in instance.items],
        "min_item_height": min_h,
        "containers": containers,
        "placements": [
            {"item": p.item, "line": line_of(p.item), "mass": _mass(lines, p.item), "k": p.k, "o": p.o,
             "x": b.x, "y": b.y, "z": b.z, "l": b.l, "w": b.w, "h": b.h, **_measure_fields(measures.get(p.item))}
            for p, b in zip(solution.placements, boxes)
        ],
        "check": {
            "ok": result.ok,
            "cost": result.cost,
            "violations": [
                {"constraint": v.constraint, "k": v.k, "items": list(v.items), "message": v.message}
                for v in result.violations[:200]
            ],
            "n_violations": len(result.violations),
        },
        "tipped": tipped_counts(solution, lines),
        "bound": bound_to_dict(lower_bound(instance)),
        "params": asdict(params),
        "run": run,
        "fill": fill_summary(whole, instance) if fill.META_KEY in whole.meta else None,
    }


def fill_summary(whole: Instance, placed: Instance) -> dict[str, Any]:
    """Mode B: the run's fleet, priority and partial flag, and per line (priority order) placed and total pieces."""
    spec = fill.spec_of(whole)
    held = {line.id: line.qty for line in placed.items}
    qty = {line.id: line.qty for line in whole.items}
    return {"fleet": dict(spec.fleet), "priority": list(spec.priority), "partial": spec.partial,
            "lines": [{"id": line, "qty": qty[line], "placed": held.get(line, 0)} for line in spec.priority],
            "placed": sum(held.values()), "total": sum(qty.values())}


def posture_kind(code: str, line: ItemLine) -> str:
    """Kind of a tipped posture by the dimension pointing up (`code[2]`) against the line's `H`: "tipped" when
    equal, "lying" when shorter, "edge" when longer. Same rule and 1e-9 tolerance as `kindOf` in
    static/shared/orient.js."""
    d = getattr(line, code[2]) - line.H
    return "tipped" if abs(d) <= 1e-9 else "lying" if d < 0 else "edge"


def tipped_counts(solution: Solution, lines: dict[str, ItemLine]) -> dict[str, int]:
    """Pieces placed on their side or end, by kind (`posture_kind`), for the result panel."""
    n = {"lying": 0, "edge": 0, "tipped": 0}
    for p in solution.placements:
        line = lines.get(line_of(p.item))
        if line is not None and is_tipped(p.o):
            n[posture_kind(p.o, line)] += 1
    return {"total": sum(n.values()), **n}


def _mass(lines: dict[str, ItemLine], item: str) -> float | None:
    line = lines.get(line_of(item))
    return line.mass if line else None


def container_load(
    instance: Instance,
    solution: Solution,
    boxes: list[Box],
    k: int,
    ctype: ContainerType | None,
    lines: dict[str, ItemLine],
) -> dict[str, Any]:
    """What container `k` carries: total mass (summed as the checker's constraint 6 does), total piece
    volume, their share of the type's `max_mass` and `L*W*H`, and count and mass per item line in
    instance order."""
    mass = 0.0
    volume = 0.0
    per_line: dict[str, list[float]] = {}
    for p, b in zip(solution.placements, boxes):
        if p.k != k:
            continue
        m = _mass(lines, p.item) or 0.0
        mass += m
        volume += b.l * b.w * b.h
        entry = per_line.setdefault(line_of(p.item), [0, 0.0])
        entry[0] += 1
        entry[1] += m
    order = [line.id for line in instance.items if line.id in per_line]
    order += [i for i in per_line if i not in order]
    return {
        "mass": mass,
        "volume": volume,
        "mass_ratio": mass / ctype.max_mass if ctype and ctype.max_mass > 0 else None,
        "volume_ratio": volume / ctype.volume if ctype and ctype.volume > 0 else None,
        "lines": [{"id": i, "qty": int(per_line[i][0]), "mass": per_line[i][1]} for i in order],
    }


def _measure_fields(m: StackMeasure | None) -> dict[str, Any]:
    if m is None:  # a placement the checker rejects under constraints 1–3
        return {"supported": None, "on_top": None, "stack": None, "free_top": None}
    return {"supported": m.supported, "on_top": m.on_top, "stack": m.stack, "free_top": m.free_top}


def min_item_height(instance: Instance) -> float:
    """Lowest height any item of the lot can take, over its allowed orientations."""
    return min(line.dims(o)[2] for line in instance.items for o in line.allowed)


def free_tops(
    solution: Solution,
    boxes: list[Box],
    k: int,
    ctype: ContainerType | None,
    lines: dict[str, ItemLine],
    measures: dict[str, StackMeasure],
    min_h: float,
) -> int:
    """Items of container `k` with nothing on top, a tier to spare, `load` not 0, and headroom for the
    lowest item of the lot. An upper estimate: area, `delta`, support and mass are not considered."""
    if ctype is None:
        return 0
    n = 0
    for p, b in zip(solution.placements, boxes):
        m = measures.get(p.item)
        line = lines.get(line_of(p.item))
        if p.k != k or m is None or line is None:
            continue
        if m.free_top and m.stack < line.tiers and line.load != 0 and ctype.H - (b.z + b.h) >= min_h - 1e-9:
            n += 1
    return n


def trim_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """The scalar diagnostics (numbers, strings, bools), capped, for the result panel."""
    flat = {k: v for k, v in diagnostics.items() if isinstance(v, (int, float, str, bool)) or v is None}
    return dict(list(flat.items())[:MAX_DIAGNOSTICS])
