"""Pool reduction before each integer master (engine e5-v2-lean).

On a lot of 486 lines the pool reaches ~116 000 columns and SCIP on all of them takes most of E5's memory. Before
each integer master the column list it gets is cut in two steps; the pool itself keeps every column:

1. **Dominated columns** go: column q is dominated when another column p of the same container type (same cost)
   holds at least as many items of every line. Any cover using q stays a cover, at the same cost, with p instead;
   the pool keeps one column per (type, counts), so p holds strictly more items in total. Dominance is transitive,
   so dropping every dominated column keeps an undominated dominator of each. Candidates p for q come from the
   posting list of q's rarest line (columns of the type holding that line), filtered by total items, then checked
   on q's lines at once (a dense per-type count matrix, built per call). A dominated column stays dominated as the
   pool grows, and a column already checked against the first n columns is checked only against later ones; the
   pass stops at a deadline, leaving the rest unchecked.
2. If more than `limit` (`Settings.master_columns`) columns are left, the `limit` with the lowest reduced cost
   under the given duals are kept (ties: pool order).

Columns in `keep` (the master's hint and the best known cover) are always kept, so the hint stays feasible.
"""
from __future__ import annotations

import time
from array import array
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.engines.e5.pool import Pool

MAX_CELLS = 100_000_000  # columns x lines of one container type above which the dominance pass skips that type
BLOCK = 2_000_000  # array cells per vectorized comparison step (memory of one step: ~8 bytes a cell)


@dataclass
class Reduction:
    index: list[int]  # pool indices handed to the master, ascending
    before: int
    dominated: int  # removed as dominated
    cut: int  # removed by the reduced-cost cut
    kept_by_reduced_cost: int | None  # columns the cut kept (None: no cut)
    forced: int  # columns of `keep`
    duals: str | None  # what the cut ranked by: "lp", "volume" (no LP duals), None (no cut)
    complete: bool  # the dominance pass checked every column
    time: float

    def diagnostics(self) -> dict[str, Any]:
        return {"before": self.before, "after": len(self.index), "dominated": self.dominated, "cut": self.cut,
                "kept_by_reduced_cost": self.kept_by_reduced_cost, "forced": self.forced, "duals": self.duals,
                "complete": self.complete, "time": round(self.time, 3)}


