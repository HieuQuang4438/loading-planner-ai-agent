"""Generate a simulated document set for a lot: packing list (xlsx, csv), product spec (pdf), one carton label photo
(png), freight rates (csv), and the answer key (`answers.json`): the lot a careful reader ends with, and the traps
it must catch. Everything is simulated: companies, products, figures and costs are made up.

    python -m scripts.gen_demo                       # data/probe: the probe and demo set
    python -m scripts.gen_demo --seed 7 --out data/eval/s7 --traps dup_height,pallet

Without --seed the set is the probe (eight traps, fixed values). With a seed, the
products, quantities and which product carries which trap are drawn from a fixed catalogue; --traps picks the traps.
The value a document shows is derived from the product's true values and the traps, so the answer key never comes
from a hand-labelled file. Needs the dev requirements (fpdf2, Pillow).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAPS = ("dup_height", "net_mass", "mm_unitless", "missing_mass", "label", "pallet", "not_shipped")
TRAP_TEXT = {
    "dup_height": "Two packing-list rows of one code, heights differ; the spec has the true height. Ask, do not split or pick silently.",
    "net_mass": "The packing list gives net mass, the spec gross; pack with gross.",
    "mm_unitless": "Size in mm and a mass without unit; read the size, take the unit of the mass from the spec or ask.",
    "missing_mass": "The packing list has no mass; take it from the spec or label with its source, never invent one.",
    "label": "Handling marks only on the label photo become posture, stacking and fragile.",
    "pallet": "Quantity and size are per pallet: pack pallets, not cartons with pallet size.",
    "not_shipped": "A code only the spec mentions, marked not in this shipment: keep it out of the lot.",
}


@dataclass(frozen=True)
class Product:
    """True values of one product's shipping unit: a carton, or a pallet when `per_pallet` is set (then L, W, H and
    gross are the loaded pallet's and `carton` is the carton the spec lists)."""
    sku: str
    vi: str
    en: str
    L: float  # m
    W: float
    H: float
    gross: float  # kg per unit
    net: float
    upright: bool = False
    stack: int | None = None  # tiers incl. itself; 1 = nothing on top; None = no limit given
    fragile: bool = False
    pcs: int = 1  # pieces per carton, shown on a label
    per_pallet: int = 0
    carton: tuple[float, float, float, float] | None = None  # L, W, H (m), gross (kg) of a carton on the pallet


@dataclass
class Row:
    """One packing-list row and the lot line it becomes."""
    product: Product
    qty: int
    line_id: str
    height_shown: float | None = None  # a wrong height (dup_height); None = the true one
    supplement: bool = False


@dataclass
class DocSet:
    name: str
    invoice: str
    rows: list[Row]
    traps: tuple[str, ...]
    on: dict[str, str]  # trap -> sku it was put on
    excluded: list[Product] = field(default_factory=list)
    seed: int | None = None


# --- the probe ---------------------------------------------------------------------------------------------------

FAN = Product("SKU-A", "Quạt đứng FS-40", "Stand fan FS-40", 0.6, 0.4, 0.45, 12.5, 12.0, stack=5)
COOKER = Product("SKU-B", "Nồi cơm điện RC-18", "Rice cooker RC-18", 0.8, 0.6, 0.5, 26.0, 25.0, upright=True)
GLASS = Product("SKU-C", "Bộ ly thủy tinh GL-06", "Glass set GL-06 (6 pcs)", 0.5, 0.5, 0.6, 18.0, 16.5, upright=True,
                stack=2, fragile=True, pcs=6)
BLENDER = Product("SKU-D", "Máy xay sinh tố BL-02", "Blender BL-02", 1.2, 1.0, 1.5, 160.0, 148.8, upright=True, stack=1,
                  per_pallet=24, carton=(0.4, 0.3, 0.35, 6.2))
KETTLE = Product("SKU-E", "Ấm siêu tốc KT-17", "Electric kettle KT-17", 0.35, 0.25, 0.3, 3.1, 2.7)


