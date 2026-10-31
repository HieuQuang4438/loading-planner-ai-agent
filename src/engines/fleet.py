"""Shared fleet layer: "từng loại, đổi container cuối" 

Every packing core plugs in as a `PackOne` (`src.engines.base.PackOne`):
`pack_one(items, ctype, params, rng) -> placements`, placing as many of `items` as fit into one new,
empty container of type `ctype` and returning their placements. The `k` on those placements is
whatever the core put there; `solve` below ignores it and renumbers every container itself.

Algorithm, for each container type `t` in `instance.container_types`, in turn:

1. Split every item by whether its line fits `t` at all, geometry and door (constraint 9;
   `src.formats.fits_container`). Items that do not fit `t` go instead to the cheapest type they do
   fit (grouped by that type — usually just one extra type, since misfits share the same reason).
2. Open new containers of the responsible type one at a time, calling `pack_one` on whatever is
   still unplaced, until every item is placed. A call that places nothing would loop forever, so
   that is treated as a core bug and raised immediately instead.

This gives one full plan per type `t`, tried as the "primary" type; the cheapest of the
`len(container_types)` plans is kept. Its emptiest container's items are then retried against every
cheaper type, cheapest first, by calling `pack_one` again — fresh, on an empty container of that
type — and swapped in the first type whose call places every one of those items (never a partial
swap, and never a replay of the old coordinates: a fresh call may find room a naive check of the old
placements against the new type's bare dimensions would have missed, e.g. items originally spread
across a long container's full length that a compact repack fits inside a shorter one).

The time limit is split evenly over the `t` tried; a type whose plan does not finish within its
share is dropped from the comparison rather than returned half-built. If every type times out,
`solve` raises `FleetTimeout` (the runner counts this instance/seed as having no solution).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from src.engines.base import PackOne, Piece, expand_pieces, piece_of
from src.formats import fits_container
from src.model import ContainerType, Instance, ItemLine, Params, Placement, Solution, UsedContainer, line_of

EPS = 1e-6  # matches src.checker.EPS


class FleetTimeout(RuntimeError):
    """No container type produced a complete plan within its share of the time limit."""


@dataclass
class _Plan:
    cost: float
    containers: list[tuple[str, list[Placement]]]  # (container type id, its placements)


def solve(instance: Instance, params: Params, time_limit: float, seed: int, pack_one: PackOne) -> Solution:
    types = instance.container_types
    if not types:
        raise ValueError(f"{instance.name}: no container types")
    pieces = expand_pieces(instance)
    per_type_budget = time_limit / len(types)

    plans: list[_Plan] = []
    for i, t in enumerate(types):
        deadline = time.monotonic() + per_type_budget
        # Deterministic, distinct stream per candidate type so a stochastic core does not repeat the
        # exact same random choices across the fleet layer's own per-type attempts.
        rng = random.Random(seed * 10_000 + i)
        try:
            plans.append(_plan_for_type(instance, pieces, t, params, rng, pack_one, deadline))
        except FleetTimeout:
            continue
    if not plans:
        raise FleetTimeout(f"{instance.name}: no container type produced a plan within {time_limit} s")

    best = min(plans, key=lambda p: p.cost)
    swapped = _swap_emptiest(instance, best, params, seed, pack_one)
    solution = _to_solution(instance, params, swapped)
    # `_swap_emptiest` returns the very same `_Plan` object, unchanged, whenever it does not swap
    # (empty plan, no cheaper type fits, or every cheaper type's repack falls short) and only ever
    # builds a fresh `_Plan` on an actual swap -- so identity tells the caller which happened, with no
    # need for `_swap_emptiest` to grow its own return type just to report it (docs/discovery/
    #'s engine-level diagnostics dict; e.g. `src.engines.e0` uses this
    # instead of an approximation from the solution's container types alone).
    solution.meta["last_container_swapped"] = swapped is not best
    return solution


def _plan_for_type(
    instance: Instance,
    pieces: list[Piece],
    primary: ContainerType,
    params: Params,
    rng: random.Random,
    pack_one: PackOne,
    deadline: float,
) -> _Plan:
    fits_primary = {line.id: fits_container(line, primary) for line in instance.items}
    primary_pieces = [p for p in pieces if fits_primary[line_of(p.item)]]
    misfit_pieces = [p for p in pieces if not fits_primary[line_of(p.item)]]

    containers: list[tuple[str, list[Placement]]] = []
    cost = _open_containers(primary_pieces, primary, params, rng, pack_one, deadline, containers)

    by_fallback: dict[str, list[Piece]] = {}
    for p in misfit_pieces:
        line = instance.line(line_of(p.item))
        assert line is not None
        fallback = _cheapest_fit(instance, line, exclude=primary.id)
        if fallback is None:
            raise ValueError(f"{line.id}: fits no container type")  # unreachable: validate_instance guards this
        by_fallback.setdefault(fallback.id, []).append(p)
    for type_id, group in by_fallback.items():
        ctype = instance.container_type(type_id)
        assert ctype is not None
        cost += _open_containers(group, ctype, params, rng, pack_one, deadline, containers)

    return _Plan(cost=cost, containers=containers)


def _open_containers(
    pieces: list[Piece],
    ctype: ContainerType,
    params: Params,
    rng: random.Random,
    pack_one: PackOne,
    deadline: float,
    containers_out: list[tuple[str, list[Placement]]],
) -> float:
    remaining = list(pieces)
    cost = 0.0
    while remaining:
        if time.monotonic() > deadline:
            raise FleetTimeout(f"{ctype.id}: time budget exceeded with {len(remaining)} piece(s) left")
        placed = pack_one(remaining, ctype, params, rng)
        placed_ids = {p.item for p in placed}
        if not placed_ids:
            raise ValueError(f"{ctype.id}: core placed 0 items into an empty container")
        remaining_ids = {p.item for p in remaining}
        unknown = placed_ids - remaining_ids
        if unknown:
            raise ValueError(f"{ctype.id}: core placed unknown item(s) {sorted(unknown)}")
        remaining = [p for p in remaining if p.item not in placed_ids]
        containers_out.append((ctype.id, placed))
        cost += ctype.cost
    return cost


def _cheapest_fit(instance: Instance, line: ItemLine, exclude: str) -> ContainerType | None:
    candidates = [t for t in instance.container_types if t.id != exclude and fits_container(line, t)]
    return min(candidates, key=lambda t: t.cost, default=None)


def _swap_emptiest(instance: Instance, plan: _Plan, params: Params, seed: int, pack_one: PackOne) -> _Plan:
    if not plan.containers:
        return plan
    idx = _emptiest(instance, plan.containers)
    type_id, placements = plan.containers[idx]
    current = instance.container_type(type_id)
    assert current is not None
    pieces = [piece_of(instance, p.item) for p in placements]
    wanted = {p.item for p in pieces}
    cheaper = sorted((t for t in instance.container_types if t.cost < current.cost - EPS), key=lambda t: t.cost)
    for j, t in enumerate(cheaper):
        # A stream distinct from the per-primary-type ones in `solve` (offset well past their range).
        rng = random.Random(seed * 10_000 + 1_000_000 + j)
        repacked = pack_one(pieces, t, params, rng)
        if {p.item for p in repacked} == wanted:
            new_containers = list(plan.containers)
            new_containers[idx] = (t.id, repacked)
            return _Plan(cost=plan.cost - current.cost + t.cost, containers=new_containers)
    return plan


def _emptiest(instance: Instance, containers: list[tuple[str, list[Placement]]]) -> int:
    """Index of the least (volume-)loaded container — the tie-break criterion of
    ("chỗ trống của container vơi nhất"), volume only: the fleet layer
    does not also weigh remaining load capacity here."""
    best_idx, best_fill = 0, float("inf")
    for idx, (type_id, placements) in enumerate(containers):
        ctype = instance.container_type(type_id)
        assert ctype is not None
        loaded = sum(_piece_volume(instance, p) for p in placements)
        fill = loaded / ctype.volume
        if fill < best_fill:
            best_fill, best_idx = fill, idx
    return best_idx


def _piece_volume(instance: Instance, p: Placement) -> float:
    line = instance.line(line_of(p.item))
    assert line is not None
    return line.volume


def _to_solution(instance: Instance, params: Params, plan: _Plan) -> Solution:
    containers: list[UsedContainer] = []
    placements: list[Placement] = []
    for k, (type_id, placed) in enumerate(plan.containers, start=1):
        containers.append(UsedContainer(k=k, type=type_id))
        placements += [replace(p, k=k) for p in placed]
    return Solution(instance=instance.name, params=params, containers=containers, placements=placements)
