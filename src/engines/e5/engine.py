"""E5 = set cover (>= qty, surplus trimmed afterwards) over containers laid out by E1's and E2's cores.

Phases, on fixed shares of the time budget (`Settings`); a phase ending early leaves its time to the
next one, since each phase runs until an absolute deadline. `Settings.cores` picks the packing cores
(default both; engines `e5-e1`, `e5-e2`): with one, it gets the whole harvest time and its
initial solve may run to the end of the span; pricing and trim's fallback use only the selected cores:

1. **Harvest** (`alns_share`). E1's and E2's full solve (core plus the shared fleet layer), each core
   call filed into the column pool; then E4's ALNS on each core, the remaining time split evenly,
   every core call again filed (`RecordingPacker`). The best solution found is the incumbent: E5
   never returns anything worse. With `Settings.search == "brkga"` (engine `e5-brkga`)
   E3's BRKGA replaces ALNS on each core, on the same slot, seeded with the core's initial solution
   (`Decoder.seeded`); every decode's core calls are filed the same way.
2. **Master on harvested columns only** (part of the pricing share): the integer master, hinted
   with the incumbent. Recorded separately to answer "how much does better fleet selection save"
   (solution-approaches §7.2) without a second run.
3. **Pricing** (`pricing_share`): LP by GLOP, then per core and container type one core call on the
   lines with a positive dual, ordered by dual per unit volume (`Hints.order`); new columns with a
   negative reduced cost go into the LP; until the share ends or a round adds none.
4. **Integer master** (the rest): SCIP over every column (price-and-branch), hinted with the best
   cover known.
5. **Leftover time** (`Settings.reuse_time`, engine e5-mono): when the final master leaves time,
   each core's ALNS resumes where it stopped, then the master runs again on the grown pool (`_reuse`).
   Engines e5-v4, e5-orient-v4 (also e5-v3-stall, e5-orient-v3-stall): a core's ALNS also stops when it stalls
   (`alns_stall_min`, `alns_stall_ratio`; counted in iterations); a stalled core is not resumed, and
   when no core can be, step 5 is skipped (`reuse.stop` = "stall").

Each master solution is trimmed (`src.engines.e5.trim`) and checked by `src.checker.check` inside
the engine (approved option 2A); one failing the check is dropped, never repaired. The
cheapest of the incumbent and the checked master solutions is returned (cost, then the emptiest
container's fill, as E4).

**Tilt probe** (`Settings.tilt_core`, engine `e5-tilt`): when some tippable line would be
oriented differently by E1's tilt-first rule (`src.engines.e1.orientation.tilt_first_orientation`),
a third core `e1-tilt` joins the harvest's initial solves and pricing, but not ALNS, so the search
time of E1's and E2's cores stays as in E5 and only the extra columns differ.

**Orientation probe** (engine `e5-orient`): `Settings.orient_dense_core` adds a core `e1-orient-dense`
(E1 with its dense rule, `src.engines.e1.orientation.dense_orientation`) the same way, when that rule
orients some line differently from E1's base rule (`dense_changes`); `Settings.e2_orient` makes the E2
core `src.engines.e2.pack_one_orient` (every allowed orientation tried) in the initial solve, ALNS,
pricing and trim. Diagnostics read the source of each container of the returned solution: a container's
source is the pool column's first producer (E1 and E2 file theirs first, so a column the dense core
reproduces counts for the earlier core), kept through trim.

**Seeding core** (engine `e5-blocks`): `Settings.initial_core` replaces the searched cores'
initial solves by one full solve with another core (E2b's block building, `src.engines.e2b`), filed into
the pool under that core's name; ALNS (or BRKGA) on every searched core starts from that solution, so
containers it never touches keep E2b's layout and those it repairs are laid out again by E1 or E2.
Pricing and trim use the searched cores only. No initial solution from the seeding core is a
`FleetTimeout`, never a fallback to E1's or E2's initial solves. Engine `e5-seed-e1` seeds with
E1's core instead: the same time layout as `e5-blocks`, as a control for where it starts.

**Knapsack pricing** (engine `e5-knap`, `Settings.pricing == "knapsack"`): only the inside of the
pricing step changes. Per core and container type, the item set is the best knapsack for the round's duals
(`src.engines.e5.knapsack`, CP-SAT) within `gamma` times the container's volume, mass and floor, `gamma`
adapted per type from what the core packs; the set is skipped when it cannot have a negative reduced cost, and a
pricing result enters the pool only when its reduced cost is negative. A round without a new column ends pricing
unless `gamma` just went down for some type.

**Lean pool** (engine `e5-v2-lean`, in e5-v3 = e5-v2-pace plus `sparse_pool`, `reduce_master`): the pool stores each
column's nonzero counts only (`SparseColumn`), and every integer master gets the pool cut by `src.engines.e5.reduce`
(dominated columns out, then at most `master_columns` by reduced cost under the latest LP duals, the hint and best
cover always in); the pool keeps every column for pricing and ALNS. The LP before the pre-pricing master is solved
first, for its duals, and reused by the first pricing round when the pool has not grown.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace
from typing import Any

from src.bound import lower_bound
from src.checker import check
from src.engines import e1, e2, e2b, fleet
from src.engines.base import Hints, PackOne, Piece
from src.engines.e1.orientation import base_orientation, dense_orientation, tilt_first_orientation
from src.engines.e3.decoder import Decoder
from src.engines.e3.engine import DEFAULTS as BRKGA_DEFAULTS
from src.engines.e3.engine import slots_for
from src.engines.e3.search import run as brkga
from src.engines.e4.engine import DEFAULTS as ALNS_DEFAULTS
from src.engines.e4.operators import Context
from src.engines.e4.packer import Deadline, HintedPackOne
from src.engines.e4.search import Search
from src.engines.e4.state import Box, from_solution
from src.engines.e4.state import key as box_key
from src.engines.e4.state import to_solution as boxes_to_solution
from src.engines.e5 import knapsack, master
from src.engines.e5.ps import Generator as PackingSolverColumns
from src.engines.e5.pool import Pool, RecordingPacker
from src.engines.e5.reduce import Reducer
from src.engines.e5.trim import Loaded, TrimFailed, expand, trim
from src.engines.e5.trim import to_solution as loaded_to_solution
from src.formats import fits_container
from src.model import UPRIGHT_ORIENTATIONS, ContainerType, Instance, Params, Placement, Solution, is_tipped, item_id, line_of

EPS = 1e-9
REDUCED_COST_TOL = 1e-6
MIN_RETRY_TIME = 0.5  # s: no master re-solve with less time than this left
MONO_FLAT_TEMPERATURE = 0.2  # x T0, e5-mono's "flat" ALNS (0.1 left S c2 lots dearer than e5)
REPACK_SLACK = 1.5  # s past the planned end the last trim may still start core calls (runner kills at 150%)
PACE_MIN_SOLVE = 1.0  # s: e5-v2-pace keeps the last master build time plus this for the final master
REDUCE_SHARE = 0.25  # of a master's time, at most, for the dominance pass of e5-v2-lean
CORES: dict[str, HintedPackOne] = {"e1": e1.pack_one, "e2": e2.pack_one}
# Seeding cores and their engine names: E2b; E1 is control for e5-blocks. Not searched here.
INITIAL_CORES: dict[str, PackOne] = {"e2b": e2b.pack_one, "e1": e1.pack_one}
SEEDED_NAMES: dict[str, str] = {"e2b": "e5-blocks", "e1": "e5-seed-e1"}
SEARCHES = ("alns", "brkga")
PRICINGS = ("greedy", "knapsack")


@dataclass(frozen=True)
class Settings:
    """Time split (option 5A) and pricing knobs."""

    time_share: float = 0.95  # of time_limit, as E4: slack for process start-up and writing the solution
    alns_share: float = 0.60
    pricing_share: float = 0.25  # the integer master gets the rest (0.15)
    pre_mip_share: float = 0.5  # of pricing_share, at most, for the master on harvested columns only
    price_volume: float = 2.0  # a pricing call gets items up to this many times the container's volume (or mass)
    price_noise: float = 1.0  # sd, in ranks, of the noisy order variant in pricing
    search: str = "alns"  # per-core search in the harvest: "alns" (E4, engine e5) or "brkga" (E3, engine e5-brkga)
    alns_iterations: int | None = None  # for tests: cap each ALNS run by iterations, not time
    brkga_generations: int | None = None  # for tests: cap each BRKGA run by generations, not time
    pricing_rounds: int | None = None  # for tests
    tilt_core: bool = False  # probe: add the `e1-tilt` core (engine e5-tilt)
    orient_dense_core: bool = False  # add the `e1-orient-dense` core (engine e5-orient)
    e2_orient: bool = False  # the E2 core tries every allowed orientation (engine e5-orient)
    cores: tuple[str, ...] = ("e1", "e2")  # packing cores of the harvest, pricing and trim (e5-e1, e5-e2)
    initial_core: str | None = None  # this core's initial solve seeds every searched core
    pricing: str = "greedy"  # "greedy" (engine e5) or "knapsack" (engine e5-knap)
    initial_to_end: bool = False  # (engine e5-mono): initial solves may run to the end of the span
    initial_to_end_from: float = 30.0  # s of time_limit; below it initial solves stop at the harvest deadline
    alns_acceptance: str | None = None  # E4's `acceptance` for the harvest ALNS; None keeps E4's tuning
    alns_stall_min: int | None = None  # (e5-v4): ALNS of a core stops when its iterations since the last
    alns_stall_ratio: float = 2.0  # improvement exceed max(alns_stall_min, ratio x the last improvement's index); None: off
    alns_flat_temperature: float | None = None  # E4's `flat_temperature` (x T0); None keeps E4's 0.1
    trim_retries: int = 0  # (e5-mono: 5): re-solves of a master whose cover failed to trim
    reuse_time: bool = False  # (e5-mono): time the final master leaves goes back to ALNS, then the master
    reuse_min: float = 1.0  # s: no new reuse round with less time than this left
    pace: bool = False  # (engine e5-v2-pace): masters and LP build sparse and keep to their deadlines
    sparse_pool: bool = False  # (engine e5-v2-lean): columns keep their nonzero counts only; needs `pace`
    reduce_master: bool = False  # (engine e5-v2-lean): integer masters get the reduced pool (`reduce`)
    master_columns: int = 20_000  # columns kept by reduced cost after the dominance pass
    knap_time: float = 0.2  # s, CP-SAT limit of one knapsack (never past the pricing deadline)
    gamma_start: float = 0.9  # knapsack fill factor, per container type, kept across rounds
    gamma_down: float = 0.05  # taken off when the core did not pack the whole set
    gamma_up: float = 0.02  # added when it packed all
    gamma_min: float = 0.5
    gamma_max: float = 1.0
    ps_initial_share: float = 0.0  # (engines e5-ps, e5-orient-ps): PackingSolver's call on the whole lot gets
    # at most this share of the span (0: no call); the other phases split what is left as before
    ps_price_time: float = 0.0  # s of PackingSolver's knapsack call per container type and pricing round (0: none)
    ps_solver: str = "box"  # PackingSolver's solver, "box" (e5-ps) or "boxstacks" (e5-psbs, with the load and tier limits)
    ps_door_filter: bool = False  # (e5-psbs): send only rotations that pass the container door


# E5's versions, each a fixed `Settings`. v1 is `Settings()` (E5 up to milestone 4; the branch
# variants e5-brkga, e5-knap, ... build on it); v2, v3 and v4 add the settings below. The bare names `e5` and `e5-orient` run the
# default version; the orientation options (`orient_dense_core`, `e2_orient`) apply on top of any version.
VERSIONS: dict[str, Settings] = {
    "e5-v1": Settings(),
    "e5-v2": Settings(initial_to_end=True, alns_acceptance="flat", alns_flat_temperature=MONO_FLAT_TEMPERATURE,
                      trim_retries=5, reuse_time=True),
}
# v3 adds (`pace`) and (`sparse_pool`, `reduce_master`, `master_columns`) to v2.
VERSIONS["e5-v3"] = replace(VERSIONS["e5-v2"], pace=True, sparse_pool=True, reduce_master=True, master_columns=20_000)
# v4 is e5-v3 plus the ALNS stall rule (deterministic, counted in iterations); K_min, r from the m85p pilot.
VERSIONS["e5-v4"] = replace(VERSIONS["e5-v3"], alns_stall_min=2000, alns_stall_ratio=2.0)
# e5-v3-stall (trial name) has v4's settings; listed after e5-v4, so `version_of` and the runs name it e5-v4.
VERSIONS["e5-v3-stall"] = VERSIONS["e5-v4"]
DEFAULT_VERSION = "e5-v4"
# e5-ps / e5-orient-ps are e5-v3 / e5-orient-v3 plus PackingSolver as a column generator (approved: 0.15 x
# span for the initial call, 1 s per container type for each pricing call).
PS_INITIAL_SHARE = 0.15
PS_PRICE_TIME = 1.0
# e5-psbs / e5-orient-psbs: the same with `boxstacks` and the door filter (second round).


def version_of(s: Settings) -> str | None:
    """The version `s` runs, orientation options aside; None for a branch variant or a trial setting."""
    plain = replace(s, orient_dense_core=False, e2_orient=False)
    return next((name for name, v in VERSIONS.items() if v == plain), None)


@dataclass
class _Candidate:
    name: str
    solution: Solution
    key: tuple[float, float]
    sources: list[str] = field(default_factory=list)  # column source of each container, in solution order


@dataclass
class _Core:
    name: str
    packer: RecordingPacker
    initial: list[Box]
    best: list[Box]
    diag: dict[str, Any] = field(default_factory=dict)
    began: float = 0.0  # time.monotonic() at the solve's start, for `last_improvement_time`
    search: Search | None = None  # the core's ALNS run, kept so leftover time resumes it


def solve(
    instance: Instance, params: Params, time_limit: float, seed: int, settings: Settings | None = None,
    start: Solution | None = None,
) -> tuple[Solution, dict[str, Any]]:
    """`start`: an earlier solution of this lot. Checked with the run's params; when valid, its
    containers go into the column pool, it is a candidate (so the result costs no more than it) and it seeds ALNS on
    every searched core where it beats the core's own initial solution. `d["start"]` is "used" or "invalid"."""
    s = settings or VERSIONS["e5-v1"]
    if s.search not in SEARCHES:
        raise ValueError(f"unknown search {s.search!r}; expected one of {SEARCHES}")
    if s.ps_solver not in ("box", "boxstacks"):
        raise ValueError(f"unknown ps_solver {s.ps_solver!r}; expected box or boxstacks")
    if s.pricing not in PRICINGS:
        raise ValueError(f"unknown pricing {s.pricing!r}; expected one of {PRICINGS}")
    if not s.cores or len(set(s.cores)) != len(s.cores) or any(c not in CORES for c in s.cores):
        raise ValueError(f"cores must be a non-empty set of {tuple(CORES)}, got {s.cores!r}")
    if s.initial_core is not None and (s.initial_core not in INITIAL_CORES or s.tilt_core or s.orient_dense_core):
        raise ValueError(f"initial_core must be one of {tuple(INITIAL_CORES)}, without extra cores; got {s.initial_core!r}")
    if s.sparse_pool and not s.pace:
        raise ValueError("sparse_pool needs pace: only the sparse LP and master builds read sparse columns")
    ps_on = s.ps_initial_share > 0.0 or s.ps_price_time > 0.0
    plain = (replace(s, ps_initial_share=0.0, ps_price_time=0.0, ps_solver="box", ps_door_filter=False)
             if ps_on else s)  # the settings without PackingSolver
    ps_columns = (PackingSolverColumns(instance, params, solver=s.ps_solver, door_filter=s.ps_door_filter,
                                       call_time=s.ps_price_time or PS_PRICE_TIME)
                  if ps_on else None)  # PackingSolverMissing if not installed
    began = time.monotonic()
    span = s.time_share * time_limit
    end = began + span
    # PackingSolver's initial call comes first and takes its time off the front; the phases then share
    # what is left as before. Without it `anchor` is `began` and `rest` the span: the deadlines are unchanged.
    anchor, ps_initial, ps_full = began, [], None
    if ps_columns is not None and s.ps_initial_share > 0.0:
        ps_initial, ps_full = ps_columns.initial(min(s.ps_initial_share * span, end - began), end)
        anchor = time.monotonic()
    rest = span if anchor == began else max(end - anchor, 0.0)
    alns_end = anchor + s.alns_share * rest
    pricing_end = anchor + (s.alns_share + s.pricing_share) * rest
    bound = lower_bound(instance).cost
    pool = Pool(instance, s.sparse_pool)
    reducer = Reducer(pool, s.master_columns) if s.reduce_master else None
    d_start: dict[str, Any] = {}
    start_sol = _valid_start(instance, params, start, d_start)
    if start_sol is not None:
        for used in start_sol.containers:
            pool.add(instance.container_type(used.type), [p for p in start_sol.placements if p.k == used.k], "start")
    name = "e5" if s.search == "alns" else f"e5-{s.search}"
    if len(s.cores) == 1:
        name = f"{name}-{s.cores[0]}" if s.search == "brkga" else f"e5-{s.cores[0]}"
    if s.orient_dense_core or s.e2_orient:
        name = "e5-orient"
    if s.pricing == "knapsack":
        name = "e5-knap"
    if s.initial_core is not None:
        name = SEEDED_NAMES[s.initial_core]
    if s.initial_to_end:
        # e5-mono is milestone 4 so far ("flat"); other acceptances keep their candidate's name.
        name = "e5-mono" if s.alns_acceptance in (None, "flat") else f"e5-mono-{s.alns_acceptance}"
        if s.alns_flat_temperature not in (None, MONO_FLAT_TEMPERATURE):  # e5-mono-t10, e5-mono-t30
            name = f"e5-mono-t{round(s.alns_flat_temperature * 100)}"
    version = version_of(plain)
    if version not in (None, "e5-v1"):  # v1 keeps the names its runs were recorded under ("e5", "e5-orient")
        name = f"e5-orient-{version[3:]}" if s.orient_dense_core or s.e2_orient else version
    # Trials on top of a version, not versions themselves. Settings equal to a version (e5-v2-lean is
    # e5-v3, as e5-mono is e5-v2) are recorded under that version's name.
    if version is None and s.pace:
        name = f"{version_of(replace(plain, pace=False)) or name}-pace"
    if version is None and (s.sparse_pool or s.reduce_master):  # a trial on top of e5-v2-pace
        name = f"{version_of(replace(plain, pace=False, sparse_pool=False, reduce_master=False)) or name}-lean"
    if ps_on:  # e5-v3 + PackingSolver is e5-ps, e5-orient-v3 + PackingSolver e5-orient-ps
        name = (name[:-3] if name.endswith("-v3") else name) + ("-psbs" if s.ps_solver == "boxstacks" else "-ps")
    d: dict[str, Any] = {"engine": name, "version": version, "bound": bound, "cores": list(s.cores),
                         "initial_core": s.initial_core, **d_start}
    # (option 1A): a single core has no second initial solve to leave time for, so its initial
    # solve may use the whole span; with both cores the deadline is as before. Engine e5-mono (
    # option 1A): from `initial_to_end_from` seconds, every initial solve may run to the end of the span, so
    # whether E2's initial solve finishes does not hang on the harvest share of `time_limit`; time past
    # `alns_end` comes out of the search, then of pricing. Below it, an E2 that cannot finish anyway would
    # only eat pricing and the master (10 s on S c40: 10% dearer).
    to_end = len(s.cores) == 1 or (s.initial_to_end and time_limit >= s.initial_to_end_from)
    initial_end = end if to_end else alns_end
    d["initial_deadline"] = "end" if to_end else "alns_end"

    # 1. Harvest: both initial solves, then ALNS (or BRKGA) on each core.
    cores: list[_Core] = []
    core_specs = [(n, (e2.pack_one_orient if n == "e2" and s.e2_orient else CORES[n])) for n in s.cores]
    d["orient_e2"] = s.e2_orient
    extra = len(core_specs)
    if s.tilt_core and tilt_changes(instance):
        core_specs.append(("e1-tilt", e1.pack_one_tilt))
    d["tilt_core"] = len(core_specs) > extra
    extra = len(core_specs)
    if s.orient_dense_core and dense_changes(instance, params.delta):
        core_specs.append(("e1-orient-dense", e1.pack_one_orient_dense))
    d["orient_dense_core"] = len(core_specs) > extra
    seeded = None if s.initial_core is None else _seed(instance, params, s.initial_core, initial_end, seed, pool, d)
    for name, pack_one in core_specs:
        t0 = time.monotonic()
        if seeded is not None:
            solution = seeded
        else:
            try:
                solution = fleet.solve(instance, params, max(initial_end - t0, 0.0), seed,
                                       _recording(pack_one, pool, name))
            except fleet.FleetTimeout:
                d[f"{name}_initial_cost"] = None
                d[f"{name}_time_initial"] = round(time.monotonic() - t0, 3)
                if start_sol is None:
                    continue
                solution = start_sol  # no initial solution of its own: ALNS starts from the earlier one
        if start_sol is not None and _solution_cost(instance, start_sol) < _solution_cost(instance, solution) - EPS:
            solution = start_sol
        packer = RecordingPacker(instance, params, pack_one, alns_end, pool, f"{s.search}-{name}")
        initial = from_solution(instance, solution, packer.pieces)
        for box in initial:
            pool.add(box.type, box.placements, name)  # a no-op for the seeding core's boxes: already filed
        cores.append(_Core(name, packer, initial, initial, began=began))
        if seeded is None:
            d[f"{name}_initial_cost"] = _cost(initial)
            d[f"{name}_time_initial"] = round(time.monotonic() - t0, 3)
    if not cores:
        raise fleet.FleetTimeout(f"{instance.name}: no core ({", ".join(s.cores)}) produced an initial solution")
    for layout in ps_initial:  # after the cores' own initial solves: a column both make counts for the core
        pool.add(layout.type, layout.placements, "ps-initial")
    d["columns_initial"] = len(pool)

    searched = [c for c in cores if c.name in s.cores]  # `e1-tilt`, `e1-orient-dense` give columns only, no search
    for n, core in enumerate(searched):
        if min(box_key(c.best) for c in cores)[0] <= bound + EPS:
            break
        now = time.monotonic()
        core_end = now + max(alns_end - now, 0.0) / (len(searched) - n)
        core.packer.deadline = core_end
        if s.search == "brkga":
            core.best, core.diag = _brkga(instance, core, s, seed, bound, core_end)
        else:
            core.best, core.diag = _alns(instance, core, s, seed, bound, core_end)
        for box in core.best:
            pool.add(box.type, box.placements, f"{s.search}-{core.name}")
        core.diag["cost"] = _cost(core.best)
        core.diag["time"] = round(time.monotonic() - now, 3)
        d[f"{core.name}_{s.search}"] = core.diag
    incumbent_core = min(cores, key=lambda c: box_key(c.best))
    incumbent = incumbent_core.best
    d["columns_harvested"] = len(pool)
    d["incumbent_cost"] = _cost(incumbent)
    d["incumbent_core"] = incumbent_core.name
    d["time_harvest"] = round(time.monotonic() - began, 3)
    candidates = [_Candidate(f"{s.search}-{incumbent_core.name}", boxes_to_solution(instance, params, incumbent),
                             box_key(incumbent), [_box_source(pool, b) for b in incumbent])]
    if ps_full is not None:  # PackingSolver's whole-lot solution, valid as returned
        candidates.append(_Candidate("ps-initial", ps_full, _solution_key(instance, ps_full),
                                     ["ps-initial"] * len(ps_full.containers)))

    keep = None
    if start_sol is not None:
        keep = _Candidate("start", start_sol, box_key(from_solution(instance, start_sol, cores[0].packer.pieces)),
                          ["start"] * len(start_sol.containers))
        candidates.append(keep)

    if _cost(incumbent) <= bound + EPS:
        d["stop"] = "bound"
        return _finish(candidates, d, began, instance, keep, ps_columns)

    # 2. Master on harvested columns only.
    incumbent_cover = _cover(pool, incumbent)
    best_cover = incumbent_cover
    pre_limit = min(s.pre_mip_share * s.pricing_share * rest, max(pricing_end - time.monotonic(), 0.0))
    # e5-v2-lean: the LP first, for the duals the reduction ranks by; pricing's first round reuses it.
    pre_lp, pre_lp_columns, duals = None, -1, None
    if reducer is not None:
        pre_lp = master.solve_lp(instance, pool.columns, max(pricing_end - time.monotonic(), 0.0), True)
        pre_lp_columns = len(pool)
        duals = pre_lp.duals if pre_lp.value is not None else None
        d["pre_lp"] = {"status": pre_lp.status, "value": pre_lp.value, "time": round(pre_lp.time, 3),
                       "build": round(pre_lp.build, 3), "columns": pre_lp_columns}
        pre_limit = min(pre_limit, max(pricing_end - time.monotonic(), 0.0))
    forced = set(incumbent_cover)  # e5-v2-lean: in every reduced master, as is the hint
    pre, cand, d["pre_pricing"] = _master(instance, params, pool, incumbent_cover, pre_limit, pricing_end,
                                          "mip-harvest", [c.packer for c in cores], pricing_end, s.trim_retries,
                                          s.pace, reducer, duals, forced)
    if cand is not None:
        candidates.append(cand)
        if pre.cost is not None and pre.cost < _cover_cost(pool, best_cover) - EPS:
            best_cover = pre.counts
    d["cost_harvest"] = min(c.key for c in candidates)[0]

    # 3. Pricing. e5-v2-pace (options 3A, 4A): pricing also stops where the final master's reserve
    # (its last build time plus PACE_MIN_SOLVE) begins, GLOP gets the time left, and no round starts with less
    # time left than the last LP took (the first: the pre-pricing master's build).
    t0 = time.monotonic()
    rng = random.Random(seed)
    reserve = _reserve(d["pre_pricing"])
    if s.pace:
        pricing_end = min(pricing_end, end - reserve)
    lp_estimate = d["pre_pricing"]["build"] if pre_lp is None else pre_lp.time
    reuse_lp = pre_lp is not None and pre_lp.value is not None and len(pool) == pre_lp_columns
    lp_reused = reuse_lp
    lp_build: list[float] = []
    lp_solve: list[float] = []
    packers = {c.name: c.packer for c in cores}
    for p in packers.values():
        p.deadline = pricing_end
    lp_values: list[float] = []
    rounds = added = 0
    knap = _Knap(s) if s.pricing == "knapsack" else None
    stop = "time"
    while True:
        if s.pricing_rounds is not None and rounds >= s.pricing_rounds:
            stop = "rounds"
            break
        if time.monotonic() >= pricing_end:
            break
        if s.pace and not reuse_lp and pricing_end - time.monotonic() < lp_estimate:
            stop = "pace"
            break
        if reuse_lp:  # e5-v2-lean: the LP solved before the pre-pricing master, on this same pool
            lp, reuse_lp = pre_lp, False
            if knap is not None:
                knap.lp, knap.lp_columns = lp, len(pool)
        elif knap is None or knap.lp is None or knap.lp_columns != len(pool):
            lp_limit = max(pricing_end - time.monotonic(), 0.0) if s.pace else None
            lp = master.solve_lp(instance, pool.columns, lp_limit, s.pace)
            lp_build.append(round(lp.build, 3))
            lp_solve.append(round(lp.time - lp.build, 3))
            lp_estimate = lp.time
            if knap is not None:
                knap.lp, knap.lp_columns = lp, len(pool)
        else:
            lp = knap.lp  # pool unchanged since the last round: same duals, new gamma
        if lp.value is None:
            stop = "lp_time" if lp.status == "TIME" else "lp"
            break
        lp_values.append(round(lp.value, 6))
        duals = lp.duals
        before = len(pool)
        if knap is not None:
            knap.shrunk = False
        try:
            if knap is None:
                _price(instance, pool, packers, lp.duals, rng, s)
            else:
                _price_knapsack(instance, pool, packers, lp.duals, rng, s, knap)
            if ps_columns is not None and s.ps_price_time > 0.0:
                _price_packingsolver(instance, pool, ps_columns, lp.duals, s, pricing_end)
        except Deadline:
            pass
        rounds += 1
        new = [c for c in pool.columns[before:] if _reduced_cost(c, lp.duals) < -REDUCED_COST_TOL]
        added += len(new)
        if knap is not None:
            knap.negative.append(len(new))
        if not new and knap is not None and knap.shrunk:
            continue  # gamma went down for some type: try the smaller sets before giving up
        if not new:
            stop = "no_column" if time.monotonic() < pricing_end else "time"
            break
    d["pricing"] = {"rounds": rounds, "columns_negative": added, "stop": stop,
                    "time": round(time.monotonic() - t0, 3), "lp_build": lp_build, "lp_solve": lp_solve}
    if knap is not None:
        d["pricing"].update(knap.diagnostics())
    if reducer is not None:
        d["pricing"]["lp_reused"] = lp_reused
    # Not a lower bound: columns come from a heuristic core (solution-approaches §5.1).
    d["lp_value_harvest"] = lp_values[0] if lp_values else None
    d["lp_value"] = lp_values[-1] if lp_values else None

    # 4. Integer master over every column. e5-v2-pace: skipped when less than its reserve is left; the
    # candidates so far stay, so the result is no worse than the incumbent.
    if s.pace and end - time.monotonic() < reserve:
        d["final"] = {"skipped": "pace", "reserve": round(reserve, 3)}
    else:
        final, cand, d["final"] = _master(instance, params, pool, best_cover, max(end - time.monotonic(), 0.0), end,
                                          "mip-final", [c.packer for c in cores], end + REPACK_SLACK,
                                          s.trim_retries, s.pace, reducer, duals, forced)
        if cand is not None:
            candidates.append(cand)
        if s.reuse_time:
            if final.cost is not None and final.cost < _cover_cost(pool, best_cover) - EPS:
                best_cover = final.counts
            reserve = _reserve(d["final"])
            d["reuse"] = _reuse(instance, params, pool, searched, candidates, best_cover, bound, end, s, reserve,
                                reducer, duals, forced)
    d["columns"] = len(pool)
    d["columns_by_source"] = _by_source(pool)
    d["stop"] = "time"
    return _finish(candidates, d, began, instance, keep, ps_columns)