def probe() -> DocSet:
    rows = [Row(FAN, 200, "SKU-A", height_shown=0.5), Row(COOKER, 80, "SKU-B"), Row(GLASS, 50, "SKU-C"),
            Row(BLENDER, 10, "SKU-D"), Row(FAN, 40, "SKU-A-2", supplement=True)]
    on = {"dup_height": "SKU-A", "net_mass": "SKU-A,SKU-B", "mm_unitless": "SKU-B", "missing_mass": "SKU-C",
          "label": "SKU-C", "pallet": "SKU-D", "not_shipped": "SKU-E"}
    return DocSet("Lô xuất T11 — điện gia dụng", "INV-2026-118", rows, TRAPS, on, [KETTLE])


# --- seeded variants ---------------------------------------------------------------------------------------------

CATALOGUE = (
    ("Quạt đứng", "Stand fan", (0.6, 0.4, 0.45), 12.5, dict(stack=5)),
    ("Nồi cơm điện", "Rice cooker", (0.8, 0.6, 0.5), 26.0, dict(upright=True)),
    ("Bộ ly thủy tinh", "Glass set", (0.5, 0.5, 0.6), 18.0, dict(upright=True, stack=2, fragile=True, pcs=6)),
    ("Máy xay sinh tố", "Blender", (0.4, 0.3, 0.35), 6.2, {}),
    ("Ấm siêu tốc", "Electric kettle", (0.35, 0.25, 0.3), 3.1, {}),
    ("Lò vi sóng", "Microwave oven", (0.55, 0.45, 0.35), 15.0, dict(upright=True, stack=4)),
    ("Bàn ủi hơi nước", "Steam iron", (0.35, 0.2, 0.2), 2.2, {}),
    ("Máy lọc không khí", "Air purifier", (0.45, 0.4, 0.7), 11.0, dict(upright=True, stack=3)),
    ("Bộ nồi inox", "Stainless pot set", (0.6, 0.45, 0.4), 14.0, dict(stack=6)),
    ("Đèn bàn LED", "LED desk lamp", (0.5, 0.25, 0.2), 2.8, dict(fragile=True)),
    ("Máy hút bụi", "Vacuum cleaner", (0.5, 0.35, 0.4), 9.5, {}),
    ("Bình giữ nhiệt", "Vacuum flask", (0.4, 0.3, 0.3), 7.0, dict(stack=8)),
)


