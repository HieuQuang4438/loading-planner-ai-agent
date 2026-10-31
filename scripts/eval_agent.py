"""Run the agent's reading on the eval set (docs/product/eval.md) and score the lot it leaves before the user
answers against each set's answer key. The pipeline is the product's: one model call per document, the fixed merge,
then the points (`src.lot.review.refresh`).

    python -m scripts.gen_eval                          # the sets, once
    python -m scripts.eval_agent [--sets set-00,set-01] [--out data/eval/results-<model>.json]

Scores, per set and summed (docs/product/eval.md §2):
- each stated field (a document gives it) is `right` (extracted, equals the key), `asked` (a point is open on it), or
  `wrong` (extracted, differs from the key);
- `invented`: a field no document states that has a value and is not asked, plus every `wrong` field;
- a trap is `caught` when every field it touches is asked or extracted right, and `dup_height` also needs one of them
  asked; a code not shipped is caught when it is not a line of the lot or a point is open on its line;
- `extra_points`: points that touch no trap's field and no unstated field.

Needs GOOGLE_API_KEY (or GOOGLE_API_KEY_1...) for the real model. Simulated data only.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.extract.documents import load
from src.extract.pipeline import extract
from src.llm.client import LLM
from src.lot.review import refresh
from src.lot.schema import Lot

EVAL = Path(__file__).resolve().parents[1] / "data" / "eval"
FIELDS = ("qty", "dims", "mass", "posture", "stacking", "fragile")
TOL = 1e-6
# Fields of a trap's lines it touches; a `MUST_ASK` trap needs a point open on one of them, the others may be read right.
TRAP_FIELDS = {
    "dup_height": ("qty", "dims"),
    "net_mass": ("mass",),
    "mm_unitless": ("dims", "mass"),
    "missing_mass": ("dims", "mass"),
    "label": ("posture", "stacking", "fragile"),
    "pallet": ("qty", "dims"),
}
MUST_ASK = {"dup_height"}


@dataclass
class SetScore:
    name: str
    right: int = 0
    asked: int = 0
    wrong: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    traps: list[dict[str, Any]] = field(default_factory=list)
    extra_points: list[str] = field(default_factory=list)
    missing_lines: list[str] = field(default_factory=list)
    extra_lines: list[str] = field(default_factory=list)
    failed_documents: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


def documents(folder: Path) -> list[Path]:
    """What a user uploads: the packing list, the spec, the label photo (not the CSV copy, the rates or the key)."""
    return [p for p in sorted(folder.iterdir())
            if p.name in ("packing_list.xlsx", "product_spec.pdf") or p.name.startswith("handling_label_")]


def same(name: str, value: Any, truth: Any) -> bool:
    if value is None:
        return False
    if name == "dims":
        return all(abs(getattr(value, k) - truth[k]) <= TOL for k in "LWH")
    if name == "mass":
        return abs(value - truth) <= TOL
    if name == "stacking":
        return value.kind == truth["kind"] and (value.tiers or None) == truth.get("tiers")
    return value == truth


def score(name: str, lot: Lot, key: dict[str, Any]) -> SetScore:
    out = SetScore(name)
    lines = {line.id: line for line in lot.lines}
    asked = {f for p in lot.open_points() for f in p.fields}
    truth = {t["id"]: t for t in key["lines"]}
    out.missing_lines = [i for i in truth if i not in lines]
    out.extra_lines = [i for i in lines if i not in truth]
    unstated: set[str] = set()
    for tid, t in truth.items():
        line = lines.get(tid)
        for f in FIELDS:
            fid = f"{tid}.{f}"
            if f not in t["stated"]:
                unstated.add(fid)
                if line is not None and getattr(line, f).value is not None and fid not in asked:
                    out.invented.append(fid)
                continue
            if line is None:
                continue
            if fid in asked:
                out.asked += 1
            elif same(f, getattr(line, f).value, t[f]):
                out.right += 1
            else:
                out.wrong.append(fid)
    out.invented += out.wrong
    trap_fields: set[str] = set()
    for trap in key["traps"]:
        for sku in trap["on"]:
            if trap["trap"] == "not_shipped":
                ids = [l.id for l in lot.lines if l.sku == sku]
                caught = not ids or any(f.startswith(f"{i}.") for i in ids for f in asked)
                out.traps.append({"trap": "not_shipped", "sku": sku, "caught": caught})
                continue
            ids = [tid for tid, t in truth.items() if t["sku"] == sku]
            fids = [f"{i}.{f}" for i in ids for f in TRAP_FIELDS[trap["trap"]]]
            trap_fields.update(fids)
            ok = []
            for fid in fids:
                tid, f = fid.split(".")
                line = lines.get(tid)
                ok.append(fid in asked or (line is not None and same(f, getattr(line, f).value, truth[tid][f])))
            caught = bool(ok) and all(ok) and (trap["trap"] not in MUST_ASK or any(f in asked for f in fids))
            out.traps.append({"trap": trap["trap"], "sku": sku, "caught": caught})
    for p in lot.open_points():
        if not any(f in trap_fields or f in unstated for f in p.fields):
            out.extra_points.append(p.title)
    return out


def run_set(llm: LLM, folder: Path) -> SetScore:
    key = json.loads((folder / "answers.json").read_text(encoding="utf-8"))
    start = time.monotonic()
    uploads = [load(p.name, p.read_bytes()) for p in documents(folder)]
    extraction = extract(llm, key["name"], uploads)
    result = score(folder.name, refresh(extraction.lot), key)
    result.failed_documents = extraction.failed
    result.seconds = round(time.monotonic() - start, 1)
    return result


def summary(scores: list[SetScore]) -> dict[str, Any]:
    stated = sum(s.right + s.asked + len(s.wrong) for s in scores)
    traps: dict[str, list[int]] = {}
    for s in scores:
        for t in s.traps:
            traps.setdefault(t["trap"], [0, 0])
            traps[t["trap"]][0] += t["caught"]
            traps[t["trap"]][1] += 1
    caught, total = sum(c for c, _ in traps.values()), sum(n for _, n in traps.values())
    return {
        "sets": len(scores),
        "sets_with_failed_documents": sum(bool(s.failed_documents) for s in scores),
        "stated_fields": stated,
        "right": sum(s.right for s in scores),
        "asked": sum(s.asked for s in scores),
        "wrong": sum(len(s.wrong) for s in scores),
        "invented": sum(len(s.invented) for s in scores),
        "traps_caught": caught,
        "traps": total,
        "by_trap": {t: {"caught": c, "of": n} for t, (c, n) in traps.items()},
        "extra_points": sum(len(s.extra_points) for s in scores),
        "missing_lines": sum(len(s.missing_lines) for s in scores),
        "extra_lines": sum(len(s.extra_lines) for s in scores),
    }


def main() -> None:
    from src.llm.client import Gemini, load_env

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sets", help="comma-separated set names (default: every set of the manifest)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    load_env()
    manifest = json.loads((EVAL / "manifest.json").read_text(encoding="utf-8"))
    names = args.sets.split(",") if args.sets else [s["name"] for s in manifest["sets"]]
    llm = Gemini()
    scores = []
    for n in names:
        s = run_set(llm, EVAL / n)
        scores.append(s)
        print(f"{n}: right {s.right}, asked {s.asked}, wrong {len(s.wrong)}, invented {len(s.invented)}, "
              f"traps {sum(t['caught'] for t in s.traps)}/{len(s.traps)}, extra points {len(s.extra_points)}, "
              f"failed {len(s.failed_documents)}, {s.seconds} s", flush=True)
    report = {"model": llm.model, "thinking": llm.thinking, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "simulated": True, "summary": summary(scores), "sets": [s.__dict__ for s in scores]}
    out = args.out or EVAL / f"results-{llm.model}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"written {out}")


if __name__ == "__main__":
    main()