def _reuse(
    instance: Instance, params: Params, pool: Pool, cores: list[_Core], candidates: list[_Candidate],
    best_cover: dict[int, int], bound: float, end: float, s: Settings, reserve: float,
    reducer: Reducer | None = None, duals: list[float] | None = None, keep: set[int] | None = None,
) -> dict[str, Any]:
    """Leftover time (engine e5-mono): while the final master leaves at least `reuse_min` seconds,
    each core's ALNS resumes where it stopped for `alns_share` of what is left (split evenly, as in the
    harvest), its columns filed into the pool, then the master runs on the grown pool until `end`. Resuming
    keeps each core on one trajectory, so the prefix property holds. Stops at the bound, when no search
    can go on, or when a round adds no column. New candidates are appended to `candidates`. e5-v2-pace:
    `reserve` (the last master's build time plus PACE_MIN_SOLVE) is kept for each master: no round starts
    without it, and ALNS stops where it begins. e5-v2-lean: each master gets the pool reduced by
    `reducer` under `duals` (the last pricing LP's), keeping the hint (best cover) and `keep` (the incumbent's)."""
    out: dict[str, Any] = {"rounds": 0, "stop": "time", "iterations": {}, "columns_added": 0, "masters": []}
    t0 = time.monotonic()
    packers = [c.packer for c in cores]
    while True:
        now = time.monotonic()
        if end - now < s.reuse_min + (reserve if s.pace else 0.0):
            break
        if min(c.key for c in candidates)[0] <= bound + EPS:
            out["stop"] = "bound"
            break
        live = [c for c in cores if c.search is not None and c.search.stop == "time"]
        if s.alns_stall_min is not None and not live and any(c.search is not None and c.search.stop == "stall"
                                                              for c in cores):
            out["stop"] = "stall"  # no core to resume, none worth it
            break
        if not live:
            out["stop"] = "search"
            break
        alns_until = now + s.alns_share * (end - now)
        if s.pace:
            alns_until = min(alns_until, end - reserve)
        before = len(pool)
        for n, core in enumerate(live):
            t = time.monotonic()
            core_end = t + max(alns_until - t, 0.0) / (len(live) - n)
            core.packer.deadline = core_end
            start_iterations = core.search.iterations
            outcome = core.search.advance(core_end)
            out["iterations"][core.name] = out["iterations"].get(core.name, 0) + outcome.iterations - start_iterations
            _improvement_diag(core, core.diag)
            out.setdefault("last_improvement_iteration", {})[core.name] = core.search.last_improvement_iteration
            if box_key(outcome.best) < box_key(core.best):
                core.best = outcome.best
                candidates.append(_Candidate(f"{s.search}-{core.name}", boxes_to_solution(instance, params, core.best),
                                             box_key(core.best), [_box_source(pool, b) for b in core.best]))
                cover = _cover(pool, core.best)
                if _cover_cost(pool, cover) < _cover_cost(pool, best_cover) - EPS:
                    best_cover = cover
            for box in core.best:
                pool.add(box.type, box.placements, f"{s.search}-{core.name}")
        out["rounds"] += 1
        out["columns_added"] += len(pool) - before
        if len(pool) == before:
            out["stop"] = "no_column"
            break
        if s.pace and end - time.monotonic() < reserve:
            out["stop"] = "pace"
            break
        res, cand, diag = _master(instance, params, pool, best_cover, max(end - time.monotonic(), 0.0), end,
                                  "mip-reuse", packers, end + REPACK_SLACK, s.trim_retries, s.pace, reducer, duals,
                                  keep)
        out["masters"].append({k: diag.get(k) for k in ("status", "cost", "columns", "time", "build", "cost_trimmed")})
        if "reduce" in diag:
            out["masters"][-1]["reduce"] = diag["reduce"]
        reserve = _reserve(diag)
        if cand is not None:
            candidates.append(cand)
        if res.cost is not None and res.cost < _cover_cost(pool, best_cover) - EPS:
            best_cover = res.counts
    out["time"] = round(time.monotonic() - t0, 3)
    return out