class Reducer:
    """The pool's columns as flat arrays (one entry per nonzero count, appended as the pool grows) and what the
    dominance pass already knows, kept across the masters of one run."""

    def __init__(self, pool: Pool, limit: int) -> None:
        self.pool = pool
        self.limit = limit  # columns past the dominance pass kept by reduced cost
        self.starts = array("q", [0])  # entries of column p: starts[p]:starts[p + 1]
        self.lines = array("i")
        self.vals = array("i")
        self.types = array("i")  # per column: index into type_ids
        self.costs = array("d")
        self.type_ids: dict[str, int] = {}
        self.dominated = np.zeros(0, dtype=bool)
        self.checked = np.zeros(0, dtype=np.int64)  # column p was compared with every column below checked[p]

    def _sync(self) -> int:
        n0, n = len(self.types), len(self.pool)
        for col in self.pool.columns[n0:]:
            pairs = col.nonzero
            self.lines.extend(i for i, _ in pairs)
            self.vals.extend(a for _, a in pairs)
            self.starts.append(len(self.lines))
            self.types.append(self.type_ids.setdefault(col.type.id, len(self.type_ids)))
            self.costs.append(col.cost)
        if n > n0:
            self.dominated = np.concatenate([self.dominated, np.zeros(n - n0, dtype=bool)])
            self.checked = np.concatenate([self.checked, np.zeros(n - n0, dtype=np.int64)])
        return n

    def reduce(self, keep: set[int], duals: list[float] | None, deadline: float) -> Reduction:
        """`duals`: per line, for the cut; None ranks by `volume_duals`. The dominance pass stops at `deadline`."""
        t0 = time.monotonic()
        n = self._sync()
        # Copies, so the arrays can still grow once this call is over.
        starts = np.frombuffer(self.starts, dtype=np.int64).copy()
        lines = np.frombuffer(self.lines, dtype=np.int32).copy()
        vals = np.frombuffer(self.vals, dtype=np.int32).copy()
        owner = np.repeat(np.arange(n), np.diff(starts))  # column of each entry
        complete = self._dominance(n, lines, vals, owner, deadline)
        alive = ~self.dominated[:n]
        forced = np.zeros(n, dtype=bool)
        forced[list(keep)] = True
        alive |= forced
        dominated = int(n - alive.sum())
        cut, kept, ranked_by = 0, None, None
        free = np.flatnonzero(alive & ~forced)
        limit = self.limit
        if alive.sum() > limit and len(free) > 0:
            ranked_by = "lp" if duals is not None else "volume"
            pi = np.asarray(duals if duals is not None else volume_duals(self.pool), dtype=float)
            rc = np.frombuffer(self.costs, dtype=float) - np.bincount(owner, weights=vals * pi[lines], minlength=n)
            order = free[np.lexsort((free, rc[free]))]
            kept = min(limit, len(order))
            alive[order[kept:]] = False
            cut = len(order) - kept
        index = np.flatnonzero(alive).tolist()
        return Reduction(index, n, dominated, cut, kept, len(keep), ranked_by, complete, time.monotonic() - t0)

    def _dominance(self, n: int, lines: np.ndarray, vals: np.ndarray, owner: np.ndarray, deadline: float) -> bool:
        """Marks dominated columns, type by type. Columns to check are grouped by their rarest line; a group is
        compared with that line's posting list in blocks: total items and check age first, then line-set inclusion on
        bitsets, then counts on the few pairs left."""
        types = np.frombuffer(self.types, dtype=np.int32)[:n].copy()
        n_lines = len(self.pool.line_index)
        words = (n_lines + 63) // 64
        local = np.full(n, -1, dtype=np.int64)
        complete = True
        for t in range(len(self.type_ids)):
            members = np.flatnonzero(types == t)  # pool indices, ascending
            todo = members[~self.dominated[members] & (self.checked[members] < n)]
            if len(todo) == 0:
                continue
            if len(members) * n_lines > MAX_CELLS:
                complete = False
                continue
            # Dense counts and line bitsets of this type's columns, row r = pool column members[r].
            local[members] = np.arange(len(members))
            mine = types[owner] == t
            rows, t_lines, t_vals = local[owner[mine]], lines[mine], vals[mine]
            counts = np.zeros((len(members), n_lines), dtype=np.uint8 if t_vals.max() < 256 else np.int32)
            counts[rows, t_lines] = t_vals
            held = np.zeros((len(members), words), dtype=np.uint64)
            np.bitwise_or.at(held, (rows, t_lines // 64), np.left_shift(np.uint64(1), (t_lines % 64).astype(np.uint64)))
            totals = np.bincount(rows, weights=t_vals, minlength=len(members))
            checked = self.checked[members]
            by_line = np.argsort(t_lines, kind="stable")
            post_rows = rows[by_line]  # rows holding line l: post_rows[post_start[l]:post_start[l + 1]], ascending
            post_start = np.concatenate([[0], np.cumsum(np.bincount(t_lines, minlength=n_lines))])
            post_len = np.diff(post_start)
            # Each row to check and its rarest line; grouped by that line, least checked first.
            wanted = np.zeros(len(members), dtype=bool)
            wanted[local[todo]] = True
            e = np.flatnonzero(wanted[rows])
            e = e[np.lexsort((post_len[t_lines[e]], rows[e]))]
            first = np.concatenate([[True], rows[e][1:] != rows[e][:-1]])
            q_rows, rare = rows[e][first], t_lines[e][first]
            order = np.lexsort((checked[q_rows], rare))
            q_rows, rare = q_rows[order], rare[order]
            bounds = np.flatnonzero(np.concatenate([[True], rare[1:] != rare[:-1], [True]]))
            for g0, g1 in zip(bounds[:-1], bounds[1:]):
                line = rare[g0]
                cand_all = post_rows[post_start[line]:post_start[line + 1]]
                cand_pool = members[cand_all]  # ascending
                step = max(1, BLOCK // max(1, len(cand_all) * words * 2))
                for b0 in range(g0, g1, step):
                    if time.monotonic() >= deadline:
                        return False
                    q = q_rows[b0:min(b0 + step, g1)]
                    cand = cand_all[np.searchsorted(cand_pool, checked[q].min()):]  # q was checked below that
                    if len(cand):
                        qi, ci = np.nonzero((totals[cand][None, :] > totals[q][:, None])
                                            & (members[cand][None, :] >= checked[q][:, None]))
                        pq, pc = q[qi], cand[ci]
                        inside = ((held[pq] & ~held[pc]) == 0).all(axis=1)
                        pq, pc = pq[inside], pc[inside]
                        pairs = BLOCK // n_lines + 1
                        for p0 in range(0, len(pq), pairs):
                            ok = (counts[pc[p0:p0 + pairs]] >= counts[pq[p0:p0 + pairs]]).all(axis=1)
                            self.dominated[members[pq[p0:p0 + pairs][ok]]] = True
                    self.checked[members[q]] = n
        return complete


def volume_duals(pool: Pool) -> list[float]:
    """Stand-in duals when no LP was solved: each item is worth its volume at the cheapest cost per volume."""
    rate = min(t.cost / t.volume for t in pool.instance.container_types)
    return [rate * line.volume for line in pool.instance.items]
