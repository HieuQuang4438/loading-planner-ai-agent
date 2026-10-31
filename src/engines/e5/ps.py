"""PackingSolver as an extra column generator for E5.

PackingSolver's `box` solver (via `packingsolver3d`, loaded lazily: `src.packingsolver.import_packingsolver`) lays
out containers; each one is a candidate column. It knows neither the support share (constraint 7), the load and
tier limits (8) nor the door (9), so every container goes through `src.checker` alone (a sub-lot holding just its
items) and, when invalid, is repaired by removing items top-down until valid; an emptied container is dropped.
Removed items are left to other columns. Only valid containers leave this module.

Mapping (lengths in integer mm):
- the gap `delta` (constraint 5) by xflp's trick: every item is sent
  `delta` longer in `L` and `W` (not `H`), every container `delta` longer in `L` and `W`; the real item sits at the
  same corner. Two inflated items that do not overlap are `delta` apart; an inflated item inside the inflated
  container is the real item inside the real one, touching the wall allowed.
- the gap is only exact for upright rotations (`L W H`, `W L H`): a tipped rotation would need `delta` on other
  axes. A line is sent with its upright allowed codes only; a line with none (tipped codes only) is not sent. Lines
  tipped by the cores stay the cores' business (`Generator.report`).
- rounding: item lengths up, container lengths down, so a rounded layout is never looser than the real one; a lot
  whose lengths (and `delta`) are whole mm loses nothing (`report["rounding_exact"]`).
- `solver="boxstacks"` (engines `e5-psbs`, `e5-orient-psbs`) maps the load and tier limits too:
  per item type `maximum_weight_above = load`, `maximum_stackability = tiers`
  (None when unlimited) and one `stackability_id` per footprint class (the unordered pair of inflated `L`, `W`), so
  only same-footprint items stack, on the floor, fully supported. Its whole-lot call returns nothing within a
  fifth of a minute, so the initial step is a loop of single-container knapsack calls (`Generator._initial_stacks`).
- `door_filter=True` sends only rotations that pass the door (constraint 9): a knapsack call on one container type
  keeps the rotations passing that type's door; the whole-lot call keeps a rotation only if it passes the door of
  every container type it fits (by size and mass) -- so wherever PackingSolver puts it, it passes.
- optimisation mode `not-anytime-sequential`: PackingSolver on one thread, like the rest of E5. The whole-lot call
  also names its algorithm, `INITIAL_ALGORITHM`; the knapsack calls keep upstream's choice (tree search).
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from src.checker import Violation, check
from src.model import (
    UPRIGHT_ORIENTATIONS,
    ContainerType,
    Instance,
    Params,
    Placement,
    Solution,
    UsedContainer,
    item_id,
    line_of,
)
from src.packingsolver import CODE_OF_ROTATION, ROTATION_OF_CODE, import_packingsolver

UNIT = 1000  # integer units per metre (mm)
MODE = "not-anytime-sequential"
# The whole-lot call runs dichotomic search alone: in `not-anytime-sequential` with upstream's own choice of
# algorithms (sequential single knapsack first) it returned no solution within 9 s, or 30 s, on any of 7 lots tried
# (smoke); dichotomic search alone returns one on all of them, in the limit, on one thread.
INITIAL_ALGORITHM = {"use_dichotomic_search": True}
LEN_EPS = 1e-6  # in units: float noise of metres * UNIT
PROFIT_SCALE = 1e6  # the largest dual becomes this profit
MIN_CALL_TIME = 0.05  # s: no PackingSolver call with less time than this
SOLVERS = ("box", "boxstacks")
DOOR_EPS = 1e-6  # m, the checker's length tolerance

Valid = Callable[[list[Placement]], bool]


@dataclass(frozen=True)
class Layout:
    """One container PackingSolver laid out and the checker accepts: `placements` (k = 1) number each line's items
    `<line>#1..n`; `copies` containers share it."""

    type: ContainerType
    placements: tuple[Placement, ...]
    copies: int = 1


@dataclass
class Stats:
    """What the generator did, for the run's diagnostics (`as_dict`)."""

    calls: Counter = field(default_factory=Counter)  # by phase: "initial", "pricing"
    no_solution: Counter = field(default_factory=Counter)  # calls that returned no container
    errors: Counter = field(default_factory=Counter)  # calls PackingSolver failed (its error)
    time: Counter = field(default_factory=Counter)  # s inside PackingSolver, by phase
    generated: int = 0  # containers (layouts) PackingSolver returned
    valid: int = 0  # ... valid as returned
    repaired: int = 0  # ... made valid by removing items
    dropped: int = 0  # ... emptied by the repair (or out of repair time)
    fill_before: float = 0.0  # sum, over repaired containers, of the fill as returned
    fill_after: float = 0.0  # ... of the fill after repair
    items_removed: int = 0
    repair_time: float = 0.0
    rotations_removed_pricing: int = 0  # door filter: (line, rotation) pairs left out of knapsack calls
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        r = self.repaired
        return {
            "calls": sum(self.calls.values()), "calls_initial": self.calls["initial"],
            "calls_pricing": self.calls["pricing"],
            "no_solution": sum(self.no_solution.values()), "no_solution_initial": self.no_solution["initial"],
            "no_solution_pricing": self.no_solution["pricing"],
            "errors": sum(self.errors.values()), "last_error": self.last_error,
            "time": round(sum(self.time.values()), 3), "time_initial": round(self.time["initial"], 3),
            "time_pricing": round(self.time["pricing"], 3),
            "columns_generated": self.generated, "columns_valid": self.valid, "columns_repaired": r,
            "columns_dropped": self.dropped,
            "repaired_fill_before": round(self.fill_before / r, 4) if r else None,
            "repaired_fill_after": round(self.fill_after / r, 4) if r else None,
            "items_removed": self.items_removed, "repair_time": round(self.repair_time, 3),
            "rotations_removed_pricing": self.rotations_removed_pricing,
        }


