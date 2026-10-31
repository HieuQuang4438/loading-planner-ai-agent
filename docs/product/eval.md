---
status: draft
updated: 2026-10-26
owner: Hiếu
---

# Eval

Đo agent đọc tài liệu đúng tới đâu và engine so với baseline. Mọi dữ liệu là **giả lập**. Agent làm gì: [agent.md](agent.md). Engine: [engine/README.md](engine/README.md).

## Mục lục

| # | Mục |
|---|---|
| 1 | [Bộ eval agent](#1-bộ-eval-agent) |
| 2 | [Chỉ số](#2-chỉ-số) |
| 3 | [Cách chạy](#3-cách-chạy) |
| 4 | [Kết quả agent](#4-kết-quả-agent) |
| 5 | [Eval engine](#5-eval-engine) |

## 1. Bộ eval agent

`python -m scripts.gen_eval` sinh 23 bộ vào `data/eval/` (gitignore; cùng lệnh luôn ra cùng file):

| Bộ | Sinh từ | Bẫy |
|---|---|---|
| `set-00` | Bộ probe (`data/probe/`) | Đủ 7 loại |
| `set-01` … `set-20` | `scripts/gen_demo.py --seed n`: 5 mã lấy từ danh mục 12 sản phẩm giả lập, số lượng ngẫu nhiên, một mã thứ sáu cho bẫy mã không giao | 2–7 loại, rút theo seed |
| `clean-21`, `clean-22` | Như trên | Không bẫy: đo câu hỏi thừa |

Mỗi bộ có packing list (Excel), spec (PDF), ảnh nhãn (khi có bẫy nhãn), bảng cước và `answers.json`. Đáp án sinh từ giá trị thật của từng sản phẩm, không gán tay: lô đúng, các trường có tài liệu nêu (`stated`), và mỗi bẫy nằm ở mã nào. Mỗi loại bẫy có trong ít nhất 5 bộ (script kiểm; hiện 11–15 bộ).

Bảy loại bẫy, hành vi đúng: [`data/probe/README.md`](../../data/probe/README.md) (bẫy 1–7) và `TRAP_TEXT` trong `scripts/gen_demo.py`.

Từng bộ có gì (sản phẩm, số lượng, bẫy nằm ở mã nào, ảnh nhãn): [eval-sets.md](eval-sets.md), sinh bằng `python -m scripts.gen_eval --doc`.

**Giới hạn:** mọi bộ cùng một khuôn (bố cục packing list, font, danh mục). Kết quả chỉ nói về dạng tài liệu này, không phải tài liệu thật của khách.

## 2. Chỉ số

Đo trên lô mà pipeline thật để lại **trước khi người dùng trả lời**: đọc từng tài liệu bằng Gemini, ghép theo luật cố định, sinh chỗ cần xác nhận (`scripts/eval_agent.py`).

| Chỉ số | Định nghĩa |
|---|---|
| Trường đúng | Trường có tài liệu nêu, trạng thái `extracted`, giá trị bằng đáp án |
| Trường đưa ra hỏi | Trường có tài liệu nêu, nằm trong một chỗ cần xác nhận đang mở |
| Trường sai | Trường có tài liệu nêu, `extracted`, khác đáp án (không ai hỏi) |
| Giá trị tự bịa (mục tiêu 0) | Trường sai, cộng trường không tài liệu nào nêu mà có giá trị và không bị hỏi |
| Bẫy bắt được | Mọi trường bẫy chạm tới đều được hỏi hoặc đọc đúng; bẫy trùng mã khác chiều cao còn phải có ít nhất một chỗ hỏi; mã không giao bắt được khi nó không thành dòng của lô, hoặc có chỗ hỏi về dòng đó |
| Câu hỏi thừa | Chỗ cần xác nhận không chạm trường của bẫy nào và không chạm trường mà tài liệu không nêu |

Trường mỗi bẫy chạm tới:

| Bẫy | Trường của các dòng mang mã đó |
|---|---|
| Trùng mã khác chiều cao | `qty`, `dims` |
| Khối lượng tịnh | `mass` |
| Đơn vị mm, khối lượng không đơn vị | `dims`, `mass` |
| Thiếu khối lượng | `dims`, `mass` (kích thước dòng đó cũng không ghi đơn vị) |
| Nhãn ảnh | `posture`, `stacking`, `fragile` |
| Pallet | `qty`, `dims` |

Test CI (`tests/scripts/test_eval.py`) dùng model giả trả bản đọc đúng của bộ probe: 8/8 bẫy, 0 giá trị tự bịa, 0 câu hỏi thừa; và một đáp án bị sửa thì runner báo đúng trường sai.

## 3. Cách chạy

```bash
pip install -r requirements-dev.txt
python -m scripts.gen_eval
python -m scripts.eval_agent            # cần GOOGLE_API_KEY; ghi data/eval/results-<model>.json
```

Mỗi bộ 2–3 lần gọi Gemini (một lần mỗi tài liệu). Tài liệu đọc lỗi được ghi riêng (`failed_documents`), không tính là đọc sai.

## 4. Kết quả agent

Một lượt, ngày 25/10/2026; `gemini-3.1-flash-lite`, thinking mặc định, temperature 0; 23 bộ ở §1, 58 tài liệu; tổng 135 s. Không tài liệu nào đọc lỗi.

| Chỉ số | Kết quả |
|---|---|
| Trường có tài liệu nêu | 525 |
| Trường đúng | 373 (71%) |
| Trường đưa ra hỏi | 152 (29%) |
| Trường sai | 0 |
| Giá trị tự bịa | 0 |
| Bẫy bắt được | 129 / 129 |
| Câu hỏi thừa | 0 (cả 2 bộ không bẫy: 0 chỗ hỏi về trường có tài liệu nêu) |
| Dòng thiếu / dòng thừa | 0 / 0 |

Theo loại bẫy (bắt được / số lần xuất hiện; bẫy khối lượng tịnh đếm theo từng mã): trùng mã khác chiều cao 13/13, khối lượng tịnh 52/52, đơn vị mm và khối lượng không đơn vị 12/12, thiếu khối lượng 14/14, nhãn ảnh 12/12, pallet 11/11, mã không giao 15/15.

**Đọc kết quả thế nào:**
- Điểm tuyệt đối cho thấy bộ eval **quá dễ để phân biệt**: biến thể cùng một khuôn với bộ probe, nơi luật ghép đã được chỉnh. Nó chứng minh pipeline không bịa giá trị và bắt đủ bảy loại bẫy trên dạng tài liệu này; không nói gì về packing list thật có bố cục khác, ảnh chụp mờ, PDF scan.
- Một lượt, nên chưa có độ dao động giữa các lần gọi.
- 29% trường được đưa ra hỏi là theo thiết kế (bẫy cài sẵn), không phải câu hỏi thừa.
- Chat không nằm trong eval này.

Muốn eval phân biệt hơn: thêm khuôn tài liệu khác (cột đảo thứ tự, gộp ô, PDF scan, ảnh nhãn nghiêng), và model khác để so.

## 5. Eval engine

Chưa làm.
