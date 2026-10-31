"""Independent checker for constraints 1–9.

Arbiter for every engine: it imports only the problem model, never solver code, and its rules are
never relaxed to let a result pass.

    python -m src.checker INSTANCE.json SOLUTION.json --delta 0.05 --alpha 0.8
"""
from __future__ import annotations

import argparse
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.formats import read_instance, read_solution
from src.model import ContainerType, Instance, ItemLine, Params, Solution, line_of, solution_cost

EPS = 1e-6  # length tolerance, m
AREA_EPS = 1e-9  # area tolerance, m²


@dataclass(frozen=True)
class Violation:
    constraint: int
    k: int | None
    items: tuple[str, ...]
    message: str


@dataclass
class CheckResult:
    violations: list[Violation]
    cost: float | None  # None when some container type is unknown

    @property
    def ok(self) -> bool:
        return not self.violations

    def by_constraint(self) -> dict[int, int]:
        return dict(sorted(Counter(v.constraint for v in self.violations).items()))


@dataclass
class _Box:
    item: str
    line: ItemLine
    x: float
    y: float
    z: float
    l: float
    w: float
    h: float
    below: list[int] = field(default_factory=list)  # boxes this one rests on
    above: list[int] = field(default_factory=list)  # boxes resting on this one

    @property
    def top(self) -> float:
        return self.z + self.h


@dataclass(frozen=True)
class StackMeasure:
    """What constraints 7 and 8 measure on one placed item, exactly as `check` judges them."""

    item: str
    k: int
    supported_area: float | None  # m² of base on touching tops; None on the floor
    base_area: float  # m²
    on_top: float  # kg: full mass of the upward "rests on" closure
    stack: int  # longest chain of "rests on" through the item, counted in items
    free_top: bool  # nothing rests on it

    @property
    def supported(self) -> float | None:
        """Share of the base that is supported; None on the floor."""
        return None if self.supported_area is None else self.supported_area / self.base_area


def check(instance: Instance, solution: Solution, params: Params) -> CheckResult:
    violations: list[Violation] = []
    types = _check_containers(instance, solution, violations)
    boxes = _collect_boxes(instance, solution, types, violations)
    for k, container_boxes in boxes.items():
        ctype = types[k]
        _check_inside_and_door(k, ctype, container_boxes, violations)
        _check_mass(k, ctype, container_boxes, violations)
        _check_gaps(k, container_boxes, params.delta, violations)
        _link_resting(container_boxes)
        measures = _measure(k, container_boxes)
        _check_support(k, measures, params.alpha, violations)
        _check_stacking(k, container_boxes, measures, violations)
    try:
        cost: float | None = solution_cost(instance, solution)
    except ValueError:
        cost = None
    return CheckResult(violations, cost)


def stack_measures(instance: Instance, solution: Solution) -> dict[str, StackMeasure]:
    """Constraint 7/8 measures of every placed item, by item id (web demo). Placements `check`
    would reject under constraints 1–3 have no entry."""
    types = _check_containers(instance, solution, [])
    out: dict[str, StackMeasure] = {}
    for k, container_boxes in _collect_boxes(instance, solution, types, []).items():
        _link_resting(container_boxes)
        out.update((m.item, m) for m in _measure(k, container_boxes))
    return out


def _check_containers(
    instance: Instance, solution: Solution, violations: list[Violation]
) -> dict[int, ContainerType]:
    """Constraint 1 for containers: each open container has exactly one known type."""
    types: dict[int, ContainerType] = {}
    for used in solution.containers:
        if used.k in types:
            violations.append(Violation(1, used.k, (), f"container {used.k} listed twice"))
            continue
        ctype = instance.container_type(used.type)
        if ctype is None:
            violations.append(Violation(1, used.k, (), f"container {used.k}: unknown type {used.type!r}"))
            continue
        types[used.k] = ctype
    return types