# --- harvesting -----------------------------------------------------------------------------------


def _alns(
    instance: Instance, core: _Core, s: Settings, seed: int, bound: float, core_end: float
) -> tuple[list[Box], dict[str, Any]]:
    """E4's ALNS on one core, E4's tuned settings for that core."""
    alns_settings = ALNS_DEFAULTS[core.name]
    if s.alns_iterations is not None:
        alns_settings = replace(alns_settings, max_iterations=s.alns_iterations)
    if s.alns_acceptance is not None:
        alns_settings = replace(alns_settings, acceptance=s.alns_acceptance)
    if s.alns_flat_temperature is not None:
        alns_settings = replace(alns_settings, flat_temperature=s.alns_flat_temperature)
    if s.alns_stall_min is not None:
        alns_settings = replace(alns_settings, stall_min=s.alns_stall_min, stall_ratio=s.alns_stall_ratio)
    ctx = Context(instance, core.packer, random.Random(seed), alns_settings)
    core.search = Search(core.initial, ctx, bound)
    outcome = core.search.advance(core_end)
    diag = {"iterations": outcome.iterations, "improvements": outcome.improvements, "stop": outcome.stop}
    _improvement_diag(core, diag)
    return outcome.best, diag


def _improvement_diag(core: _Core, diag: dict[str, Any]) -> None:
    """where the core's ALNS improved, counted from its search's start and across resumes (the list
    is capped at E4's IMPROVEMENT_CAP entries). Refreshed in `_reuse`, so the final state is what stays."""
    search = core.search
    diag["improvement_iterations"] = list(search.improvement_iterations)
    diag["last_improvement_iteration"] = search.last_improvement_iteration
    diag["last_improvement_time"] = (None if search.last_improvement_time is None
                                     else round(search.last_improvement_time - core.began, 3))


