# probe — bộ tài liệu demo và eval

Dữ liệu **giả lập**: công ty, sản phẩm, số liệu, cước đều tự đặt, không phải dữ liệu hay báo giá thật. Một lô hàng mô tả rời rạc qua nhiều tài liệu lộn xộn, có bẫy cài sẵn có chủ đích, để thử agent đọc tài liệu: bộ demo của sản phẩm và bộ `set-00` của eval.

| File | Nội dung |
|---|---|
| `packing_list.xlsx` | Packing list tiếng Việt: 3 dòng tiêu đề trước header, kích thước gộp một cột, đơn vị trộn |
| `packing_list.csv` | Cùng dữ liệu, dạng CSV (UTF-8 BOM) |
| `product_spec.pdf` | Spec tiếng Anh: kích thước, khối lượng cả bì (G.W.), lưu ý xếp, dữ liệu pallet của SKU-D; đối chiếu với packing list |
| `handling_label_sku_c.png` | Ảnh nhãn thùng SKU-C: this side up, fragile, giới hạn chồng 2 |
| `freight_rates.csv` | Kích thước trong, tải trọng, cước của 20GP / 40GP / 40HC |
| `answers.json` | Đáp án: lô đúng và các bẫy (eval); không đưa cho agent |

## Bẫy cài sẵn và đáp án đúng

| # | Bẫy | Hành vi đúng |
|---|---|---|
| 1 | SKU-A có 2 dòng trong packing list, cao **50 cm** và **45 cm**; spec ghi 450 mm | Phát hiện cùng mã khác kích thước, nêu nguồn, hỏi người dùng. Không lặng lẽ tách 2 dòng hay chọn một |
| 2 | SKU-A, SKU-B: packing list ghi khối lượng tịnh (N.W.), spec ghi cả bì (G.W. 12,5 / 26 kg) | Nhận ra hai loại khối lượng; xếp hàng dùng G.W. |
| 3 | SKU-B: kích thước theo mm, khối lượng `25` không có đơn vị | Đổi về 80×60×50 cm; hỏi hoặc lấy đơn vị từ spec |
| 4 | SKU-C: packing list **thiếu khối lượng** | Lấy 18 kg từ spec hoặc nhãn, ghi nguồn; nếu chỉ có packing list thì hỏi. **Không** tự điền 1 kg |
| 5 | SKU-C: nhãn ảnh có this side up, fragile, giới hạn chồng 2 | Chuyển thành ràng buộc hướng đặt và chồng |
| 6 | SKU-D: số lượng và kích thước theo **pallet** (10 pallet × 24 thùng, 120×100×150 cm, 160 kg, không chồng) | Xếp 10 pallet, không phải 240 thùng mang kích thước pallet |
| 7 | SKU-E chỉ có trong spec, ghi "Not in this shipment" | Không đưa vào lô |
| 8 | Bảng cước 3 loại container | Chọn tổ hợp container có tổng cước thấp nhất, không chỉ tối đa độ lấp đầy |

Sinh lại: `python -m scripts.gen_demo` (cần `requirements-dev.txt`). Script ghi cả `answers.json`: lô đúng sau khi xác nhận (từng dòng, kèm các trường có tài liệu nêu) và các bẫy phải bắt. Trường không tài liệu nào nêu có giá trị thật trong đáp án nhưng phải hỏi người dùng, không được điền. Biến thể cho eval: `python -m scripts.gen_demo --seed <n> --out <thư mục> [--traps dup_height,pallet,...]`.

Bộ này cũng là bộ demo của sản phẩm. Bảng cước lấy theo bảng mặc định của chế độ A (`src/plan/mode_a.py`).