def repair_top_down(
    placements: list[Placement], top: Callable[[Placement], float], valid: Valid,
    expired: Callable[[], bool] = lambda: False,
) -> list[Placement] | None:
    """`placements` when valid; else with the item whose top is highest removed (ties: higher base, then later in the
    list), again and again until valid. `[]` when it empties; `None` when `expired()` before it is valid."""
    current = list(placements)
    while current:
        if valid(current):
            return current
        if expired():
            return None
        worst = max(range(len(current)), key=lambda i: (top(current[i]), current[i].z, i))
        del current[worst]
    return []


def renumbered(placements: list[Placement] | tuple[Placement, ...]) -> list[Placement]:
    """The placements with each line's items numbered `<line>#1..n` in list order (items of a line are identical)."""
    seen: Counter = Counter()
    out = []
    for p in placements:
        line = line_of(p.item)
        seen[line] += 1
        out.append(replace(p, item=item_id(line, seen[line]), k=1))
    return out


def container_violations(instance: Instance, ctype: ContainerType, placements: list[Placement], params: Params
                         ) -> list[Violation]:
    """The checker's violations for one container of `ctype` holding exactly `placements`: the check runs on a sub-lot
    of just these items, so constraint 2 (every item once) is met by construction."""
    counts = Counter(line_of(p.item) for p in placements)
    lines = tuple(replace(line, qty=counts[line.id]) for line in instance.items if counts[line.id])
    sub = Instance(instance.name, (ctype,), lines)
    solution = Solution(instance.name, params, [UsedContainer(1, ctype.id)], renumbered(placements))
    return check(sub, solution, params).violations


def container_valid(instance: Instance, ctype: ContainerType, placements: list[Placement], params: Params) -> bool:
    """Whether the checker accepts one container of `ctype` holding exactly `placements`."""
    return not container_violations(instance, ctype, placements, params)


def fill_of(instance: Instance, ctype: ContainerType, placements: list[Placement] | tuple[Placement, ...]) -> float:
    """The container's fill: the larger of its volume and mass shares."""
    volume = mass = 0.0
    for p in placements:
        line = instance.line(line_of(p.item))
        volume += line.volume
        mass += line.mass
    return max(volume / ctype.volume, mass / ctype.max_mass)


