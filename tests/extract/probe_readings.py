"""What a correct reading of data/probe (simulated) looks like: the answers a mocked model gives in the tests.
Written by hand from the files; the live test (`test_live.py`) compares a real model with these."""
from __future__ import annotations

from src.extract.readings import DocumentReading, ItemReading

PL, SPEC, LABEL = "packing_list.xlsx", "product_spec.pdf", "handling_label_sku_c.png"


def r(sku: str, where: str, **kw) -> ItemReading:
    return ItemReading(sku=sku, where=where, **kw)


PACKING_LIST = DocumentReading(kind="packing_list", items=[
    r("SKU-A", "Packing List · dòng 6", description="Quạt đứng FS-40", qty_text="200 thùng", unit="carton",
      dims_text="60x40x50 cm", dims_of="carton", mass_text="12 kg", mass_kind="net", mass_of="carton"),
    r("SKU-B", "Packing List · dòng 7", description="Nồi cơm điện RC-18 (this side up)", qty_text="80 thùng", unit="carton",
      dims_text="800 x 600 x 500 mm", dims_of="carton", mass_text="25", mass_kind="net", mass_of="carton",
      upright_text="this side up"),
    r("SKU-C", "Packing List · dòng 8", description="Bộ ly thủy tinh GL-06 - FRAGILE", qty_text="50 thùng", unit="carton",
      dims_text="50*50*60", dims_of="carton", fragile_text="FRAGILE; Hàng dễ vỡ"),
    r("SKU-D", "Packing List · dòng 9", description="Máy xay sinh tố BL-02", qty_text="10 pallet x 24 thùng", unit="pallet",
      dims_text="120x100x150 cm", dims_of="pallet", mass_text="160 kg", mass_kind="net", mass_of="pallet"),
    r("SKU-A", "Packing List · dòng 10", description="Quạt đứng FS-40 (bổ sung)", qty_text="40 thùng", unit="carton",
      dims_text="60x40x45 cm", dims_of="carton", mass_text="12 kg", mass_kind="net", mass_of="carton"),
])

SPECIFICATION = DocumentReading(kind="spec", items=[
    r("SKU-A", "trang 1", description="Stand fan FS-40", dims_text="600x400x450 mm", dims_of="carton",
      mass_text="12.5 kg", mass_kind="gross", mass_of="carton", stack_text="Max 5 layers", stack_limit=5),
    r("SKU-B", "trang 1", description="Rice cooker RC-18", dims_text="80x60x50 cm", dims_of="carton",
      mass_text="26 kg", mass_kind="gross", mass_of="carton", upright_text="This side up"),
    r("SKU-C", "trang 1", description="Glass set GL-06 (6 pcs)", dims_text="50x50x60 cm", dims_of="carton",
      mass_text="18 kg", mass_kind="gross", mass_of="carton", stack_text="max 2 layers", stack_limit=2,
      fragile_text="Fragile"),
    r("SKU-D", "trang 1", description="Blender BL-02", dims_text="40x30x35 cm", dims_of="carton",
      mass_text="6.2 kg", mass_kind="gross", mass_of="carton"),
    r("SKU-D", "trang 1", description="Wooden pallet", dims_text="1200 x 1000 mm, loaded height 1.5 m", dims_of="pallet",
      mass_text="160 kg", mass_kind="gross", mass_of="pallet", stack_text="Pallets are not stackable", no_stack=True),
    r("SKU-E", "trang 1", description="Electric kettle KT-17", dims_text="35x25x30 cm", dims_of="carton",
      mass_text="3.1 kg", mass_kind="gross", mass_of="carton", in_shipment=False),
])

LABEL_PHOTO = DocumentReading(kind="label", items=[
    r("SKU-C", "nhãn", description="GLASS SET GL-06", dims_text="50 x 50 x 60 CM", dims_of="carton",
      mass_text="G.W. 18 KG", mass_kind="gross", mass_of="carton", upright_text="THIS SIDE UP",
      stack_text="STACKING LIMIT 2", stack_limit=2, fragile_text="FRAGILE"),
])

BY_FILE = {PL: PACKING_LIST, SPEC: SPECIFICATION, LABEL: LABEL_PHOTO}