def _collect_boxes(
    instance: Instance,
    solution: Solution,
    types: dict[int, ContainerType],
    violations: list[Violation],
) -> dict[int, list[_Box]]:
    """Constraints 1 (orientation), 2 (each item exactly once) and 3 (open containers only)."""
    expected = {i for line in instance.items for i in line.item_ids()}
    open_ks = {used.k for used in solution.containers}
    seen: set[str] = set()
    boxes: dict[int, list[_Box]] = {k: [] for k in types}
    for p in solution.placements:
        if p.item not in expected:
            violations.append(Violation(2, p.k, (p.item,), f"{p.item}: not an item of the instance"))
            continue
        if p.item in seen:
            violations.append(Violation(2, p.k, (p.item,), f"{p.item}: placed more than once"))
            continue
        seen.add(p.item)
        line = instance.line(line_of(p.item))
        assert line is not None
        if p.o not in line.allowed:
            violations.append(Violation(1, p.k, (p.item,), f"{p.item}: orientation {p.o!r} not allowed"))
            continue
        if p.k not in open_ks:
            violations.append(Violation(3, p.k, (p.item,), f"{p.item}: container {p.k} is not open"))
            continue
        if p.k not in types:
            continue  # container type already reported under constraint 1
        l, w, h = line.dims(p.o)
        boxes[p.k].append(_Box(p.item, line, p.x, p.y, p.z, l, w, h))
    for missing in sorted(expected - seen):
        violations.append(Violation(2, None, (missing,), f"{missing}: not placed"))
    return boxes


def _check_inside_and_door(
    k: int, ctype: ContainerType, boxes: list[_Box], violations: list[Violation]
) -> None:
    """Constraints 4 and 9."""
    for b in boxes:
        inside = (
            b.x >= -EPS and b.y >= -EPS and b.z >= -EPS
            and b.x + b.l <= ctype.L + EPS
            and b.y + b.w <= ctype.W + EPS
            and b.z + b.h <= ctype.H + EPS
        )
        if not inside:
            violations.append(Violation(4, k, (b.item,), f"{b.item}: outside container {k} ({ctype.id})"))
        if b.w > ctype.door_w + EPS or b.h > ctype.door_h + EPS:
            violations.append(Violation(
                9, k, (b.item,),
                f"{b.item}: {b.w:.3f} x {b.h:.3f} m does not pass door {ctype.door_w} x {ctype.door_h} m",
            ))


def _check_mass(k: int, ctype: ContainerType, boxes: list[_Box], violations: list[Violation]) -> None:
    """Constraint 6."""
    total = sum(b.line.mass for b in boxes)
    if total > ctype.max_mass + EPS:
        violations.append(Violation(6, k, (), f"container {k}: {total:.1f} kg > {ctype.max_mass} kg"))


def _check_gaps(k: int, boxes: list[_Box], delta: float, violations: list[Violation]) -> None:
    """Constraint 5: boxes are disjoint, and side by side at least delta apart; stacked boxes may touch."""
    order = sorted(boxes, key=lambda b: b.x)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if b.x >= a.x + a.l + delta - EPS:
                break  # separated along x from a, and so is every later box
            if _separated(a, b, delta):
                continue
            kind = "overlap" if _interiors_meet(a, b) else f"gap < delta = {delta} m"
            violations.append(Violation(5, k, (a.item, b.item), f"{a.item}, {b.item}: {kind}"))


def _separated(a: _Box, b: _Box, delta: float) -> bool:
    return (
        a.x + a.l + delta <= b.x + EPS or b.x + b.l + delta <= a.x + EPS
        or a.y + a.w + delta <= b.y + EPS or b.y + b.w + delta <= a.y + EPS
        or a.top <= b.z + EPS or b.top <= a.z + EPS
    )


def _interiors_meet(a: _Box, b: _Box) -> bool:
    return (
        _overlap(a.x, a.l, b.x, b.l) > EPS
        and _overlap(a.y, a.w, b.y, b.w) > EPS
        and _overlap(a.z, a.h, b.z, b.h) > EPS
    )


def _overlap(start_a: float, size_a: float, start_b: float, size_b: float) -> float:
    return min(start_a + size_a, start_b + size_b) - max(start_a, start_b)