def _brkga(
    instance: Instance, core: _Core, s: Settings, seed: int, bound: float, core_end: float
) -> tuple[list[Box], dict[str, Any]]:
    """E3's BRKGA on one core, E3's tuned settings for that core (option 2A). The initial
    solution E5 already has is the incumbent and seeds the population (option 3A); it is not solved
    again."""
    brkga_settings = BRKGA_DEFAULTS[core.name]
    if s.brkga_generations is not None:
        brkga_settings = replace(brkga_settings, max_generations=s.brkga_generations)
    decoder = Decoder(instance, core.packer, slots_for(len(core.initial)))
    outcome = brkga(decoder, core.initial, [b.type.id for b in core.initial], brkga_settings,
                    random.Random(seed), bound, core_end)
    return outcome.best, {"population": outcome.population, "generations": outcome.generations,
                          "decodes": outcome.decodes, "improvements": outcome.improvements,
                          "restarts": outcome.restarts, "stop": outcome.stop,
                          "pack_one_calls": core.packer.calls, "cache_hits": core.packer.hits}


def _seed(
    instance: Instance, params: Params, core: str, until: float, seed: int, pool: Pool, d: dict[str, Any]
) -> Solution:
    """The seeding core's full solve, every core call filed into the pool under its name."""
    t0 = time.monotonic()
    try:
        solution = fleet.solve(instance, params, max(until - t0, 0.0), seed, _recording(INITIAL_CORES[core], pool, core))
    except fleet.FleetTimeout as exc:
        d[f"{core}_initial_cost"] = None
        d[f"{core}_time_initial"] = round(time.monotonic() - t0, 3)
        raise fleet.FleetTimeout(f"{instance.name}: seeding core {core} produced no initial solution") from exc
    d[f"{core}_initial_cost"] = round(sum(instance.container_type(c.type).cost for c in solution.containers), 9)
    d[f"{core}_time_initial"] = round(time.monotonic() - t0, 3)
    return solution


