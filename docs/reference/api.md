---
status: draft
updated: 2026-10-26
owner: Hiếu
---

# HTTP API

Mọi route của app. Kiểu dữ liệu: [data-model.md](data-model.md). Đăng nhập và CSRF: [architecture.md](../product/architecture.md) §6. Code: `src/web/service/lots.py`, `src/web/service/chat.py`, `src/web/api.py`, `src/web/service/runs.py`, `src/web/auth.py`.

## Quy ước chung

- Mọi route cần phiên đăng nhập, trừ `GET /login`, `GET /healthz`, `POST /api/login`. Thiếu phiên: 401, hoặc `GET /` chuyển tới `/login`.
- Request đổi trạng thái (`POST`, `DELETE`) phải có `Origin` trong `PLANNER_ORIGINS`; có body thì body phải là `application/json`. Sai: 403 `forbidden`.
- Lỗi luôn có dạng `{code, message, details[]}`; `message` viết tiếng Việt cho người dùng, `details[]` mỗi phần tử một vấn đề (`message`, `line`, `container`, `field`).

| HTTP | `code` | Khi nào |
|---|---|---|
| 401 | `unauthorized` | Chưa đăng nhập, sai mật khẩu |
| 403 | `forbidden` | Sai `Origin`, body không phải JSON |
| 404 | `not_found` | Không có, hoặc của người khác |
| 409 | `conflict` | Ghi lô trên `rev` cũ: tải lại lô rồi làm lại |
| 409 | `not_ready` | Lô còn trường chưa xác nhận; `details[].field` liệt kê `"<line id>.<field>"` |
| 422 | `invalid_input` | Dữ liệu không hợp lệ: tệp không đọc được, câu trả lời sai, chế độ chưa có |
| 503 | `queue_full` | Hàng đợi engine đầy |

## Lô

| Route | Body | Trả về |
|---|---|---|
| `GET /api/lots` | — | Lô gốc của người dùng, mới sửa trước: `id`, `name`, `documents`, `open_points`, `lines`, `confirmed`, `updated_at`, `last_run` (lần chạy mới nhất của họ lô, cùng trường như `runs[]` của thân lô, hoặc null) |
| `POST /api/lots` | `{name, parent_id?, note?}` | 201, thân lô. Có `parent_id` là bản what-if: chép lô và bảng cước của lô đó |
| `GET /api/lots/{id}` | — | Thân lô (dưới) |
| `PATCH /api/lots/{id}` | `{rev, name}` | Thân lô. Đổi tên; `rev` cũ thì 409 |
| `DELETE /api/lots/{id}` | — | `{ok}`. Đánh dấu xóa, hoàn tác được trong 1 ngày |
| `POST /api/lots/{id}/restore` | `{}` | Thân lô |
| `POST /api/lots/{id}/documents` | `{files: [{name, data}]}`, `data` là base64; 1–20 tệp, mỗi tệp ≤ 10 MB; `.xlsx`, `.csv`, `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp` | 202, thân lô. Tệp vào hàng đọc nền; trạng thái từng tệp ở `documents[].status` |
| `POST /api/lots/{id}/documents/{doc_id}/read` | — | 202, thân lô. Đọc lại một tệp đọc lỗi; lô được ghép lại sau đó; 409 khi tệp không ở trạng thái `failed` |
| `DELETE /api/lots/{id}/documents/{doc_id}` | — | Thân lô. Xóa hẳn tệp và bản đọc, ghép lại lô từ các tệp còn lại (`forget` rồi `carry`); 409 khi còn tệp đang đọc |
| `POST /api/lots/{id}/lines` | `{rev, sku, description?, unit?, values}`; `values`: đủ 6 trường | 201, thân lô. Dòng người dùng nhập, không nguồn, đã xác nhận |
| `POST /api/lots/{id}/lines/{line_id}` | `{rev, values?, sku?, description?}` | Thân lô. Trường gửi lên thành đã xác nhận; trường đang ở chỗ cần xác nhận bị từ chối; mã, mô tả chỉ sửa được ở dòng người dùng nhập |
| `POST /api/lots/{id}/lines/{line_id}/drop` | `{rev}` | Thân lô. Dòng từ tài liệu sang `excluded`, dòng người dùng nhập xóa hẳn |
| `POST /api/lots/{id}/lines/{line_id}/restore` | `{rev}` | Thân lô. Dòng người dùng đã bỏ (ở bảng hoặc ở chỗ cần xác nhận) lấy lại từ tài liệu |
| `POST /api/lots/{id}/points/{point_id}` | `{rev, choice?, values?}`; `values`: `"<line id>.<field>"` → giá trị | Thân lô, `rev` tăng 1. Chỗ đã trả lời trả lời lại được: lựa chọn mới thay lựa chọn cũ; dòng lựa chọn cũ đã bỏ được lấy lại từ tài liệu của lô |
| `POST /api/lots/{id}/confirm` | `{rev}` | Thân lô; các trường `extracted` thành `confirmed`. 409 `not_ready` khi còn trường cần xác nhận |
| `GET /api/lots/{id}/chat` | — | Hội thoại: `[{id, role, content, created_at}]` |