def variant(seed: int, traps: tuple[str, ...]) -> DocSet:
    rng = random.Random(seed)
    picks = rng.sample(range(len(CATALOGUE)), 6)
    products = []
    for n, k in enumerate(picks):
        vi, en, (L, W, H), gross, extra = CATALOGUE[k]
        model = f"{en[:2].upper()}-{rng.randint(10, 99)}"
        products.append(Product(f"SKU-{chr(65 + n)}", f"{vi} {model}", f"{en} {model}", L, W, H, gross,
                                round(gross * rng.uniform(0.88, 0.96), 1), **extra))
    shipped, spare = products[:5], products[5]
    on: dict[str, str] = {}
    if "pallet" in traps:  # a small carton goes on pallets
        i = min(range(5), key=lambda j: shipped[j].L * shipped[j].W * shipped[j].H)
        c = shipped[i]
        n = rng.choice((20, 24, 30, 36))
        shipped[i] = replace(c, L=1.2, W=1.0, H=round(0.15 + 0.35 * (n // 6), 2), gross=round(25 + n * c.gross),
                             net=round(n * c.net, 1), upright=True, stack=1, fragile=False, per_pallet=n,
                             carton=(c.L, c.W, c.H, c.gross))
        on["pallet"] = c.sku
    cartons = [p for p in shipped if not p.per_pallet]
    rng.shuffle(cartons)
    for trap in ("dup_height", "mm_unitless", "missing_mass", "label"):
        if trap in traps:
            if trap == "label":
                marked = [p for p in cartons if p.upright or p.fragile or p.stack] or cartons
                on[trap] = marked[0].sku
            else:
                on[trap] = cartons.pop().sku
    if "net_mass" in traps:
        on["net_mass"] = ",".join(p.sku for p in shipped if not p.per_pallet and p.sku != on.get("missing_mass"))
    rows = []
    for p in shipped:
        qty = rng.randint(4, 12) if p.per_pallet else rng.randint(30, 300)
        if p.sku == on.get("dup_height"):
            extra = max(10, qty // 6)
            rows.append(Row(p, qty, p.sku, height_shown=round(p.H + 0.05, 2)))
            rows.append(Row(p, extra, f"{p.sku}-2", supplement=True))
        else:
            rows.append(Row(p, qty, p.sku))
    rows.sort(key=lambda r: r.supplement)  # a supplement row comes last, as an added order does
    excluded = []
    if "not_shipped" in traps:
        excluded = [spare]
        on["not_shipped"] = spare.sku
    return DocSet(f"Lô eval {seed}", f"INV-2026-{rng.randint(200, 999)}", rows, traps, on, excluded, seed)


# --- what each document shows ------------------------------------------------------------------------------------

def num(x: float) -> str:
    return f"{x:g}"


def cm(x: float) -> str:
    return num(round(x * 100, 1))


def mm(x: float) -> str:
    return num(round(x * 1000))


def has(ds: DocSet, trap: str, sku: str) -> bool:
    return trap in ds.traps and sku in ds.on.get(trap, "").split(",")


def label_sku(ds: DocSet) -> str | None:
    return ds.on.get("label") if "label" in ds.traps else None


def packing_rows(ds: DocSet) -> list[list[str]]:
    out = []
    for r in ds.rows:
        p = r.product
        H = r.height_shown or p.H
        desc = p.vi + (" (bổ sung)" if r.supplement else "")
        note = "Đơn bổ sung" if r.supplement else ""
        if p.per_pallet and has(ds, "pallet", p.sku):
            qty = f"{r.qty} pallet x {p.per_pallet} thùng"
            note = "Kích thước/khối lượng theo pallet"
        else:
            qty = f"{r.qty} thùng"
        if has(ds, "mm_unitless", p.sku):
            dims, mass = f"{mm(p.L)} x {mm(p.W)} x {mm(H)} mm", num(p.net if "net_mass" in ds.traps else p.gross)
        elif has(ds, "missing_mass", p.sku):
            dims, mass = f"{cm(p.L)}*{cm(p.W)}*{cm(H)}", ""
        else:
            dims = f"{cm(p.L)}x{cm(p.W)}x{cm(H)} cm"
            mass = f"{num(p.net if 'net_mass' in ds.traps and not p.per_pallet else p.gross)} kg"
        if p.upright and has(ds, "mm_unitless", p.sku):
            desc += " (this side up)"
        if p.fragile and p.sku == label_sku(ds):
            desc += " - FRAGILE"
            note = note or "Hàng dễ vỡ"
        out.append([p.sku, desc, qty, dims, mass, note])
    return out


def mass_header(ds: DocSet) -> str:
    return "N.W/thùng" if "net_mass" in ds.traps else "G.W/thùng"


def spec_rows(ds: DocSet) -> list[list[str]]:
    seen, out = set(), []
    for p in [r.product for r in ds.rows] + ds.excluded:
        if p.sku in seen:
            continue
        seen.add(p.sku)
        if p.per_pallet:
            L, W, H, gross = p.carton
            out.append([p.sku, p.en, f"{cm(L)}x{cm(W)}x{cm(H)} cm", f"{num(gross)} kg", f"{p.per_pallet} ctns/pallet"])
            continue
        size = (f"{mm(p.L)}x{mm(p.W)}x{mm(p.H)} mm" if has(ds, "dup_height", p.sku)
                else f"{cm(p.L)}x{cm(p.W)}x{cm(p.H)} cm")
        notes = []
        if p in ds.excluded:
            notes.append("Not in this shipment")
        elif p.sku != label_sku(ds):  # the label is the only place its marks are given
            if p.upright:
                notes.append("This side up")
            if p.fragile:
                notes.append("Fragile")
            if p.stack:
                notes.append(f"max {p.stack} layers" if notes else f"Max {p.stack} layers")
        elif p.fragile:
            notes.append("Fragile")
            if p.stack:
                notes.append(f"max {p.stack} layers")
        out.append([p.sku, p.en, size, f"{num(p.gross)} kg", ", ".join(notes)])
    return out


def pallet_notes(ds: DocSet) -> list[str]:
    return [f"Wooden pallet {mm(p.L)} x {mm(p.W)} mm, {p.per_pallet} cartons per pallet, loaded height {num(p.H)} m, "
            f"gross weight per pallet {num(p.gross)} kg. Pallets are not stackable."
            for p in dict.fromkeys(r.product for r in ds.rows) if p.per_pallet]


# --- writers -----------------------------------------------------------------------------------------------------

def write_packing_list(ds: DocSet, out: Path) -> None:
    from openpyxl import Workbook

    header = ["Mã hàng", "Mô tả", "SL", "Kích thước DxRxC", mass_header(ds), "Ghi chú"]
    rows = packing_rows(ds)
    cartons = sum(r.qty for r in ds.rows if not r.product.per_pallet)
    pallets = sum(r.qty for r in ds.rows if r.product.per_pallet)
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing List"
    ws.append(["CÔNG TY TNHH GIA DỤNG MINH AN (giả lập)"])
    ws.append([f"PACKING LIST — Invoice {ds.invoice} — Ngày 20/10/2026"])
    ws.append(["Cảng xếp: Hải Phòng — Cảng dỡ: Los Angeles"])
    ws.append([])
    ws.append(header)
    for row in rows:
        ws.append([v or None for v in row])
    ws.append([])
    ws.append(["TỔNG", None, f"{cartons} thùng" + (f" + {pallets} pallet" if pallets else "")])
    for col, width in zip("ABCDEF", (10, 36, 22, 20, 12, 34)):
        ws.column_dimensions[col].width = width
    wb.save(out / "packing_list.xlsx")
    with open(out / "packing_list.csv", "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows([header, *rows])


def write_spec(ds: DocSet, out: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 10, "PRODUCT SPECIFICATION - Export cartons (synthetic)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, "Minh An Household Appliances (synthetic). Rev. 3, 2026-09-30. All dimensions are outer carton "
                         "dimensions. Weights are gross weight per carton.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    widths = (22, 52, 40, 22, 54)
    pdf.set_font("Helvetica", "B", 10)
    for w, h in zip(widths, ("Item code", "Description", "L x W x H", "G.W.", "Handling")):
        pdf.cell(w, 8, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    for row in spec_rows(ds):
        for w, v in zip(widths, row):
            pdf.cell(w, 8, v, border=1)
        pdf.ln()
    notes = pallet_notes(ds)
    if notes:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 12)
        skus = ", ".join(r.product.sku for r in ds.rows if r.product.per_pallet)
        pdf.cell(0, 8, f"Pallet data ({skus})", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for note in notes:
            pdf.multi_cell(0, 5, note, new_x="LMARGIN", new_y="NEXT")
    pdf.set_creation_date(datetime(2026, 10, 20, tzinfo=timezone.utc))  # the same input gives the same bytes
    pdf.output(str(out / "product_spec.pdf"))


def write_label(ds: DocSet, out: Path) -> str | None:
    from PIL import Image, ImageDraw, ImageFont

    sku = label_sku(ds)
    if sku is None:
        return None
    p = next(r.product for r in ds.rows if r.product.sku == sku)
    qty = sum(r.qty for r in ds.rows if r.product.sku == sku)
    img = Image.new("RGB", (900, 600), (242, 226, 198))
    d = ImageDraw.Draw(img)
    font = lambda size: ImageFont.load_default(size)  # noqa: E731 - Pillow's scalable default font, no system font
    d.rectangle((22, 22, 878, 578), outline="black", width=6)
    d.text((50, 45), f"{p.sku}  {p.en.split(' (')[0].upper()}", fill="black", font=font(42), stroke_width=1, stroke_fill="black")
    d.text((50, 108), f"{p.pcs} PCS / CTN   G.W. {num(p.gross)} KG   {cm(p.L)} x {cm(p.W)} x {cm(p.H)} CM",
           fill="black", font=font(22))
    if p.upright:
        for x in (120, 190):
            d.polygon([(x - 30, 225), (x, 190), (x + 30, 225)], fill="black")
            d.rectangle((x - 8, 224, x + 8, 340), fill="black")
        d.text((80, 362), "THIS SIDE UP", fill="black", font=font(28), stroke_width=1, stroke_fill="black")
    if p.fragile:
        red = (230, 0, 0)
        d.polygon([(382, 202), (478, 202), (460, 276), (400, 276)], outline=red, width=6)
        d.line((418, 220, 444, 244, 426, 264), fill=red, width=3)
        d.line((430, 276, 430, 330), fill=red, width=6)
        d.line((400, 330, 460, 330), fill=red, width=6)
        d.text((360, 362), "FRAGILE", fill=red, font=font(28), stroke_width=1, stroke_fill=red)
    if p.stack:
        d.rectangle((641, 242, 759, 288), outline="black", width=5)
        d.rectangle((641, 302, 759, 348), outline="black", width=5)
        d.text((780, 205), str(p.stack), fill="black", font=font(36), stroke_width=1, stroke_fill="black")
        d.text((600, 362), "STACKING LIMIT", fill="black", font=font(24))
    d.text((50, 472), f"MADE IN VIETNAM - {ds.invoice} - CTN NO. 1-{qty}", fill="black", font=font(22))
    name = f"handling_label_{sku.lower().replace('-', '_')}.png"
    img.save(out / name, optimize=True)
    return name


def write_rates(out: Path) -> None:
    from src.plan.mode_a import DEFAULT_CONTAINERS

    with open(out / "freight_rates.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["container", "inner_l_mm", "inner_w_mm", "inner_h_mm", "max_payload_kg", "freight_usd"])
        for c in DEFAULT_CONTAINERS:
            w.writerow([c.id, mm(c.L), mm(c.W), mm(c.H), num(c.max_mass), num(c.cost)])


def answers(ds: DocSet) -> dict:
    """The lot after a careful reading and the user's answers, line by line, with the fields some document states;
    a field no document states has the true value here but must be asked, never filled by the reader."""
    lines = []
    for r in ds.rows:
        p = r.product
        stated = {"qty", "dims", "mass"}
        if p.upright:
            stated.add("posture")
        if p.stack:
            stated.add("stacking")
        if p.fragile:
            stated.add("fragile")
        if p.per_pallet:
            stated -= {"posture", "fragile"}
        stacking = ({"kind": "free"} if p.stack is None else {"kind": "none"} if p.stack == 1
                    else {"kind": "limited", "tiers": p.stack})
        lines.append({
            "id": r.line_id, "sku": p.sku, "unit": "pallet" if p.per_pallet else "carton", "qty": r.qty,
            "dims": {"L": p.L, "W": p.W, "H": p.H}, "mass": p.gross,
            "posture": "upright" if p.upright else "tippable", "stacking": stacking, "fragile": p.fragile,
            "stated": sorted(stated),
        })
    traps = [{"trap": t, "on": ds.on[t].split(","), "expect": TRAP_TEXT[t]} for t in ds.traps if t in ds.on]
    return {"simulated": True, "seed": ds.seed, "name": ds.name, "lines": lines,
            "excluded": [p.sku for p in ds.excluded], "traps": traps}


def generate(ds: DocSet, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    write_packing_list(ds, out)
    write_spec(ds, out)
    write_label(ds, out)
    write_rates(out)
    (out / "answers.json").write_text(json.dumps(answers(ds), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sorted(f.name for f in out.iterdir())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, help="draw a variant; omit for the probe set")
    ap.add_argument("--traps", default=",".join(TRAPS), help="comma-separated, from: " + ", ".join(TRAPS))
    ap.add_argument("--out", type=Path, help="output folder (default data/probe without --seed)")
    args = ap.parse_args()
    traps = tuple(t for t in TRAPS if t in args.traps.split(","))
    if unknown := set(args.traps.split(",")) - set(TRAPS) - {""}:
        ap.error(f"unknown trap: {', '.join(sorted(unknown))}")
    if args.seed is None:
        if args.traps != ",".join(TRAPS):
            ap.error("the probe set has all traps; pass --seed to choose")
        ds, out = probe(), args.out or ROOT / "data" / "probe"
    else:
        if args.out is None:
            ap.error("--out is required with --seed")
        ds, out = variant(args.seed, traps), args.out
    print("\n".join(generate(ds, out)))


if __name__ == "__main__":
    main()
