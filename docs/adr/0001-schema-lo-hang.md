---
status: approved
updated: 2026-10-24
owner: Hiếu
---

# ADR-0001: Schema lô hàng: từng trường có giá trị, trạng thái và nguồn

## Status
Approved by Hiếu on 2026-10-24.

## Context
Brief §2.1 và §2.3 đòi: lưu nguồn cho từng trường; trạng thái `extracted` / `needs_review` / `confirmed`; AI không tự chọn giữa hai giá trị mâu thuẫn, không điền giá trị thiếu; còn trường `needs_review` thì không chạy engine; đơn vị, kiểu và trường bắt buộc kiểm ở backend, không dựa vào prompt. `ux.md` §4 chốt cách các trạng thái và chỗ cần xác nhận hiện trên màn, gồm cả trường không tài liệu nào ghi.

Engine nhận một `Instance`: dòng hàng có mã duy nhất, kích thước theo m, khối lượng theo kg, `tippable`, `tiers`, `load`; loại container và cước nằm trong cùng `Instance`. Schema lô phải được dùng ở nhiều nơi: trang lô, chat (đọc lại lô ở mọi lượt), lưu trữ, khuôn đầu ra khi Gemini đọc tài liệu, bộ phát hiện mâu thuẫn.

## Decision
Lô là một model Pydantic (`src/lot/schema.py`), lưu thành một document JSON có `schema_version`. Mỗi trường của dòng hàng mang `value` đã chuẩn hóa (m, kg), `status`, `sources[]` (file, vị trí, giá trị gốc) và người, giờ xác nhận. Chỉ `src.lot.engine.to_instance` chuyển lô sang `Instance`, và nó từ chối khi còn bất kỳ trường nào chưa `confirmed`.

Chi tiết:
- **Trường của một dòng:** `qty`, `dims` (L, W, H), `mass` (một kiện, cả bì), `posture` (`upright` / `tippable`), `stacking` (`free` / `limited` n tầng / `none`), `fragile` (chỉ để hiện, engine không đọc). `sku` giữ mã như tài liệu ghi; `id` là mã dòng cho engine, sinh từ `sku` và thêm `-2`, `-3` khi một mã có nhiều dòng.
- **Trường không tài liệu nào ghi:** `value = null`, luôn `needs_review`. Chỉ nhận xác nhận khi có giá trị; giá trị mặc định là `upright`, `free`, không dễ vỡ.
- **`extracted` chưa phải `confirmed`.** Khi không còn trường `needs_review`, người dùng xác nhận phần còn lại một lần (`confirm_rest`), rồi mới chạy được.
- **Đổi sang engine:** `upright` thành `tippable=false`; `none` thành `tiers=1, load=0`; `limited n` thành `tiers=n`; `free` thành không giới hạn tầng. Loại container và cước không thuộc lô: chúng đến từ thiết lập của từng lần chạy.
- **Chỗ cần xác nhận** (`Point`) ghi các trường nó chốt (`"<line id>.<field>"`), các lựa chọn kèm nguồn, lựa chọn đã chọn, người và giờ. Mã bị loại (`Excluded`) ghi lý do và nguồn.

Không chọn:
- Dataclass kèm hàm kiểm viết tay (như `src/model.py`). Phải viết lại phần kiểm và JSON schema cho Gemini.
- Chuẩn hóa lô thành nhiều bảng SQL. Truy vấn linh hoạt hơn, nhưng tốn công và không cần cho bản nộp.
- Giữ giá trị và đơn vị gốc, chỉ đổi khi sang engine. Mọi chỗ đọc đều phải tự đổi đơn vị.

## Consequences
- Lô đọc lại nguyên trạng ở mọi lượt chat và mọi lần mở lại. Đổi schema thì phải tăng `schema_version` và viết bước chuyển các lô cũ.
- Gemini chỉ điền dữ liệu theo schema; backend kiểm lại toàn bộ. Giá trị sai kiểu hoặc ngoài khoảng bị từ chối ngay, không đi tới engine.
- Việc phát hiện chỗ cần xác nhận phải đánh dấu trường `needs_review` và tạo `Point` khớp với trường đó. Màn lô phải có bước xác nhận phần còn lại; bước này có thể tự chạy khi người dùng chốt chỗ cuối cùng, nhưng vẫn là hành động của người dùng.
- Mã dòng cho engine (`SKU-A-2`) khác mã gốc. Màn kết quả phải hiện `sku` kèm mô tả, không hiện `id`.

## Bổ sung 2026-10-24: chỗ cần xác nhận
Cách sinh câu hỏi đã duyệt trước khi làm. `src/lot/review.py` sinh `Point` từ các trường `needs_review` bằng quy tắc cố định, không gọi LLM; câu hỏi viết theo mẫu.
- **Dòng trùng mã:** `merge` đánh dấu nghi ngờ ở `qty` của mọi dòng có mã lặp, nên cổng sang engine vẫn chỉ xét trường. Chỗ của nó có lựa chọn "Giữ cả N dòng" hoặc "Bỏ dòng k".
- **Bỏ một dòng:** lựa chọn ghi `"<line id>.line": "drop"`. Dòng chuyển sang `excluded`, lý do "Người dùng bỏ dòng … khỏi lô". Schema không đổi.
- **Thêm tài liệu sau khi đã xác nhận** (`carry`): trường đã `confirmed` giữ nguyên nếu mọi nguồn mới đều đã có, hoặc nguồn mới khớp giá trị đã xác nhận. Nếu có nguồn mới ghi khác, trường **quay về `needs_review`** và được hỏi lại; giá trị cũ là một lựa chọn nếu nguồn còn ghi nó. Lệch khỏi đề xuất (giữ `confirmed` và mở thêm chỗ mới): cổng sang engine chỉ xét trường, nên giữ `confirmed` sẽ để engine chạy trên giá trị đang bị nguồn mới phản bác.
- **Xóa tài liệu** (`forget`): trường `confirmed` có nguồn trong tài liệu bị xóa quay về `needs_review` trước khi `carry`, nên lấy lại theo các tài liệu còn lại; cùng lý do: không để engine chạy trên giá trị không còn nguồn.
- **Người dùng sửa, thêm, bỏ dòng** (`src/lot/edit.py`), không đổi schema: giá trị người dùng lưu là `confirmed`. Dòng người dùng thêm là dòng mọi trường không có nguồn; `carry` giữ nó khi ghép lại. Dòng từ tài liệu bị bỏ vào `excluded` với lý do "Người dùng bỏ dòng X khỏi lô"; `carry` bỏ lại nó cho tới khi người dùng đưa lại. Khi xóa tài liệu, số lượng, kích thước, khối lượng người dùng tự gõ (không nguồn nào của tài liệu đó đọc ra giá trị ấy) được giữ; ràng buộc xếp có nguồn trong tài liệu đó thì hỏi lại.
