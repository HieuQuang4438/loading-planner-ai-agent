---
status: approved
updated: 2026-10-25
owner: Hiếu
---

# ADR-0002: Chế độ B: tối đa hàng theo thứ tự ưu tiên trên kho cột của E5

## Status
Approved by Hiếu on 2026-10-25.

## Context
Brief §2.2: chế độ B cố định danh sách container có sẵn, xếp nhiều hàng nhất theo thứ tự ưu tiên người dùng đặt, phân hàng giữa các container có tối ưu (không lấp lần lượt), báo hàng còn lại. `ux.md` §4 đã chốt màn: số container mỗi loại, thứ tự ưu tiên sắp bằng nút lên/xuống, ô "Cho xếp một phần mã hàng". Engine lúc đó chỉ có chế độ A (E5: set cover tối thiểu cước). Checker kiểm ràng buộc 2 "mỗi kiện của lô nằm trong đúng một container", mà phương án B để lại kiện.

## Decision
Engine mới `e5-fill` (`src/engines/fill.py`; `e5-fill-orient` thêm lõi thử mọi tư thế), dùng lại lõi E1, E2 và kho cột của E5, đổi bài chính:

```
max  theo thứ tự từ điển (y_1, …, y_n)   (dòng 1 là dòng ưu tiên nhất)
s.t. y_i = Σ_p a_ip x_p ≤ qty_i          (mọi dòng i)
     Σ_{p loại t} x_p ≤ n_t              (số container có sẵn loại t)
     x_p nguyên ≥ 0
```

- **Mục tiêu theo thứ tự từ điển:** tối đa số kiện dòng ưu tiên 1, giữ số đó rồi tối đa dòng 2, và tiếp tục. Mỗi vị trí ưu tiên là một dòng nên đếm kiện cũng là đo thể tích.
- **Không cho xếp một phần** (ô chọn tắt): `y_i ∈ {0, qty_i}`.
- **Bài chính đóng gói (`≤ qty`), không phủ:** không có kiện thừa nên mỗi container giữ nguyên cách xếp lõi đã làm; không cần bước bỏ kiện thừa.
- **Trọng số:** một bài SCIP với trọng số `Π (qty_j + 1)` của các dòng sau. Khi tích vượt `1e9`, dòng được chia thành nhiều bài nối tiếp, bài sau giữ số kiện bài trước đạt (lệch đề xuất "giới hạn 15 dòng": với `qty` cỡ trăm, 15 dòng đã vượt độ chính xác của số thực).
- **Cột:** lời giải baseline của mỗi lõi; lõi chạy trên tập dòng xếp theo đối ngẫu LP (giá trị mỗi kiện giảm theo thứ tự ưu tiên, chỉ để dẫn hướng); tập con ngẫu nhiên theo thứ tự ưu tiên với số lượng ngẫu nhiên. 60% thời gian sinh cột, phần còn lại cho bài chính.
- **Baseline:** đưa kiện theo thứ tự ưu tiên, lấp container lần lượt bằng lõi E1 (`fill.sequential`). Cột baseline luôn trong kho và là gợi ý của SCIP, nên kết quả không kém baseline theo thứ tự từ điển.
- **Checker giữ nguyên:** phương án B được chấm trên lô con gồm đúng các kiện đã xếp (`qty` = số đã xếp; `fill.placed_instance`). Job kiểm thêm số container mỗi loại không vượt số có sẵn.
- Thiết lập của lần chạy đi trong `instance.meta["fill"]` (`fleet`, `priority`, `partial`), nên run lưu lại được xem lại và chấm lại như run chế độ A.

Không chọn:
- Trọng số thể tích giảm dần theo thứ tự ưu tiên. Xếp được nhiều hơn, nhưng một kiện ưu tiên cao có thể bị đổi lấy nhiều kiện ưu tiên thấp.
- Tối đa khối lượng hoặc giá trị. Lô không có trường giá trị.
- Thêm chế độ cho checker chấp nhận kiện không xếp. Phải sửa ràng buộc 2 của trọng tài.
- Giải lần lượt từng dòng. Ổn định số học nhưng chia thời gian cho n lần gọi SCIP; chỉ dùng khi trọng số vượt ngưỡng.

## Consequences
- "Tối đa" chỉ đúng trên kho cột đã sinh; lõi tham lam nên không phải tối ưu chứng minh được.
- Đo ngày 25/10/2026 (lô probe, giả lập; 10–20 s, seed 1, δ 0,05, α 0,8; nhiều bộ container và cả hai trạng thái ô chọn): kết quả **bằng** baseline mọi lần, chưa thấy lần nào hơn. Số đo đầy đủ để sau.
- Viewer 3D vẫn hiện cước của từng container ở chế độ B.
