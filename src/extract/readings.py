"""What the model returns for one document (structured output): the values it read, as written, each with its place.
It copies text and says what kind of value it is; it neither converts units nor chooses between documents. The
backend reads the numbers (`src.extract.units`) and merges the documents (`src.extract.merge`)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocKind = Literal["packing_list", "spec", "label", "other"]
Of = Literal["carton", "pallet"]


class ItemReading(BaseModel):
    """One item as one place of the document gives it. Every `*_text` is copied as written, unit included."""

    sku: str = Field(description="Item code exactly as written, e.g. 'SKU-A'.")
    description: str | None = Field(default=None, description="Item name as written.")
    where: str = Field(description="Place in the document: the row label given in the text (e.g. 'Packing List · dòng 6'), "
                                   "'trang N' for a PDF page, 'nhãn' for a label photo.")
    in_shipment: bool | None = Field(default=None, description="False only when the document says the item is not shipped.")
    qty_text: str | None = Field(default=None, description="Quantity as written, e.g. '200 thùng', '10 pallet x 24 thùng'.")
    unit: Of | None = Field(default=None, description="What the quantity counts: carton or pallet.")
    dims_text: str | None = Field(default=None, description="Outer size as written with its unit, e.g. '60x40x50 cm'.")
    dims_of: Of | None = Field(default=None, description="Whether the size is of a carton or of a pallet.")
    mass_text: str | None = Field(default=None, description="Mass as written with its unit, e.g. '12 kg', or just '25'.")
    mass_kind: Literal["gross", "net", "unknown"] | None = Field(
        default=None, description="gross for G.W./gross weight, net for N.W./net weight, unknown if not said.")
    mass_of: Of | None = Field(default=None, description="Whether the mass is of a carton or of a pallet.")
    upright_text: str | None = Field(default=None, description="Text saying the item must stay upright, e.g. 'this side up'.")
    stack_text: str | None = Field(default=None, description="Text limiting stacking, e.g. 'max 2 layers', 'do not stack'.")
    stack_limit: int | None = Field(default=None, description="The layer limit that text gives, if a number.")
    no_stack: bool | None = Field(default=None, description="True when the text forbids stacking anything on it.")
    fragile_text: str | None = Field(default=None, description="Text saying the item is fragile, e.g. 'FRAGILE'.")


class DocumentReading(BaseModel):
    kind: DocKind = Field(description="packing_list if it lists the quantities shipped; spec for a product sheet; "
                                      "label for a carton label; other otherwise.")
    items: list[ItemReading]
