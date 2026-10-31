---
status: draft
updated: 2026-10-25
owner: Hiếu
---

# Ràng buộc của một phương án xếp

Những gì checker (`src/checker.py`) kiểm trên mọi phương án trước khi hiện. Checker độc lập với code giải: không import engine nào, và không bao giờ được nới để một phương án qua. Số hiệu ràng buộc dùng chung với code (`Violation.constraint`) và viewer.

## 1. Chín ràng buộc

| # | Ràng buộc | Nội dung |
|---|---|---|
| 1 | Tư thế và loại container | Mỗi kiện đặt đúng một tư thế được phép; mỗi container dùng đúng một loại có trong bảng |
| 2 | Gán kiện | Mỗi kiện của lô nằm trong đúng một container |
| 3 | Container đã mở | Kiện chỉ nằm trong container có trong lời giải |
| 4 | Nằm trong container | Kiện nằm trọn trong lòng container; được chạm vách |
| 5 | Không va chạm | Hai kiện cùng container không giao nhau; đứng cạnh nhau theo phương ngang thì cách ít nhất `δ` |
| 6 | Tải trọng container | Tổng khối lượng kiện trong một container ≤ tải tối đa của loại đó |
| 7 | Đỡ | Kiện nằm trên sàn, hoặc phần đáy được mặt trên các kiện bên dưới đỡ ≥ `α` × diện tích đáy |
| 8 | Sức chịu chồng | Tải đè lên một kiện ≤ `load` của nó, và số tầng của mọi chồng đi qua kiện ≤ `tiers` của nó |
| 9 | Qua cửa | Kiện, ở tư thế đã đặt, đưa vào được qua cửa container |

Ràng buộc 8 là chỗ bài toán khác xếp hộp thuần: một phương án đúng hình học vẫn sai nếu kiện nặng nằm trên kiện yếu.

## 2. Tham số

| Tham số | Nghĩa | Giá trị trong bản này |
|---|---|---|
| `δ` | Khe hở tối thiểu giữa hai kiện đứng cạnh nhau, cho xe nâng và tay người; không áp với vách, không áp theo phương đứng | 0,05 m |
| `α` | Tỉ lệ đáy tối thiểu phải được đỡ; 1 là đỡ trọn, 0,8 cho nhô 20% | 0,8 |

Hai số này là lựa chọn mô hình, không phải dữ liệu nhà máy, và chưa có căn cứ ngành; mọi số đo ghi kèm chúng.

## 3. Tư thế

Mã tư thế cho biết cạnh nào của kiện nằm theo `x`, `y`, `z`: `LWH` là đặt như liệt kê, `WLH` là xoay 90° quanh trục đứng; `LHW`, `HLW`, `WHL`, `HWL` là lật. Kiện `upright` chỉ có `LWH`, `WLH`; kiện `tippable` có cả sáu. Kiện lật giữ nguyên `tiers` và `load` như khi đứng (giả định, chưa có dữ liệu riêng).

## 4. Cách đổi từ lô

Lô của sản phẩm đổi sang các tham số trên ở `to_instance` ([engine/README.md](../product/engine/README.md) §1): `stacking: none` thành `tiers = 1, load = 0` (không gì được đè lên); `limited n` thành `tiers = n`; `free` thành không giới hạn. `fragile` không thành ràng buộc nào: người dùng thể hiện nó qua tư thế và chồng.