def dense_changes(instance: Instance, delta: float) -> bool:
    """Whether E1's dense rule orients some line differently from its base rule in some container type."""
    for line in instance.items:
        piece = Piece(line.id, line.L, line.W, line.H, line.mass, line.tippable, line.tiers, line.load, line.orientations)
        if any(dense_orientation(piece, t, delta) != base_orientation(piece, t) for t in instance.container_types):
            return True
    return False


def tilt_changes(instance: Instance) -> bool:
    """Whether E1's tilt-first rule orients some tippable line differently in some container type."""
    for line in instance.items:
        if not any(c not in UPRIGHT_ORIENTATIONS for c in line.allowed):
            continue
        piece = Piece(line.id, line.L, line.W, line.H, line.mass, line.tippable, line.tiers, line.load, line.orientations)
        if any(tilt_first_orientation(piece, t) != base_orientation(piece, t) for t in instance.container_types):
            return True
    return False


def _recording(pack_one: HintedPackOne, pool: Pool, source: str):
    """The fleet layer's `PackOne`, filing every result into the pool (all four per-type plans, not
    only the one the layer keeps)."""

    def wrapped(items: list[Piece], ctype: ContainerType, params: Params, rng: random.Random) -> list[Placement]:
        placed = pack_one(items, ctype, params, rng)
        pool.add(ctype, placed, source)
        return placed

    return wrapped


