"""Generate the agent's eval set (docs/product/eval.md): the probe set and seeded variants of
`scripts/gen_demo.py`, each with its answer key. Everything is simulated.

    python -m scripts.gen_eval                 # data/eval/: set-00 (probe), set-01..20, clean-21, clean-22, manifest.json
    python -m scripts.gen_eval --doc           # docs/product/eval-sets.md: what each set holds (no data written)

The list of sets is fixed here (`SETS`), so the same command always writes the same files. Each variant turns on 2-7
traps drawn by its seed; the two clean sets have none, to count the questions a reader asks without cause.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date
from pathlib import Path

from scripts.gen_demo import ROOT, TRAPS, DocSet, answers, generate, num, probe, variant

OUT = ROOT / "data" / "eval"
DOC = ROOT / "docs" / "product" / "eval-sets.md"
TRAP_VI = {
    "dup_height": "trùng mã khác chiều cao", "net_mass": "khối lượng tịnh", "mm_unitless": "mm, khối lượng không đơn vị",
    "missing_mass": "thiếu khối lượng", "label": "nhãn ảnh", "pallet": "pallet", "not_shipped": "mã không giao",
}
VARIANTS = range(1, 21)
CLEAN = (21, 22)
MIN_PER_TRAP = 5


def traps_for(seed: int) -> tuple[str, ...]:
    rng = random.Random(1000 + seed)
    chosen = set(rng.sample(TRAPS, rng.randint(2, len(TRAPS))))
    return tuple(t for t in TRAPS if t in chosen)


SETS: tuple[tuple[str, int | None, tuple[str, ...]], ...] = (
    ("set-00", None, TRAPS),
    *((f"set-{s:02d}", s, traps_for(s)) for s in VARIANTS),
    *((f"clean-{s}", s, ()) for s in CLEAN),
)


def check_coverage() -> dict[str, int]:
    """How many sets carry each trap; ValueError below `MIN_PER_TRAP`."""
    counts = {t: sum(t in traps for _, _, traps in SETS) for t in TRAPS}
    if low := [t for t, n in counts.items() if n < MIN_PER_TRAP]:
        raise ValueError(f"traps in fewer than {MIN_PER_TRAP} sets: {', '.join(low)}")
    return counts


def doc_set(name: str, seed: int | None) -> DocSet:
    return probe() if seed is None else variant(seed, dict((n, t) for n, _, t in SETS)[name])


def describe() -> str:
    """The body of `DOC` (everything after its front matter): one overview row and one table of lines per set, from
    the same values `build` writes, so the doc and the files cannot drift."""
    out = ["", "# Từng bộ eval agent", "",
           "Sinh bằng `python -m scripts.gen_eval --doc` từ cùng danh sách bộ và cùng seed với `data/eval/`; **không "
           "sửa tay** (test so file này với script). Mọi giá trị là **giả lập**. Bộ eval là gì, chỉ số, kết quả: "
           "[eval.md](eval.md). Hành vi đúng với từng bẫy: "
           "[`data/probe/README.md`](../../data/probe/README.md).", "",
           "Giá trị trong bảng là **giá trị thật** (đáp án), không phải giá trị tài liệu ghi: bẫy làm tài liệu ghi "
           "khác (mm, khối lượng tịnh, thiếu khối lượng, chiều cao sai ở dòng trùng mã). Cột \"Tài liệu nêu\" là các "
           "trường có tài liệu nào đó nêu; trường còn lại phải hỏi.", "",
           "## Tổng quan", "", "| Bộ | Seed | Dòng | Bẫy (mã) | Ảnh nhãn |", "|---|---|---|---|---|"]
    body = []
    for name, seed, traps in SETS:
        ds = doc_set(name, seed)
        key = answers(ds)
        trap_text = "; ".join(f"{TRAP_VI[t['trap']]} ({', '.join(t['on'])})" for t in key["traps"]) or "không"
        photo = f"`handling_label_{ds.on['label'].lower().replace('-', '_')}.png`" if "label" in ds.on else "—"
        out.append(f"| [`{name}`](#{name}) | {'probe' if seed is None else seed} | {len(key['lines'])} | {trap_text} | {photo} |")
        body += ["", f"## {name}", "", f"{ds.name}, hóa đơn {ds.invoice}.", "",
                 "| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |",
                 "|---|---|---|---|---|---|---|---|---|---|"]
        for row, line in zip(ds.rows, key["lines"]):
            d, s = line["dims"], line["stacking"]
            stack = {"free": "tự do", "none": "không"}.get(s["kind"]) or f"{s['tiers']} tầng"
            body.append(f"| `{line['id']}` | {row.product.vi} | {'pallet' if line['unit'] == 'pallet' else 'thùng'} "
                        f"| {line['qty']} | {num(d['L'])} × {num(d['W'])} × {num(d['H'])} | {num(line['mass'])} "
                        f"| {'đứng' if line['posture'] == 'upright' else 'tùy'} | {stack} "
                        f"| {'có' if line['fragile'] else 'không'} | {', '.join(line['stated'])} |")
        if ds.excluded:
            body += ["", "Không giao (chỉ spec nhắc): " + ", ".join(f"`{p.sku}` {p.vi}" for p in ds.excluded) + "."]
    return "\n".join(out + body) + "\n"


def write_doc(path: Path = DOC) -> None:
    """Rewrite the body of `path`, keeping its front matter (bump `updated` by hand when the body changes)."""
    head = (path.read_text(encoding="utf-8").split("\n---\n", 1)[0] + "\n---\n" if path.exists() else
            f"---\nstatus: living\nupdated: {date.today().isoformat()}\nowner: Hiếu\n---\n")
    path.write_text(head + describe(), encoding="utf-8", newline="\n")


def build(out: Path = OUT) -> dict:
    counts = check_coverage()
    manifest = {"simulated": True, "sets": [], "trap_sets": counts}
    for name, seed, traps in SETS:
        ds = probe() if seed is None else variant(seed, traps)
        files = generate(ds, out / name)
        manifest["sets"].append({"name": name, "seed": seed, "traps": list(traps), "files": files})
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--doc", action="store_true", help=f"write {DOC.relative_to(ROOT).as_posix()} only")
    args = ap.parse_args()
    if args.doc:
        write_doc()
        print(f"wrote {DOC}")
        return
    manifest = build(args.out)
    print(f"{len(manifest['sets'])} sets in {args.out}; sets per trap: {manifest['trap_sets']}")


if __name__ == "__main__":
    main()