def rounding_exact(instance: Instance, delta: float) -> bool:
    """Whether every length of the lot (and `delta`) is a whole number of mm."""
    lengths = [delta]
    lengths += [v for t in instance.container_types for v in (t.L, t.W, t.H)]
    lengths += [v for line in instance.items for v in (line.L, line.W, line.H)]
    return all(abs(v * UNIT - round(v * UNIT)) < 1e-6 for v in lengths)


def _up(metres: float) -> int:
    return math.ceil(metres * UNIT - LEN_EPS)


def _down(metres: float) -> int:
    return math.floor(metres * UNIT + LEN_EPS)


class Generator:
    """PackingSolver on one lot: `initial` (the whole lot) and `knapsack` (one container of a type, items valued at the
    LP duals). `solver` is `"box"` or `"boxstacks"`, `door_filter` drops rotations that do not pass the door (see the
    module docstring). Raises `PackingSolverMissing` when `packingsolver3d` is absent."""

    def __init__(self, instance: Instance, params: Params, ps: Any = None, solver: str = "box",
                 door_filter: bool = False, call_time: float = 1.0) -> None:
        if solver not in SOLVERS:
            raise ValueError(f"unknown PackingSolver solver {solver!r}; expected one of {SOLVERS}")
        self.ps = ps if ps is not None else import_packingsolver()
        self.instance = instance
        self.params = params
        self.solver = solver
        self.door_filter = door_filter
        self.call_time = call_time  # s per knapsack call of the `boxstacks` initial loop
        self.stats = Stats()
        delta = params.delta
        types = instance.container_types
        self.codes = [tuple(c for c in line.allowed if c in UPRIGHT_ORIENTATIONS) for line in instance.items]
        self.dims = [(_up(line.L + delta), _up(line.W + delta), _up(line.H)) for line in instance.items]
        self.bin_dims = [(_down(t.L + delta), _down(t.W + delta), _down(t.H)) for t in types]
        # rotations of line i that fit container type t by size and mass (before any door filter)
        self.codes_fit = [[tuple(c for c in self.codes[i] if self._fits(i, c, t)) for t in range(len(types))]
                          for i in range(len(instance.items))]
        # rotations a knapsack call on type t sends for line i, and the ones the whole-lot call sends
        if door_filter:
            self.codes_type = [[tuple(c for c in cs if self._door_ok(i, c, t)) for t, cs in enumerate(row)]
                               for i, row in enumerate(self.codes_fit)]
            self.codes_all = [
                tuple(c for c in self.codes[i]
                      if all(self._door_ok(i, c, t) for t in range(len(types)) if c in self.codes_fit[i][t]))
                for i in range(len(instance.items))]
        else:
            self.codes_type = self.codes_fit
            self.codes_all = self.codes
        self.fit = [[bool(cs) for cs in row] for row in self.codes_type]
        self.sendable = [i for i in range(len(instance.items))
                         if any(c in self.codes_all[i] for cs in self.codes_fit[i] for c in cs)]
        # `boxstacks`: one stackability id per footprint class
        classes: dict[tuple[int, int], int] = {}
        self.footprint = [classes.setdefault(tuple(sorted(d[:2])), len(classes)) for d in self.dims]
        sent = set(self.sendable)
        box = solver == "box"
        self.report: dict[str, Any] = {
            "rounding_exact": rounding_exact(instance, delta), "unit": "mm", "mode": MODE, "solver": solver,
            "door_filter": door_filter,
            "initial_algorithm": sorted(INITIAL_ALGORITHM)[0].removeprefix("use_") if box else "sequential knapsack",
            "lines_not_sent": [line.id for i, line in enumerate(instance.items) if i not in sent],
            "lines_tipped_ignored": [line.id for line, codes in zip(instance.items, self.codes)
                                     if codes and len(codes) < len(line.allowed)],
        }
        if door_filter:  # (line, rotation) pairs the whole-lot call does not send because some type's door stops them
            self.report["rotations_removed_by_door"] = sum(
                len(self.codes[i]) - len(self.codes_all[i]) for i in range(len(instance.items)) if self.codes[i])
            self.report["lines_dropped_by_door"] = [
                line.id for i, line in enumerate(instance.items)
                if i not in sent and any(self.codes_fit[i][t] for t in range(len(types)))]

    def _fits(self, i: int, code: str, t: int) -> bool:
        """Whether line `i` in upright rotation `code` fits container type `t` by (inflated) size and mass."""
        a, b, h = self.dims[i]
        if code == "WLH":
            a, b = b, a
        x, y, z = self.bin_dims[t]
        return a <= x and b <= y and h <= z and self.instance.items[i].mass <= self.instance.container_types[t].max_mass

    def _door_ok(self, i: int, code: str, t: int) -> bool:
        """Whether line `i` in rotation `code` passes the door of type `t` (constraint 9, real sizes)."""
        _, w, h = self.instance.items[i].dims(code)
        ctype = self.instance.container_types[t]
        return w <= ctype.door_w + DOOR_EPS and h <= ctype.door_h + DOOR_EPS

    # --- calls ---------------------------------------------------------------------------------

    def _item_type(self, i: int, profit: float | None, copies: int, codes: tuple[str, ...]) -> Any:
        ps, line = self.ps, self.instance.items[i]
        a, b, h = self.dims[i]
        rotations = tuple(ps.Rotation(ROTATION_OF_CODE[c]) for c in codes)
        fields: dict[str, Any] = {} if profit is None else {"profit": profit}
        if self.solver == "boxstacks":  # mapping: only same-footprint items stack; load and tiers as given
            fields.update(stackability_id=self.footprint[i], maximum_weight_above=line.load,
                          maximum_stackability=None if line.tiers_unlimited else line.tiers)
        return ps.ItemType(x=a, y=b, z=h, weight=line.mass, copies=copies, rotations=rotations, **fields)

    def _bin_type(self, t: int, copies: int) -> Any:
        ctype = self.instance.container_types[t]
        x, y, z = self.bin_dims[t]
        return self.ps.BinType(x=x, y=y, z=z, cost=ctype.cost, copies=copies, maximum_weight=ctype.max_mass)

    def _solve(self, ps_instance: Any, phase: str, time_limit: float, **algorithms: bool) -> list[dict[str, Any]]:
        """PackingSolver's bins (raw JSON) within `time_limit` s; `[]` and a count when it finds none or fails."""
        ps = self.ps
        self.stats.calls[phase] += 1
        t0 = time.monotonic()
        try:
            solved = getattr(ps, self.solver).solve(ps_instance, time_limit=time_limit,
                                                    optimization_mode=ps.OptimizationMode(MODE), **algorithms)
            bins = json.loads(solved.to_json()).get("bins") or []
        except ps.PackingSolverError as error:  # an invalid or failed solve is a result, not a crash
            self.stats.errors[phase] += 1
            self.stats.last_error = f"{type(error).__name__}: {error}"
            bins = []
        finally:
            self.stats.time[phase] += time.monotonic() - t0
        if not any(b.get("placements") for b in bins):
            self.stats.no_solution[phase] += 1
            return []
        return bins

    def raw_initial(self, time_limit: float) -> list[Layout]:
        """`box` only: one variable-sized bin packing call on the whole lot (all container types, their costs and
        masses) within `time_limit` s; its containers as returned, unchecked."""
        if self.solver != "box":
            raise ValueError("raw_initial is the box solver's whole-lot call")
        if not self.sendable or time_limit < MIN_CALL_TIME:
            return []
        pieces = sum(self.instance.items[i].qty for i in self.sendable)
        ps_instance = self.ps.Instance(
            bin_types=tuple(self._bin_type(t, pieces) for t in range(len(self.instance.container_types))),
            item_types=tuple(self._item_type(i, None, self.instance.items[i].qty, self.codes_all[i])
                             for i in self.sendable),
            objective=self.ps.Objective.VARIABLE_SIZED_BIN_PACKING)
        return [self._layout(b) for b in self._solve(ps_instance, "initial", time_limit, **INITIAL_ALGORITHM)]

    def initial(self, time_limit: float, until: float) -> tuple[list[Layout], Solution | None]:
        """The whole lot within `time_limit` s: its valid (repaired) containers, and its full solution when it holds
        every item of the lot and is valid as returned (else `None`). `box`: one variable-sized bin packing call;
        `boxstacks`: a loop of single-container knapsack calls (`_initial_stacks`). Repairs stop at monotonic time
        `until`."""
        if self.solver == "boxstacks":
            return self._initial_stacks(time_limit, until)
        raw = self.raw_initial(time_limit)
        return self._valid(raw, until), self._full_solution(raw)

    def _initial_stacks(self, time_limit: float, until: float) -> tuple[list[Layout], Solution | None]:
        """`boxstacks` has no whole-lot call that answers in time (variable-sized bin packing returned nothing within
        8.5 s on 4 of 6 lots tried), so this does what its sequential-knapsack step does, by hand: while
        time is left, fill one container of the type with the lowest cost per m3 among those the remaining lines fit,
        valuing each item at its volume, one call (at most `call_time` s) at a time; the items of the container as
        returned are taken off the list. A type whose call finds nothing is not tried again."""
        types = self.instance.container_types
        index = {line.id: i for i, line in enumerate(self.instance.items)}
        remaining = {i: self.instance.items[i].qty for i in self.sendable}
        stop = time.monotonic() + time_limit
        raws: list[Layout] = []
        layouts: list[Layout] = []
        failed: set[int] = set()
        order = sorted(range(len(types)), key=lambda t: (types[t].cost / types[t].volume, t))
        while remaining:
            left = stop - time.monotonic()
            t = next((t for t in order if t not in failed and any(self.fit[i][t] for i in remaining)), None)
            if t is None or left < MIN_CALL_TIME:
                break
            profits = {i: self.instance.items[i].volume for i in remaining if self.fit[i][t]}
            got = self.raw_knapsack(types[t], profits, min(self.call_time, left), "initial",
                                    {i: remaining[i] for i in profits})
            if not got:
                failed.add(t)
                continue
            for layout in got:
                for p in layout.placements:
                    remaining[index[line_of(p.item)]] -= 1
            remaining = {i: n for i, n in remaining.items() if n > 0}
            raws += got
            layouts += self._valid(got, until)
        covered = not remaining and len(self.sendable) == len(self.instance.items)
        return layouts, (self._full_solution(raws) if covered else None)

    def raw_knapsack(self, ctype: ContainerType, profits: dict[int, float], time_limit: float, phase: str = "pricing",
                     available: dict[int, int] | None = None) -> list[Layout]:
        """One container of `ctype` filled for the profits (line index -> value) within `time_limit` s, as returned,
        unchecked. Profits are scaled so the largest is `PROFIT_SCALE`; `available`: copies per line (default: the
        lot's, capped by what fits)."""
        t = self.instance.container_types.index(ctype)
        chosen = [i for i, pi in profits.items() if pi > 0.0 and self.fit[i][t]]
        if not chosen or time_limit < MIN_CALL_TIME:
            return []
        if self.door_filter:  # rotations the door of this type takes out, lines left out altogether included
            self.stats.rotations_removed_pricing += sum(
                len(self.codes_fit[i][t]) - len(self.codes_type[i][t]) for i, pi in profits.items() if pi > 0.0)
        scale = PROFIT_SCALE / max(profits[i] for i in chosen)
        ps_instance = self.ps.Instance(
            bin_types=(self._bin_type(t, 1),),
            item_types=tuple(self._item_type(i, max(profits[i] * scale, 1.0),
                                             self._copies(i, ctype, None if available is None else available[i]),
                                             self.codes_type[i][t]) for i in chosen),
            objective=self.ps.Objective.KNAPSACK)
        bins = self._solve(ps_instance, phase, time_limit)
        return [self._layout(b, chosen, t) for b in bins]

    def knapsack(self, ctype: ContainerType, profits: dict[int, float], time_limit: float, until: float) -> list[Layout]:
        """One container of `ctype` filled for the profits (line index -> dual) within `time_limit` s; the valid
        (repaired) container, if any."""
        return self._valid(self.raw_knapsack(ctype, profits, time_limit), until)

    def _copies(self, i: int, ctype: ContainerType, limit: int | None = None) -> int:
        """The copies of line `i` a knapsack on one `ctype` can use: no more than the lot has (or `limit`), nor than
        fit by volume or mass (a smaller call: PackingSolver's time limit is only checked between its steps)."""
        line = self.instance.items[i]
        a, b, h = self.dims[i]
        by_volume = int(ctype.volume / (a * b * h / UNIT**3)) if a * b * h else line.qty
        by_mass = int(ctype.max_mass / line.mass) if line.mass > 0 else line.qty
        return max(1, min(line.qty if limit is None else limit, by_volume, by_mass))

    # --- results -------------------------------------------------------------------------------

    def _layout(self, packed: dict[str, Any], line_ids: list[int] | None = None, bin_type: int | None = None) -> Layout:
        """A raw PackingSolver bin as a layout (unchecked). `line_ids`: line index of each item type of the call
        (default: the sendable lines, as `initial` sends them); `bin_type`: the bin's type when the call had one."""
        index = self.sendable if line_ids is None else line_ids
        ctype = self.instance.container_types[packed.get("bin_type_id", 0) if bin_type is None else bin_type]
        counters: Counter = Counter()
        placements = []
        for p in packed["placements"]:
            line = self.instance.items[index[p["item_type_id"]]]
            counters[line.id] += 1
            placements.append(Placement(item=item_id(line.id, counters[line.id]), k=1, x=p["x"] / UNIT,
                                        y=p["y"] / UNIT, z=p["z"] / UNIT, o=CODE_OF_ROTATION[p["rotation"]]))
        return Layout(ctype, tuple(placements), packed.get("copies", 1))

    def _valid(self, layouts: list[Layout], until: float) -> list[Layout]:
        """The layouts that are valid, repaired top-down when not; counts in `stats`."""
        out = []
        for layout in layouts:
            self.stats.generated += 1
            if not layout.placements:
                self.stats.dropped += 1
                continue
            t0 = time.monotonic()
            placements = list(layout.placements)
            fixed = repair_top_down(
                placements, self._top,
                lambda ps_: container_valid(self.instance, layout.type, ps_, self.params),
                lambda: time.monotonic() >= until)
            self.stats.repair_time += time.monotonic() - t0
            if not fixed:
                self.stats.dropped += 1
            elif len(fixed) == len(placements):
                self.stats.valid += 1
                out.append(layout)
            else:
                self.stats.repaired += 1
                self.stats.items_removed += len(placements) - len(fixed)
                self.stats.fill_before += fill_of(self.instance, layout.type, placements)
                self.stats.fill_after += fill_of(self.instance, layout.type, fixed)
                out.append(Layout(layout.type, tuple(renumbered(fixed)), layout.copies))
        return out

    def _top(self, p: Placement) -> float:
        return p.z + self.instance.line(line_of(p.item)).dims(p.o)[2]

    def _full_solution(self, layouts: list[Layout]) -> Solution | None:
        """The call's solution as a repo solution when it holds every item of the lot and the checker accepts it as
        returned, else `None`."""
        if sum(len(layout.placements) * layout.copies for layout in layouts) != self.instance.n_items:
            return None
        containers: list[UsedContainer] = []
        placements: list[Placement] = []
        counters: Counter = Counter()
        for layout in layouts:
            for _ in range(layout.copies):
                k = len(containers) + 1
                containers.append(UsedContainer(k, layout.type.id))
                for p in layout.placements:
                    line = line_of(p.item)
                    counters[line] += 1
                    placements.append(replace(p, item=item_id(line, counters[line]), k=k))
        solution = Solution(self.instance.name, self.params, containers, placements)
        return solution if check(self.instance, solution, self.params).ok else None

