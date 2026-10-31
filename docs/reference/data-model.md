---
status: draft
updated: 2026-10-25
owner: Hiếu
---

# Mô hình dữ liệu

Các cấu trúc dữ liệu của sản phẩm và nơi lưu chúng. Vì sao lô có hình dạng này: ADR-0001 ([../adr/0001-schema-lo-hang.md](../adr/0001-schema-lo-hang.md)). Code là nguồn cuối cùng: `src/lot/schema.py`, `src/extract/readings.py`, `src/formats.py`, `src/web/db.py`.

## Mục lục

| # | Mục |
|---|---|
| 1 | [Đơn vị và hệ trục](#1-đơn-vị-và-hệ-trục) |
| 2 | [Lô](#2-lô) |
| 3 | [Bản đọc tài liệu](#3-bản-đọc-tài-liệu) |
| 4 | [Lô của engine và lời giải](#4-lô-của-engine-và-lời-giải) |
| 5 | [Bảng SQLite](#5-bảng-sqlite) |

## 1. Đơn vị và hệ trục

- Mét, kg, độ. Giá trị trong lô đã đổi về đơn vị này; chữ gốc của tài liệu nằm ở `Source.raw`.
- Container: `x` theo chiều dài từ đáy trong ra cửa, `y` theo chiều rộng, `z` hướng lên. Tọa độ một kiện là góc trong-trái-dưới.
- Thời điểm: ISO 8601, UTC.

## 2. Lô

Một lô là một document JSON (`Lot`, `schema_version` 1).

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `schema_version` | `1` | Đổi schema thì tăng và viết bước chuyển lô cũ |
| `name` | chuỗi | Tên lô |
| `lines` | `Line[]` | Các dòng hàng, theo thứ tự packing list |
| `points` | `Point[]` | Chỗ cần xác nhận, cả đã trả lời |
| `excluded` | `Excluded[]` | Mã tài liệu nhắc tới nhưng không ở trong lô |

**`Line`** — một dòng hàng.

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `id` | chuỗi, không khoảng trắng, không `#` | Mã dòng cho engine, duy nhất trong lô: mã hàng, thêm `-2`, `-3` khi một mã có nhiều dòng |
| `sku` | chuỗi | Mã hàng như tài liệu ghi; màn hình hiện mã này, không hiện `id` |
| `description` | chuỗi | Mô tả |
| `unit` | `carton` / `pallet` / `piece` | Một kiện là gì |
| `qty` | `LotField[int]`, > 0 | Số kiện |
| `dims` | `LotField[Dims]` | `L`, `W`, `H` (m), mỗi cạnh > 0 và ≤ 20 |
| `mass` | `LotField[float]`, > 0 | Khối lượng một kiện, cả bì (kg) |
| `posture` | `LotField["upright" \| "tippable"]` | Chỉ đứng (xoay quanh trục đứng), hoặc được lật |
| `stacking` | `LotField[Stacking]` | `{kind: "free"}`, `{kind: "limited", tiers: n}` (tính cả chính nó), `{kind: "none"}` |
| `fragile` | `LotField[bool]` | Chỉ để hiện; engine không đọc |

**`LotField`** — mọi trường của dòng.

| Trường | Ý nghĩa |
|---|---|
| `value` | Giá trị đã chuẩn hóa; `null` khi không có (khi đó luôn `needs_review`) |
| `status` | `extracted` (nguồn khớp nhau), `needs_review` (thiếu, mâu thuẫn, nghi ngờ), `confirmed` (người dùng đã xác nhận) |
| `sources` | `Source[]`: `file`, `where` (dòng, trang, nhãn), `raw` (chữ như tài liệu ghi; `null` là ô trống) |
| `confirmed_by`, `confirmed_at` | Ai xác nhận, lúc nào |

Nguồn có `file = "chat"` là giá trị người dùng nói trong chat (what-if); `raw` bắt đầu bằng `not in shipment` là một tài liệu ghi mã đó không giao.

**`Point`** — một chỗ cần xác nhận ([agent.md](../product/agent.md) §3).

| Trường | Ý nghĩa |
|---|---|
| `id` | Số thứ tự theo trang, từ 1 |
| `title`, `question` | Viết theo mẫu cố định |
| `fields` | Các trường chỗ này chốt, dạng `"<line id>.<field>"` |
| `options` | `Option[]`: `label`, `sets` (`"<line id>.<field>"` → giá trị; `"<line id>.line": "drop"` là bỏ dòng), `sources` |
| `chosen` | Chỉ số lựa chọn đã chọn; `null` khi chưa trả lời hoặc người dùng nhập giá trị riêng |
| `resolved_by`, `resolved_at` | Ai trả lời, lúc nào; `resolved_at = null` là chỗ còn mở |

**`Excluded`**: `sku`, `description`, `reason`, `sources`.

**Lô chạy được** khi mọi trường của mọi dòng là `confirmed` (`Lot.open_fields()` rỗng).

## 3. Bản đọc tài liệu

Đầu ra của model cho một tài liệu (`DocumentReading`), lưu nguyên trong bảng `documents` để ghép lại mà không gọi model lần nữa.

| Trường | Ý nghĩa |
|---|---|
| `kind` | `packing_list`, `spec`, `label` |
| `items[]` | Một mục mỗi lần tài liệu nhắc tới một mã (hai dòng cùng mã là hai mục) |

Mỗi mục (`ItemReading`): `sku`, `description`, `where`, `in_shipment`, `qty_text`, `unit`, `dims_text`, `dims_of`, `mass_text`, `mass_kind` (`gross` / `net` / `unknown`), `mass_of`, `upright_text`, `stack_text`, `stack_limit`, `no_stack`, `fragile_text`. Mọi giá trị là chữ chép nguyên từ tài liệu; đổi đơn vị là việc của code.

## 4. Lô của engine và lời giải

Định dạng JSON của engine (`src/formats.py`); là thứ job nhận và run lưu.

- **Lô engine:** `name`, `meta` (chế độ B: `meta.fill` = `{fleet, priority, partial}`), `container_types[]` (`id`, `L`, `W`, `H`, `door_w`, `door_h`, `max_mass`, `cost`), `items[]` (`id`, `qty`, `L`, `W`, `H`, `mass`, `tippable`, `tiers` (`null` là không giới hạn), `load` (`null` là không giới hạn), `orientations` khi khác mặc định).
- **Lời giải:** `instance`, `params` (`delta`, `alpha`), `containers[]` (`k` từ 1, `type`), `placements[]` (`item` dạng `"<line id>#<n>"`, `k`, `x`, `y`, `z`, `o` mã tư thế như `LWH`, `WLH`).
- **Kết quả xem** (`/api/jobs/{id}/result`, `/api/runs/{id}`): lô, lời giải đã dựng hình (mỗi container kèm khối lượng, thể tích, tỉ lệ dùng, số kiện mỗi dòng, thứ tự tua), kết quả checker (`ok`, `cost`, `violations`), cận dưới, tham số.

## 5. Bảng SQLite

Một file (`PLANNER_DB`), migration trong `src/web/db.py` (`PRAGMA user_version`).

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `users` | `name`, `pw_hash` (argon2id), `active` | Tạo bằng CLI `python -m src.web.users` |
| `sessions` | `token_hash`, `user_id`, `expires_at` | Chỉ lưu hash của token |
| `login_failures` | `name`, `at` | Khóa tên sau nhiều lần sai |
| `lots` | `user_id`, `parent_id`, `name`, `note`, `rev`, `lot` (JSON), `containers` (JSON bảng cước), `deleted_at` | `parent_id` khác null là bản what-if; `deleted_at` khác null là đã xóa, giữ 1 ngày để hoàn tác |
| `documents` | `lot_id`, `name`, `mime`, `size`, `data` (blob), `status` (`waiting`, `reading`, `read`, `failed`), `reading` (JSON), `error` | Tối đa 10 MB mỗi tệp |
| `chat_messages` | `lot_id`, `role` (`user`, `assistant`), `content` (JSON: `text`, `actions`, `proposals`, `unverified`) | Hội thoại của lô |
| `runs` | `job_id`, `user_id`, `lot_id`, `mode`, `status`, `code`, `cost`, `settings`, `lot`, `result`, `solution`, `diag` | Một run xong; giữ `PLANNER_RUN_DAYS` ngày; xóa lô thì `lot_id` thành null |

Dữ liệu người dùng (file DB, tài liệu upload) không bao giờ vào git.