def _link_resting(boxes: list[_Box]) -> None:
    """Fill the "rests on" relation: top of the lower box touches the base, with positive shared area."""
    by_top = sorted(range(len(boxes)), key=lambda i: boxes[i].top)
    tops = [boxes[i].top for i in by_top]
    for j, upper in enumerate(boxes):
        if upper.z <= EPS:
            continue
        for i in by_top[bisect_left(tops, upper.z - EPS):bisect_right(tops, upper.z + EPS)]:
            lower = boxes[i]
            if _overlap(upper.x, upper.l, lower.x, lower.l) > EPS and _overlap(upper.y, upper.w, lower.y, lower.w) > EPS:
                upper.below.append(i)
                lower.above.append(j)


def _measure(k: int, boxes: list[_Box]) -> list[StackMeasure]:
    """Supported area, mass on top and stack height of every box; needs `_link_resting` first."""
    n = len(boxes)
    by_z = sorted(range(n), key=lambda i: boxes[i].z)
    down = [1] * n
    for j in by_z:
        if boxes[j].below:
            down[j] = 1 + max(down[i] for i in boxes[j].below)
    up = [1] * n
    closure = [0] * n  # bitset of boxes reachable upward
    for i in reversed(by_z):
        for u in boxes[i].above:
            up[i] = max(up[i], 1 + up[u])
            closure[i] |= (1 << u) | closure[u]
    out = []
    for i, b in enumerate(boxes):
        supported = None if b.z <= EPS else sum(
            _overlap(b.x, b.l, boxes[j].x, boxes[j].l) * _overlap(b.y, b.w, boxes[j].y, boxes[j].w)
            for j in b.below
        )
        out.append(StackMeasure(
            b.item, k, supported, b.l * b.w, _mass_of(closure[i], boxes), down[i] + up[i] - 1, not b.above,
        ))
    return out


def _check_support(k: int, measures: list[StackMeasure], alpha: float, violations: list[Violation]) -> None:
    """Constraint 7: base on the floor, or at least alpha of its area on touching tops."""
    for m in measures:
        if m.supported_area is None:
            continue
        if m.supported_area < alpha * m.base_area - AREA_EPS:
            violations.append(Violation(
                7, k, (m.item,), f"{m.item}: supported {m.supported_area / m.base_area:.3f} of base < alpha = {alpha}",
            ))


def _check_stacking(k: int, boxes: list[_Box], measures: list[StackMeasure], violations: list[Violation]) -> None:
    """Constraint 8: full mass of the upward "rests on" closure within load, longest stack within tiers."""
    for b, m in zip(boxes, measures):
        if b.line.load is not None and m.on_top > b.line.load + EPS:
            violations.append(Violation(8, k, (b.item,), f"{b.item}: {m.on_top:.1f} kg on top > load {b.line.load} kg"))
        if m.stack > b.line.tiers:
            violations.append(Violation(8, k, (b.item,), f"{b.item}: stack of {m.stack} > tiers {b.line.tiers}"))


def _mass_of(bits: int, boxes: list[_Box]) -> float:
    total = 0.0
    while bits:
        low = bits & -bits
        total += boxes[low.bit_length() - 1].line.mass
        bits ^= low
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a solution against constraints 1–9.")
    parser.add_argument("instance", type=Path)
    parser.add_argument("solution", type=Path)
    parser.add_argument("--delta", type=float, required=True, help="minimum horizontal gap, m")
    parser.add_argument("--alpha", type=float, required=True, help="minimum supported share of a base")
    parser.add_argument("--show", type=int, default=20, help="violations to print")
    args = parser.parse_args(argv)

    instance = read_instance(args.instance)
    solution = read_solution(args.solution)
    if solution.instance != instance.name:
        print(f"solution is for {solution.instance!r}, instance is {instance.name!r}", file=sys.stderr)
        return 2
    params = Params(delta=args.delta, alpha=args.alpha)
    if solution.params != params:
        print(f"note: solution states {solution.params}, checking with {params}")
    result = check(instance, solution, params)
    print(f"cost {result.cost}, containers {len(solution.containers)}, violations {len(result.violations)}")
    for constraint, count in result.by_constraint().items():
        print(f"  constraint {constraint}: {count}")
    for v in result.violations[: args.show]:
        print(f"  [{v.constraint}] {v.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