**Thân lô:** `id`, `name`, `rev`, `parent_id`, `note`, `lot` (lô JSON), `containers` (bảng cước đang dùng), `documents[]` (`id`, `name`, `mime`, `size`, `status`, `error`, `created_at`), `settled` (false khi còn tệp chờ hoặc đang đọc, hoặc đã đọc mà lô chưa ghép lại; trang chờ cho tới khi true), `family[]` (lô gốc và mọi bản what-if: `id`, `name`, `note`, `parent_id`), `runs[]` (run của cả họ lô, mới trước: `job_id`, `lot_name`, `created_at`, `status`, `code`, `cost`, `lot_id`, `mode`, `containers` là danh sách loại, `placed` số kiện trong phương án (null khi không có), `total` số kiện của lô đưa vào lần chạy), `updated_at`.

## Chạy

| Route | Body | Trả về |
|---|---|---|
| `GET /api/plan/containers` | — | `{containers, simulated: true}`: bảng cước mặc định |
| `POST /api/lots/{id}/runs` | `{mode: "a" \| "b", containers?, time_limit?, fill?, delta?, alpha?, orient?}`; `delta` ≥ 0 (mặc định 0,05 m), `alpha` 0–1 (mặc định 0,8), `orient` chỉ có tác dụng khi lô có dòng được lật (bỏ trống: bật khi có); `containers` mỗi phần tử `{id, L, W, H, door_w, door_h, max_mass, cost}`; chế độ B cần `fill: {fleet: {loại: số}, priority?: [line id], partial?: bool}` | 202, trạng thái job. Bảng cước gửi lên ở chế độ A được lưu cùng lô. 409 `not_ready` khi lô chưa xác nhận đủ; 422 khi `mode` khác `a`, `b`, hoặc `fill` không khớp lô |
| `POST /api/lots/{id}/compare` | `{containers?, mode?, fill?, delta?, alpha?}`; so với lô **hiện tại** | Chế độ A: `{bound, baselines[], cheapest_single, fewest_containers, settings}` ([engine/README.md](../product/engine/README.md) §3). Chế độ B: baseline lấp lần lượt theo thứ tự ưu tiên `{lines[{id, placed}], placed, total, containers, ok, seconds, settings}` (§4). Chạy đồng bộ, vài giây |
| `POST /api/runs/{job_id}/compare` | `{}`; lô, đội (chế độ B), `delta`, `alpha` lấy từ lần chạy (đang chạy hoặc đã lưu), không lấy lô hiện tại. Màn Kết quả dùng route này | Như route trên theo chế độ của lần chạy, thêm `lot_changed`: dữ liệu dòng hàng hoặc bảng cước của lô đã khác lúc chạy (lô chưa xác nhận đủ cũng tính là đã đổi). 404 khi không có lần chạy |
| `GET /api/jobs/{job}` | — | `{id, status, position, elapsed, time_limit, hard_limit, code, error, has_result, saved, orient}`; `status`: `queued`, `running`, `done`, `stopped`, `failed` |
| `POST /api/jobs/{job}/stop` | `{}` | Trạng thái job |
| `GET /api/jobs/{job}/result` | — | Kết quả xem (data-model §4); 404 khi chưa có |
| `GET /api/jobs/{job}/lot.json`, `/solution.json` | — | Lô engine, lời giải |
| `GET /api/runs` | — | Mọi run đã lưu của người dùng |
| `GET /api/runs/{job}` | — | Kết quả xem của run đã lưu (cả sau khi app khởi động lại) |
| `GET /api/runs/{job}/lot.json`, `/solution.json` | — | Như trên |
| `DELETE /api/runs/{job}` | — | `{ok}` |

Job (`/api/jobs/…`) chỉ sống trong bộ nhớ tiến trình; run đã xong đọc lại qua `/api/runs/…`.

## Chat

`POST /api/lots/{id}/chat`, body `{text}` (1–4 000 ký tự). Trả `text/event-stream`; mỗi sự kiện là một dòng `data: <JSON>`:

| `type` | Trường | Khi nào |
|---|---|---|
| `action` | `text` | Trợ lý vừa chạy một công cụ |
| `proposal` | `kind` (`answer` / `confirm` / `add_line` / `edit_line`), `lot_id`, `label`; `answer`: `point_id`, `title`, `choice`, `values`; `add_line`, `edit_line`: `line_id` (null khi thêm), `body` (thân request của route dòng, thiếu `rev`) | Trợ lý đề xuất; trang hiện nút, người bấm thì trang gọi route `points`, `confirm`, `lines` hoặc `lines/{line_id}` |
| `lot` | `lot_id`, `parent_id` | Đã tạo bản what-if |
| `run` | `lot_id`, `job_id` | Đã xếp một job |
| `message` | `text`, `unverified`, `actions`, `proposals`, `lot_id`, `rev` | Câu trả lời; sự kiện cuối |
| `error` | `message` | Model lỗi; sự kiện cuối |

## Khác

| Route | Trả về |
|---|---|
| `GET /` | Trang app ([ux.md](../product/ux.md)) |
| `GET /login`, `POST /api/login` `{name, password}`, `POST /api/logout`, `GET /api/me` | Đăng nhập |
| `GET /healthz` | Kiểm tra sống |
| `GET /api/config` | Mặc định và giới hạn của service (thời gian, `δ`, `α`, engine) |
| `POST /api/lots/validate`, `POST /api/jobs`, `POST /api/check` | Route trên lô engine JSON; app không dùng, giữ cho chạy thử engine trực tiếp |