def _valid_start(instance: Instance, params: Params, start: Solution | None, diag: dict[str, Any]) -> Solution | None:
    """`start` if the checker accepts it for this lot and these params, else None; `diag["start"]` says which."""
    if start is None:
        return None
    try:
        ok = check(instance, start, params).ok
    except Exception:  # noqa: BLE001 - a start the checker cannot even read is an invalid one
        ok = False
    diag["start"] = "used" if ok else "invalid"
    return start if ok else None


def _solution_cost(instance: Instance, solution: Solution) -> float:
    return sum(instance.container_type(c.type).cost for c in solution.containers)


def _cost(boxes: list[Box]) -> float:
    return box_key(boxes)[0]


def _cover(pool: Pool, boxes: list[Box]) -> dict[int, int]:
    out: dict[int, int] = {}
    for box in boxes:
        p = pool.add(box.type, box.placements, "incumbent")
        assert p is not None
        out[p] = out.get(p, 0) + 1
    return out


def _cover_cost(pool: Pool, counts: dict[int, int]) -> float:
    return sum(pool.columns[p].cost * n for p, n in counts.items())


# --- pricing --------------------------------------------------------------------------------------


def _reduced_cost(col, duals: list[float]) -> float:
    if col.sparse:
        return col.cost - sum(duals[i] * a for i, a in col.nonzero)
    return col.cost - sum(pi * a for pi, a in zip(duals, col.counts))


def _price(
    instance: Instance, pool: Pool, packers: dict[str, RecordingPacker], duals: list[float], rng: random.Random,
    s: Settings,
) -> None:
    """One pricing round: for each core, container type and order variant, one core call on the
    lines with a positive dual, best dual per unit volume first; every result lands in the pool."""
    lines = [(i, line) for i, line in enumerate(instance.items) if duals[i] > EPS]
    ranked = sorted(lines, key=lambda il: (-duals[il[0]] / il[1].volume, il[0]))
    for packer in packers.values():
        for ctype in sorted(instance.container_types, key=lambda t: t.cost):
            chosen = [(i, line) for i, line in ranked if fits_container(line, ctype)]
            if not chosen:
                continue
            items = _items(chosen, ctype, s.price_volume)
            plain = tuple((line.id, float(r)) for r, (_, line) in enumerate(chosen))
            noisy = tuple((line.id, r + rng.gauss(0.0, s.price_noise)) for r, (_, line) in enumerate(chosen))
            turned = tuple((line.id, True) for _, line in chosen)
            for hints in (Hints(order=plain), Hints(order=plain, turn=turned), Hints(order=noisy)):
                packer.pack(items, ctype, hints)


