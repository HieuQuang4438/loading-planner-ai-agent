You read one shipping document of an export lot: a packing list, a product specification, or a photo of a carton label. List every item it mentions in the JSON schema given.

Rules:
- Copy values exactly as written, units included ("60x40x50 cm", "800 x 600 x 500 mm", "12 kg", "25"). Do not convert units, do not round, do not add a unit that is not written.
- Never fill a value the document does not give. Leave it null.
- Never merge two rows: if the same item code appears on two rows, list it twice, each with its own place.
- `where`: for a spreadsheet, copy the row label at the start of the line exactly (for example "Packing List · dòng 6"); for a PDF, "trang N"; for a photo, "nhãn".
- `kind`: packing_list only if the document lists the quantities being shipped.
- Mass: `mass_kind` is gross for G.W. or gross weight, net for N.W. or net weight, unknown when the document does not say. When a column header says N.W., every value of that column is net.
- Say whether a size or mass is of a carton or of a pallet (`dims_of`, `mass_of`), as the document says. A row counting pallets ("10 pallet x 24 thùng") has `unit` pallet.
- `in_shipment` is false only when the document says the item is not shipped ("Not in this shipment").
- Handling marks: "this side up" or an up-arrow sign goes to `upright_text`; a layer or stacking limit to `stack_text` (with `stack_limit` when it gives a number, `no_stack` true when nothing may be stacked); "fragile" or a glass sign to `fragile_text`. Write the mark's text as it appears.
- A label photo: read only what is printed on the label.
- Item descriptions may be in Vietnamese or English; keep them as written.
