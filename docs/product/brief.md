---
status: draft
updated: 2026-10-24
owner: Hiếu
---

# Loading AI Planner — Product brief

Web app lập phương án xếp hàng vào container: **AI agent** biến tài liệu hàng hóa rời rạc thành dữ liệu lô hàng đã xác nhận, **engine tối ưu** tạo phương án xếp 3D theo chi phí hoặc theo sức chứa.

## 1. Vấn đề

- Thông tin hàng nằm rải rác: packing list Excel, spec PDF, ảnh nhãn kiện. Cùng một SKU có thể lệch kích thước, khối lượng, đơn vị giữa các nguồn; nhầm kích thước kiện với kích thước pallet, khối lượng tịnh với cả bì.
- Phần lớn phần mềm xếp container vẫn đòi nhập tay hoặc import file đúng template. Công cụ đã dùng AI đọc tài liệu thì kết quả phụ thuộc cách hỏi: lặng lẽ chọn một giá trị khi tài liệu mâu thuẫn, tự điền giá trị thiếu (1 kg), không lưu nguồn, không bắt người dùng xác nhận.
- Dữ liệu sai đi vào solver cho ra phương án trông hợp lệ nhưng không đóng được.
- Hai câu hỏi thực tế khác nhau: *"lô này cần ít tiền nhất bao nhiêu container?"* và *"có sẵn N container, xếp được nhiều hàng nhất là bao nhiêu, ưu tiên hàng nào?"*. Câu thứ nhất thường được trả lời bằng "ít container nhất" hoặc "lấp đầy nhất", không theo tổng cước. Câu thứ hai chỉ có dạng lấp lần lượt từng container theo thứ tự liệt kê.

**Người dùng:** nhân viên logistics / điều phối đóng hàng ở doanh nghiệp xuất nhập khẩu, sản xuất nhiều SKU.

## 2. Giải pháp

### 2.1 AI agent (giao diện chat, hành động có kiểm soát)

| Chức năng | Mô tả |
|---|---|
| Nhập liệu đa tài liệu | Nhận nhiều file một lúc (Excel, PDF, ảnh). Trích xuất vào schema thống nhất; chuẩn hóa đơn vị; ghép theo SKU, giữ nguyên mã SKU gốc; lưu nguồn cho từng trường (file, sheet/dòng, trang). Đọc ký hiệu trên nhãn (this side up, fragile, giới hạn chồng) thành ràng buộc đề xuất, cũng cần xác nhận như trường khác. Kết quả trích xuất và nguồn lưu cùng lô, agent đọc lại được ở mọi lượt chat sau. |
| Phát hiện và hỏi lại | Chỉ ra trường thiếu, trùng, mâu thuẫn kèm nguồn; hỏi người dùng trong chat; người dùng xác nhận trước khi dữ liệu được chốt. |
| Gọi engine | Chạy một trong hai chế độ tối ưu (2.2) theo yêu cầu người dùng. Agent chỉ gọi, không xếp. |
| What-if | Đổi tham số qua chat ("chỉ có 2x40HC", "bỏ SKU B", "thêm 50 thùng"), chạy lại, so sánh với phương án trước. |
| Giải thích | Diễn giải phương án bằng số liệu engine trả về (tổng cước, số container theo loại, tỷ lệ sử dụng, hàng còn lại). |

### 2.2 Engine tối ưu (hai chế độ)

| Chế độ | Cố định | Mục tiêu |
|---|---|---|
| A. Tối thiểu chi phí | Lô hàng | Chọn loại và số container, xếp hết hàng, tổng cước nhỏ nhất. Solver chọn tổ hợp container, không để LLM liệt kê hay đoán |
| B. Tối đa hàng | Danh sách container có sẵn | Xếp nhiều hàng nhất theo thứ tự ưu tiên người dùng đặt; phân hàng giữa các container có tối ưu, không lấp lần lượt theo thứ tự; báo hàng còn lại |

Mọi phương án qua validator hình học và tải trọng độc lập trước khi hiển thị.

### 2.3 Nguyên tắc

- AI không tự chọn giữa hai giá trị mâu thuẫn, không điền giá trị thiếu bằng phỏng đoán.
- Đối chiếu là một bước cố định của quy trình, chạy giống nhau bất kể người dùng hỏi thế nào.
- Còn trường nào ở trạng thái `needs_review` thì không chạy engine. Chỉ dữ liệu đã xác nhận được gửi sang engine. Đơn vị, kiểu dữ liệu, trường bắt buộc kiểm ở backend, không dựa vào prompt.
- LLM không quyết định tính hợp lệ của phương án; validator quyết định.
- Engine là heuristic: không tuyên bố tối ưu toàn cục; so với baseline.

## 3. Phạm vi

**Trong phạm vi:**

- Đăng nhập. Tài khoản do admin tạo/seed, không có trang đăng ký.
- Upload nhiều tài liệu cho một lô; Excel, PDF, ảnh.
- Bảng dữ liệu lô hàng: nguồn từng trường, trạng thái `extracted` / `needs_review` / `confirmed`.
- Hai chế độ tối ưu A, B; xem phương án 3D, tổng cước, so baseline.
- Lưu lịch sử theo người dùng: lô hàng, tài liệu, hội thoại, các lần chạy và kết quả.
- Bộ dữ liệu demo giả lập (packing list, spec, ảnh nhãn, bảng cước) có mâu thuẫn cài sẵn.

**Ngoài phạm vi:**

- Tích hợp ERP/WMS/TMS, booking với hãng tàu.
- Xe tải, pallet (chỉ container biển).
- Bản vẽ CAD, ước kích thước kiện từ ảnh chụp.
- Đăng ký tự phục vụ, phân quyền nhiều vai trò.

## 4. Ràng buộc kỹ thuật

- Build bằng Google AI Studio và/hoặc Antigravity; LLM là Gemini qua Google GenAI SDK (structured output, function calling).
- Một backend FastAPI chứa cả agent và engine. Engine tái dùng từ một dự án trước của tác giả (fleet layer, packing core, checker, job chạy trong subprocess); chế độ B là phần mới.
- Auth, lưu lịch sử, viewer 3D tái dùng từ cùng dự án đó (argon2id, SQLite, seed tài khoản bằng CLI).
- Dữ liệu thật: không có. Mọi số liệu demo là giả lập và ghi rõ như vậy.