@dataclass
class _Knap:
    """State of knapsack pricing across rounds: `gamma` per container type and the counters."""

    s: Settings
    gamma: dict[str, float] = field(default_factory=dict)
    solves: int = 0
    sets: int = 0  # knapsack sets with sum(pi a) > c_t: the ones the core was called on
    full: int = 0  # ... of which some order variant had the core pack every item
    time: float = 0.0
    negative: list[int] = field(default_factory=list)  # new negative columns per round
    shrunk: bool = False  # gamma went down for some type this round: another round may still find a column
    lp: Any = None  # the last LP and the pool size it was solved on, reused while the pool is unchanged
    lp_columns: int = -1

    def update(self, type_id: str, packed_all: bool) -> None:
        s = self.s
        old = self.gamma.get(type_id, s.gamma_start)
        self.gamma[type_id] = knapsack.next_gamma(old, packed_all, s.gamma_down, s.gamma_up, s.gamma_min,
                                                  s.gamma_max)
        self.shrunk |= self.gamma[type_id] < old

    def diagnostics(self) -> dict[str, Any]:
        return {"mode": "knapsack", "knapsack_solves": self.solves, "knapsack_sets_over_cost": self.sets,
                "knapsack_full_share": round(self.full / self.sets, 3) if self.sets else None,
                "negative_per_round": list(self.negative),
                "gamma": {k: round(v, 3) for k, v in self.gamma.items()},
                "knapsack_time": round(self.time, 3)}


def _price_knapsack(
    instance: Instance, pool: Pool, packers: dict[str, RecordingPacker], duals: list[float], rng: random.Random,
    s: Settings, knap: _Knap,
) -> None:
    """One pricing round, knapsack variant: for each core and container type, the best set for
    the duals within `gamma` of the container (`knapsack.solve`); skipped unless its dual value exceeds the
    container's cost. The set goes to the core in the three order variants of `_price`; results enter the
    pool only when their reduced cost is negative."""
    lines = [(i, line) for i, line in enumerate(instance.items) if duals[i] > EPS]
    ranked = sorted(lines, key=lambda il: (-duals[il[0]] / il[1].volume, il[0]))

    def negative(ctype: ContainerType, placed: list[Placement]) -> bool:
        counts = pool.counts_of(line_of(p.item) for p in placed)
        return bool(placed) and ctype.cost - sum(pi * a for pi, a in zip(duals, counts)) < -REDUCED_COST_TOL

    for packer in packers.values():
        for ctype in sorted(instance.container_types, key=lambda t: t.cost):
            chosen = [(i, line) for i, line in ranked if fits_container(line, ctype)]
            if not chosen:
                continue
            left = packer.deadline - time.monotonic()
            if left <= 0.0:
                raise Deadline
            gamma = knap.gamma.setdefault(ctype.id, s.gamma_start)
            t0 = time.monotonic()
            counts = knapsack.solve([duals[i] for i, _ in chosen], [l.volume for _, l in chosen],
                                    [l.mass for _, l in chosen], [l.qty for _, l in chosen],
                                    gamma * ctype.volume, gamma * ctype.max_mass, min(s.knap_time, left),
                                    [knapsack.floor_share(l.L, l.W, l.H, l.mass, l.tiers, l.load, ctype.H)
                                     for _, l in chosen],
                                    gamma * ctype.L * ctype.W)
            knap.time += time.monotonic() - t0
            knap.solves += 1
            if sum(duals[i] * a for (i, _), a in zip(chosen, counts)) <= ctype.cost + REDUCED_COST_TOL:
                continue
            knap.sets += 1
            picked = [(il, a) for il, a in zip(chosen, counts) if a > 0]
            sel = [il for il, _ in picked]
            items = [item_id(line.id, n) for (_, line), a in picked for n in range(1, a + 1)]
            plain = tuple((line.id, float(r)) for r, (_, line) in enumerate(sel))
            noisy = tuple((line.id, r + rng.gauss(0.0, s.price_noise)) for r, (_, line) in enumerate(sel))
            turned = tuple((line.id, True) for _, line in sel)
            packed_all = False
            packer.admit = negative
            try:
                for hints in (Hints(order=plain), Hints(order=plain, turn=turned), Hints(order=noisy)):
                    packed_all |= len(packer.pack(items, ctype, hints)) == len(items)
            finally:
                packer.admit = None
            knap.full += packed_all
            knap.update(ctype.id, packed_all)


def _price_packingsolver(
    instance: Instance, pool: Pool, ps: PackingSolverColumns, duals: list[float], s: Settings, until: float
) -> None:
    """One pricing round of PackingSolver: per container type, cheapest first, one knapsack call whose item
    values are the lines' duals; each valid container whose reduced cost is negative enters the pool (the others
    would not help the master). A call gets `ps_price_time` s, never past `until`."""
    profits = {i: pi for i, pi in enumerate(duals) if pi > EPS}
    for ctype in sorted(instance.container_types, key=lambda t: t.cost):
        left = until - time.monotonic()
        if left <= 0.0:
            raise Deadline
        usable = {i: pi for i, pi in profits.items() if fits_container(instance.items[i], ctype)}
        for layout in ps.knapsack(ctype, usable, min(s.ps_price_time, left), until):
            counts = pool.counts_of(line_of(p.item) for p in layout.placements)
            if ctype.cost - sum(pi * a for pi, a in zip(duals, counts)) < -REDUCED_COST_TOL:
                pool.add(ctype, layout.placements, "ps-pricing")


def _solution_key(instance: Instance, solution: Solution) -> tuple[float, float]:
    """A candidate's key (cost, emptiest container's fill) for a whole solution, as `_emptiest` for trimmed boxes."""
    lines = {line.id: line for line in instance.items}
    fills = []
    for used in solution.containers:
        ctype = instance.container_type(used.type)
        mine = [lines[line_of(p.item)] for p in solution.placements if p.k == used.k]
        fills.append(max(sum(l.volume for l in mine) / ctype.volume, sum(l.mass for l in mine) / ctype.max_mass))
    return round(_solution_cost(instance, solution), 9), min(fills, default=0.0)


def _items(chosen: list, ctype: ContainerType, factor: float) -> list[str]:
    """Items of the chosen lines in their order, up to `factor` times the container's volume or
    mass: enough choice for the core without paying for a whole large lot in one call."""
    out: list[str] = []
    volume = mass = 0.0
    for _, line in chosen:
        for n in range(1, line.qty + 1):
            if volume >= factor * ctype.volume or mass >= factor * ctype.max_mass:
                return out
            out.append(item_id(line.id, n))
            volume += line.volume
            mass += line.mass
    return out


# --- master solutions -----------------------------------------------------------------------------


def _mip_diag(res: master.MIPResult, columns: int) -> dict[str, Any]:
    return {"status": res.status, "cost": res.cost, "bound": res.bound, "columns": columns,
            "containers": sum(res.counts.values()), "time": round(res.time, 3), "build": round(res.build, 3),
            "solve": round(res.time - res.build, 3)}


def _reserve(diag: dict[str, Any]) -> float:
    """e5-v2-pace's reserve for the next master: the last one's build (and, e5-v2-lean, its reduction) plus
    PACE_MIN_SOLVE."""
    reserve = diag["build"] + PACE_MIN_SOLVE
    if "reduce" in diag:
        reserve += diag["reduce"]["time"]
    return reserve


