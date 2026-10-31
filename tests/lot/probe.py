"""The probe lot (data/probe, simulated) as the reading should leave it before the user answers:
the fields and points of docs/product/ux.md §4. Used by the lot tests as a realistic document."""
from __future__ import annotations

from src.lot.schema import Dims, Excluded, Line, Lot, LotField, Option, Point, Source, Stacking

PL, SPEC, LABEL = "packing_list.xlsx", "product_spec.pdf", "handling_label_sku_c.png"


def src(file: str, where: str, raw: str | None) -> Source:
    return Source(file=file, where=where, raw=raw)


def ex(value, *sources: Source) -> LotField:
    return LotField(value=value, status="extracted", sources=list(sources))


def rv(value, *sources: Source) -> LotField:
    return LotField(value=value, status="needs_review", sources=list(sources))


def missing() -> LotField:
    return LotField(value=None, status="needs_review")


def probe_lot() -> Lot:
    lines = [
        Line(id="SKU-A", sku="SKU-A", description="Quạt đứng FS-40",
             qty=ex(200, src(PL, "Sheet1 · dòng 5", "200 thùng")),
             dims=rv(Dims(L=0.6, W=0.4, H=0.5), src(PL, "Sheet1 · dòng 5", "60x40x50 cm"), src(SPEC, "trang 1", "Height 450 mm")),
             mass=rv(12.5, src(PL, "Sheet1 · dòng 5", "N.W. 12 kg"), src(SPEC, "trang 1", "G.W. 12.5 kg")),
             posture=missing(), stacking=missing(), fragile=missing()),
        Line(id="SKU-A-2", sku="SKU-A", description="Quạt đứng FS-40 (bổ sung)",
             qty=ex(40, src(PL, "Sheet1 · dòng 9", "40 thùng")),
             dims=rv(Dims(L=0.6, W=0.4, H=0.45), src(PL, "Sheet1 · dòng 9", "60x40x45 cm")),
             mass=rv(12.5, src(PL, "Sheet1 · dòng 9", "N.W. 12 kg"), src(SPEC, "trang 1", "G.W. 12.5 kg")),
             posture=missing(), stacking=missing(), fragile=missing()),
        Line(id="SKU-B", sku="SKU-B", description="Nồi cơm điện RC-18",
             qty=ex(80, src(PL, "Sheet1 · dòng 6", "80 thùng")),
             dims=ex(Dims(L=0.8, W=0.6, H=0.5), src(PL, "Sheet1 · dòng 6", "800 x 600 x 500 mm")),
             mass=rv(26.0, src(PL, "Sheet1 · dòng 6", "25"), src(SPEC, "trang 1", "G.W. 26 kg")),
             posture=ex("upright", src(PL, "Sheet1 · dòng 6", "this side up")), stacking=missing(), fragile=missing()),
        Line(id="SKU-C", sku="SKU-C", description="Bộ ly thủy tinh GL-06",
             qty=ex(50, src(PL, "Sheet1 · dòng 7", "50 thùng")),
             dims=ex(Dims(L=0.5, W=0.5, H=0.6), src(PL, "Sheet1 · dòng 7", "50*50*60"), src(SPEC, "trang 1", "500 x 500 x 600 mm")),
             mass=rv(18.0, src(PL, "Sheet1 · dòng 7", None), src(SPEC, "trang 1", "G.W. 18 kg"), src(LABEL, "nhãn thùng", "G.W. 18 KG")),
             posture=rv("upright", src(LABEL, "nhãn thùng", "THIS SIDE UP")),
             stacking=rv(Stacking(kind="limited", tiers=2), src(LABEL, "nhãn thùng", "STACK LIMIT 2")),
             fragile=rv(True, src(LABEL, "nhãn thùng", "FRAGILE"))),
        Line(id="SKU-D", sku="SKU-D", description="Máy xay sinh tố BL-02", unit="pallet",
             qty=rv(10, src(PL, "Sheet1 · dòng 8", "10 pallet x 24 thùng")),
             dims=rv(Dims(L=1.2, W=1.0, H=1.5), src(PL, "Sheet1 · dòng 8", "120x100x150 cm")),
             mass=ex(160.0, src(PL, "Sheet1 · dòng 8", "160 kg"), src(SPEC, "trang 2", "Pallet G.W. 160 kg")),
             posture=ex("upright", src(SPEC, "trang 2", "Pallet, upright")),
             stacking=ex(Stacking(kind="none"), src(SPEC, "trang 2", "Do not stack")), fragile=missing()),
    ]
    points = [
        Point(id=1, title="SKU-A: chiều cao", question="Hai dòng cùng mã, chiều cao khác nhau; ghi thế nào?",
              fields=["SKU-A.dims", "SKU-A-2.dims"],
              options=[Option(label="Giữ 2 dòng riêng"),
                       Option(label="0,45 m cho 240 thùng", sets={"SKU-A.dims": {"L": 0.6, "W": 0.4, "H": 0.45}},
                              sources=[src(SPEC, "trang 1", "Height 450 mm")])]),
        Point(id=2, title="SKU-A: khối lượng tịnh hay cả bì", question="Dùng G.W. của spec?",
              fields=["SKU-A.mass", "SKU-A-2.mass"]),
        Point(id=3, title="SKU-B: khối lượng không có đơn vị", question="25 là kg tịnh?", fields=["SKU-B.mass"]),
        Point(id=4, title="SKU-C: thiếu khối lượng", question="Lấy 18 kg của spec và nhãn?", fields=["SKU-C.mass"]),
        Point(id=5, title="SKU-C: ràng buộc từ nhãn", question="Chỉ đứng, dễ vỡ, chồng tối đa 2?",
              fields=["SKU-C.posture", "SKU-C.stacking", "SKU-C.fragile"]),
        Point(id=6, title="SKU-D: kiện là pallet", question="10 pallet, kích thước theo pallet?",
              fields=["SKU-D.qty", "SKU-D.dims"]),
        Point(id=7, title="Tư thế, chồng chưa có trong tài liệu", question="Dùng mặc định?",
              fields=[f"{i}.{n}" for i in ("SKU-A", "SKU-A-2") for n in ("posture", "stacking", "fragile")]
              + ["SKU-B.stacking", "SKU-B.fragile", "SKU-D.fragile"]),
    ]
    excluded = [Excluded(sku="SKU-E", description="Ấm siêu tốc KT-15", reason="Chỉ spec nhắc tới, ghi Not in this shipment",
                         sources=[src(SPEC, "trang 2", "Not in this shipment")])]
    return Lot(name="Lô xuất T11 — điện gia dụng", lines=lines, points=points, excluded=excluded)