def _master(
    instance: Instance,
    params: Params,
    pool: Pool,
    hint: dict[int, int],
    first_limit: float,
    until: float,
    name: str,
    packers: list[RecordingPacker],
    repack_until: float,
    retries: int,
    pace: bool = False,
    reducer: Reducer | None = None,
    duals: list[float] | None = None,
    keep: set[int] | None = None,
) -> tuple[master.MIPResult, _Candidate | None, dict[str, Any]]:
    """The integer master and its trimmed, checked candidate. When the cover fails to trim (
    option 2A), the failed line's cover is capped at its qty plus the surplus trim did remove, which cuts
    off that cover, and the master is solved again with what is left until `until`, at most `retries`
    times. The diagnostics are the last attempt's, with `retries` and the caps. `pace`: sparse
    build, SCIP's limit net of the build, and no re-solve with less than the last build plus MIN_RETRY_TIME left.
    `reducer` (e5-v2-lean): SCIP gets the pool reduced under `duals`, keeping the hint's and `keep`'s
    columns, for every attempt; its counts are mapped back to pool indices. The reduction's time comes off the first
    attempt's limit."""
    caps: dict[int, int] = {}
    index = {line.id: i for i, line in enumerate(instance.items)}
    limit = first_limit
    columns, local_hint, kept, reduction = pool.columns, hint, None, None
    if reducer is not None:
        reduction = reducer.reduce(set(hint) | (keep or set()), duals, time.monotonic() + REDUCE_SHARE * first_limit)
        kept = reduction.index
        position = {p: j for j, p in enumerate(kept)}
        columns = [pool.columns[p] for p in kept]
        local_hint = {position[p]: n for p, n in hint.items()}
        limit = first_limit - reduction.time
    for attempt in range(retries + 1):
        res = master.solve_mip(instance, columns, local_hint, limit, caps, sparse=pace, net_of_build=pace)
        if kept is not None:
            res = replace(res, counts={kept[j]: n for j, n in res.counts.items()})
        diag = _mip_diag(res, len(columns))
        if reduction is not None:
            diag["reduce"] = reduction.diagnostics()
        cand = _from_mip(instance, params, pool, res, name, diag, packers, repack_until)
        if retries:
            diag["retries"] = attempt
            diag["caps"] = {instance.items[i].id: c for i, c in caps.items()}
        line, removable = diag.pop("_trim_line", None), diag.pop("_trim_removable", 0)
        limit = until - time.monotonic()
        if cand is not None or line is None or attempt == retries or limit < MIN_RETRY_TIME + (res.build if pace else 0.0):
            return res, cand, diag
        i = index[line]
        caps[i] = min(caps.get(i, 10**9), instance.items[i].qty + removable)
    raise AssertionError("unreachable")


def _from_mip(
    instance: Instance,
    params: Params,
    pool: Pool,
    res: master.MIPResult,
    name: str,
    diag: dict[str, Any],
    packers: list[RecordingPacker],
    repack_until: float,
) -> _Candidate | None:
    if res.cost is None:
        return None
    try:
        out = trim(instance, expand(pool.columns, res.counts), _repacker(packers, repack_until))
    except TrimFailed as exc:
        diag["trim_failed"] = str(exc)
        if exc.line is not None:
            diag["_trim_line"], diag["_trim_removable"] = exc.line, exc.surplus - exc.left  # for `_master` only
        return None
    boxes = out.boxes
    diag["trimmed_items"] = out.removed
    diag["repacked_containers"] = out.repacked
    solution = loaded_to_solution(instance, params, boxes)
    result = check(instance, solution, params)
    diag["checker_ok"] = result.ok
    if not result.ok:
        diag["checker_violations"] = len(result.violations)
        return None
    diag["cost_trimmed"] = round(result.cost, 9)
    return _Candidate(name, solution, (round(result.cost, 9), _emptiest(instance, boxes)), [b.source for b in boxes])


def _repacker(packers: list[RecordingPacker], until: float):
    """Trim's fallback: the cores in turn (E1 first), each on an empty container of the type, with
    no hints; the first placing every item wins. No new call starts after `until`."""

    def repack(ctype: ContainerType, lines: list[str]) -> list | None:
        seen: dict[str, int] = {}
        items = []
        for line in lines:
            seen[line] = seen.get(line, 0) + 1
            items.append(item_id(line, seen[line]))
        for packer in packers:
            old = packer.deadline
            packer.deadline = until
            try:
                placed = packer.pack(items, ctype)
            except Deadline:
                return None
            finally:
                packer.deadline = old
            if len(placed) == len(items):
                return [(line_of(p.item), p.x, p.y, p.z, p.o) for p in placed]
        return None

    return repack


def _emptiest(instance: Instance, boxes: list[Loaded]) -> float:
    lines = {line.id: line for line in instance.items}
    fills = []
    for box in boxes:
        v = sum(lines[s[0]].volume for s in box.slots)
        m = sum(lines[s[0]].mass for s in box.slots)
        fills.append(max(v / box.type.volume, m / box.type.max_mass))
    return min(fills, default=0.0)


def _by_source(pool: Pool) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in pool.columns:
        out[c.source] = out.get(c.source, 0) + 1
    return out


def _box_source(pool: Pool, box: Box) -> str:
    """The pool column a harvest box stands for: the first source to file this (type, counts)."""
    found = pool.index(pool.key_of(box.type, (line_of(p.item) for p in box.placements)))
    return pool.columns[found].source if found is not None else "incumbent"


def _family(source: str) -> str:
    """A column source's core: "alns-e1-orient-dense" -> "e1-orient-dense"; "incumbent" and "" -> "other"."""
    for prefix in SEARCHES:
        if source.startswith(prefix + "-"):
            source = source[len(prefix) + 1:]
    if source.startswith("ps-"):  # PackingSolver's columns, "ps-initial" and "ps-pricing"
        return "ps"
    return source if source in ("e1", "e2", "e2b", "e1-orient-dense", "e1-tilt") else "other"


def _orientation_diagnostics(instance: Instance, best: _Candidate) -> dict[str, Any]:
    """Containers and tipped pieces of the returned solution by source core."""
    containers: dict[str, int] = {}
    tipped: dict[str, int] = {}
    family = {c.k: _family(src) for c, src in zip(best.solution.containers, best.sources)}
    for k, fam in family.items():
        containers[fam] = containers.get(fam, 0) + 1
    for p in best.solution.placements:
        if is_tipped(p.o):
            fam = family.get(p.k, "other")
            tipped[fam] = tipped.get(fam, 0) + 1
    return {"containers_by_core": containers, "tipped_by_core": tipped,
            "containers_from_e1_orient_dense": containers.get("e1-orient-dense", 0), "tipped_pieces": sum(tipped.values())}


def _finish(
    candidates: list[_Candidate], d: dict[str, Any], start: float, instance: Instance,
    keep: _Candidate | None = None, ps: PackingSolverColumns | None = None,
) -> tuple[Solution, dict[str, Any]]:
    best = min(candidates, key=lambda c: c.key)  # first (the incumbent) on a tie
    if keep is not None and best.key[0] >= keep.key[0] - EPS:
        best = keep  # nothing cheaper than the earlier solution: it is handed back as it was
    if ps is not None:
        d["packingsolver"] = {**ps.stats.as_dict(), **ps.report,
                              "containers_in_solution": sum(src.startswith("ps-") for src in best.sources)}
    d.update(_orientation_diagnostics(instance, best))
    d["source"] = best.name
    d["cost"] = best.key[0]
    d.setdefault("cost_harvest", d["cost"])
    d["time_total"] = round(time.monotonic() - start, 3)
    return best.solution, d
