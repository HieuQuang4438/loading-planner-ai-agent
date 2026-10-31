---
status: approved
updated: 2026-10-26
owner: Hiếu
---

# Giao diện — luồng, hệ thiết kế và các màn

Giao diện của Loading AI Planner. Chốt qua một prototype tĩnh, rồi build hai đợt: lô, upload, bảng dữ liệu, chat; chạy, kết quả 3D, lịch sử. Chức năng và nguyên tắc nằm ở [brief.md](brief.md) (§2.1 agent, §2.2 hai chế độ, §2.3 nguyên tắc); file này chỉ ghi cách chúng hiện ra trên màn.

## Mục lục

| # | Mục |
|---|---|
| 1 | [Nguyên tắc](#1-nguyên-tắc) |
| 2 | [Hệ thiết kế](#2-hệ-thiết-kế) |
| 3 | [Khung màn của một lô](#3-khung-màn-của-một-lô) |
| 4 | [Xác nhận dữ liệu](#4-xác-nhận-dữ-liệu) |
| 5 | [Các màn](#5-các-màn) |
| 6 | [Màn dùng chung](#6-màn-dùng-chung) |

## 1. Nguyên tắc

- **Chỉ màn máy tính.** Kiểm ở 1366 × 768, 1440 × 900 và 1920 × 1080; không tối ưu cho điện thoại.
- **Tiếng Việt** cho mọi chữ trên màn. Tên file, mã hàng và giá trị gốc trích từ tài liệu giữ nguyên như trong tài liệu.
- **Mỗi bước một màn**, chuyển bằng hash trong URL; nút Back của trình duyệt đi qua các màn đã mở.
- **Không có giá trị nào vào engine mà người dùng chưa thấy.** Mọi trường cần xác nhận đều hiện trên màn, kèm nguồn; nút chạy bị khóa cho tới khi xác nhận đủ (brief §2.3).
- **Trợ lý và trang dùng chung một dữ liệu.** Việc làm được trong chat (xác nhận, đặt thiết lập, chạy) thì cũng làm được trên trang, và ngược lại; làm ở đâu thì chỗ kia cập nhật theo.
- **Màn của app không gắn nhãn "giả lập"** cạnh số. Tài liệu, số đo và lô mẫu vẫn ghi rõ là giả lập.

## 2. Hệ thiết kế

Hệ thiết kế nằm ở `src/web/static/shared/`: `style.css` (token trên `:root`), `icons.js` (Lucide nhúng sẵn), `util.js` (định dạng số), `linecolor.js` (màu của mã hàng). Component mới chỉ dùng token, không dùng mã màu trơn.

- **Style:** Minimalism và Swiss, mật độ cao. Nền `--bg`, thẻ trắng phẳng có viền, bo góc 6 px (4 px cho phần tử nhỏ). Chỉ giao diện sáng.
- **Màu:** một màu nhấn `--accent`. `--ok` cho đã xác nhận và đạt; `--warn` cho cần xác nhận và hàng còn lại; `--bad` cho lỗi.
- **Chữ:** Fira Sans, thang 12 / 14 / 16 / 20 px, số lớn 26 và 44 px.
- **Số:** dấu phẩy thập phân, khoảng trắng hẹp phân cách hàng nghìn, chữ số cùng bề rộng. Kích thước 2 chữ số (`0,60 m`); khối lượng một kiện 1 chữ số (`12,5 kg`); tổng khối lượng làm tròn tới kg; thể tích 1 chữ số (`73,0 m³`); **cước 2 chữ số** (`4 000,00 USD`).
- **Màu mã hàng:** suy ra từ mã (`linecolor.js`). Dùng chung cho dải màu ở bảng, chip, thẻ container và cảnh 3D.
- **Icon:** chỉ SVG nét mảnh Lucide, không emoji. Nút chỉ có icon phải có `aria-label`.
- **Trợ năng:** vòng focus 2 px. Trạng thái luôn có icon và chữ, không chỉ màu. Mỗi màn một `h1`; mở màn thì focus vào `h1` đó, vẽ lại một màn (sau mỗi thao tác, khi đang đọc tài liệu) thì focus về đúng nút cũ. Không đặt `aria-live` lên cả trang, chỉ lên toast, chat và lỗi. Mọi thứ mở bằng rê chuột cũng mở được bằng bấm và bàn phím; menu đóng khi bấm ra ngoài hoặc Esc. Thao tác kéo thả luôn có nút thay thế. Một dòng bảng mở được thứ gì đó (lô, lần xếp) thì trông như vậy: tên là link màu nhấn, cả dòng bấm được, rê chuột thì dòng đổi nền, cuối dòng có ›. Tôn trọng `prefers-reduced-motion`.

## 3. Khung màn của một lô

- **Thanh trên:** logo và tên app, mục "Lô hàng", nút tài khoản (menu chỉ có Đăng xuất).
- **Thanh công cụ của màn:** nút "Quay lại" (về phần cuối của breadcrumb), breadcrumb (`Lô hàng / <tên lô> / <màn>`, mỗi phần là link; ẩn khi chỉ có một phần, vì trùng nút Quay lại), tiêu đề `h1` (màn lô: kèm nút đổi tên và xóa lô), nhãn trạng thái, rồi các nút của màn ở bên phải. Nút chính (nền xanh) tối đa một nút. Nút bị khóa thì lý do ghi ngay cạnh nút.
- **Cột chat bên phải** rộng 380 px (320 px khi cửa sổ hẹp hơn 1440 px), có ở **mọi màn của một lô**. Cột này dính theo khi trang cuộn và có ô nhập riêng, dưới ô ghi "Enter gửi · Shift+Enter xuống dòng". Chữ đang gõ là nháp của lô: màn vẽ lại hay chuyển màn trong lô vẫn giữ (chỉ trong trang đang mở).
  - **Thu gọn** bằng nút ở đầu cột. Khi thu gọn, cột thành một dải 56 px chỉ còn nút mở lại, kèm số câu hỏi đang chờ.
  - Trình duyệt nhớ lựa chọn thu gọn (`localStorage`). Đọc hoặc ghi lỗi thì dùng mặc định là mở.
- **Tin nhắn trong chat:**
  - Lời chào theo lô: lô chưa có tài liệu thì chỉ cách nhập từng mã hàng hoặc thả tài liệu, không nói "đọc tài liệu".
  - Tin của trợ lý nền xám; tin của người dùng nền xanh nhạt, căn phải.
  - Câu hỏi cần xác nhận có viền trái màu `--warn` và các nút trả lời nhanh.
  - Hành động trợ lý đã làm (đọc file, chạy, kiểm tra) ghi thành một dòng nhỏ dưới tin.
  - Xác nhận đã ghi thì hiện "Xác nhận bởi <tên> lúc <giờ> · nguồn …".
  - Khi đang chờ có ba chấm; mỗi công cụ trợ lý chạy hiện ngay thành một dòng hành động (luồng sự kiện). Câu trả lời hiện cả câu một lần, không hiện dần từng chữ.
  - Câu trả lời trợ lý hiểu từ lời người dùng là **đề xuất**: hiện nút "Xác nhận Hk: …"; dữ liệu chỉ chốt khi người dùng bấm.
  - Thêm hoặc sửa dòng nói trong chat cũng là đề xuất: nút "Xác nhận Thêm SKU-AA: 3 thùng · 1,00 × 1,00 × 1,00 m · …" hoặc "Xác nhận Sửa SKU-A: …" ghi đủ giá trị đã đổi ra mét; bấm thì như dùng form của bảng.
  - Số trong câu trả lời không tìm thấy trong kết quả công cụ thì hiện cảnh báo "Số chưa kiểm được từ dữ liệu" dưới tin.

## 4. Xác nhận dữ liệu

Phần cốt lõi của sản phẩm, thực hiện brief §2.1 "Phát hiện và hỏi lại" và §2.3.

**Trạng thái của một trường** (mỗi ô trong bảng dữ liệu là một nút):

| Trạng thái | Hiện | Khi nào |
|---|---|---|
| `confirmed` | icon dấu tích, màu `--ok` | Người dùng đã xác nhận |
| `extracted` | icon tròn, màu xám | Trích từ tài liệu, các nguồn khớp nhau |
| `needs_review` | icon tam giác, nền `--warn-soft`, kèm **mã câu hỏi (H1, H2…)** | Thiếu, mâu thuẫn, đơn vị không rõ, giá trị suy ra (ví dụ ràng buộc đọc từ nhãn), hoặc không tài liệu nào ghi |

- **Bấm một ô** (hoặc Enter, Space) mở hộp nguồn. Hộp ghi trạng thái, giá trị đã chuẩn hóa, và từng nguồn gồm file, vị trí (sheet/dòng, trang, nhãn) và giá trị gốc trong ngoặc kép. Nguồn không ghi gì thì hiện "trống". Đóng bằng Esc hoặc bấm ra ngoài.
- **Trường không tài liệu nào ghi** (ví dụ tư thế, chồng) hiện "Chưa có" ở trạng thái `needs_review`. Sau khi xác nhận, ô mới hiện giá trị mặc định của engine. Các trường loại này của cả lô gom thành **một** câu hỏi, để xác nhận một lần.
- **Mã hàng bị loại khỏi lô** chỉ thành một câu hỏi khi các nguồn mâu thuẫn, ví dụ một nguồn ghi "Not in this shipment" còn nguồn khác vẫn liệt kê mã đó. Chỉ một nguồn nhắc tới và không mâu thuẫn thì loại mà không hỏi, nhưng vẫn hiện ở mục gấp "Không đưa vào lô" kèm lý do, nguồn và nút "Đưa vào lô".

**Panel "Câu hỏi"** nằm trên bảng dữ liệu khi còn câu hỏi chưa trả lời.
- **Trái:** danh sách mọi câu hỏi theo thứ tự trang. Mỗi câu hỏi có mã (H + số), tiêu đề và một dòng tóm tắt. Đầu danh sách có tiến độ "n / tổng xong" và một thanh mảnh. Chỗ đang xử lý được đánh dấu.
- **Phải:** câu hỏi đang xử lý, gồm mã, tiêu đề, câu hỏi, rồi các lựa chọn dạng radio. Mỗi lựa chọn có giá trị và nguồn của nó. Luôn có lựa chọn "Giá trị khác" để nhập tay: một bảng nhỏ, mỗi mã một dòng, mỗi trường được hỏi một cột, ô câu hỏi không hỏi thì "—"; ô số tầng chỉ hiện khi chọn "Tối đa n tầng"; nhập vào bảng thì tự chọn "Giá trị khác". Lựa chọn còn để trống trường nào (ví dụ khối lượng một pallet mà không tài liệu nào ghi) thì có ô nhập trường đó ngay trong lựa chọn; bấm xác nhận mà để trống thì báo bằng chữ, như "Còn thiếu khối lượng của SKU-D".
- **Nút:** "Xác nhận và sang Hk", "Để sau", và ‹ › để chuyển giữa các câu hỏi.
- **Chat hỏi cùng câu hỏi, cùng các lựa chọn.** Trả lời ở chat hay ở panel thì kết quả như nhau.
- **Xác nhận đủ** thì panel thay bằng một dải xanh "Dữ liệu lô đã xác nhận", kèm tổng dòng, kiện, kg và m³. Nút "Xếp lô hàng" mở.

## 5. Các màn

| Hash | Màn | Nội dung |
|---|---|---|
| `#/lo-hang` | Lô hàng | Bảng lô của tài khoản, mới nhất trước: tên lô (link), số tài liệu, trạng thái dữ liệu ("n câu hỏi" hoặc "Đã xác nhận"), lần chạy gần nhất (cách xếp, rồi cước, hoặc "a / b kiện" khi xếp vào container có sẵn, rồi các container), giờ cập nhật. Ô tìm theo tên; không khớp thì ghi "Không có lô nào khớp". Nút chính "Lô mới" |
| `#/lo/moi` | Lô mới | Ô tên lô. Vùng thả lớn nhận nhiều file một lúc (Excel, CSV, PDF, ảnh), kèm nút "Chọn file", dưới đó vạch "hoặc" và nút "Nhập tay từng mã hàng" (tạo lô, sang màn lô và mở form "Thêm dòng"). Dưới là ba bước Đọc, Đối chiếu, Chạy, mỗi bước một câu. Thả file thì hiện "Đang tải lên n tệp…" và các nút chọn file khóa tới khi gửi xong (cả ở màn lô). "Xếp lô hàng" khóa, lý do "Thêm tài liệu thì mới chạy được". Chat chào và nói việc sẽ làm |
| `#/lo/<id>` khi đang đọc | Đang đọc tài liệu | Dải tài liệu: mỗi file có trạng thái Chờ / thanh tiến độ (ví dụ "Trang 2 / 2") / Đã đọc. Bảng dữ liệu là khung xám chờ (`.sk`), `aria-busy`. Chat báo từng file đã đọc được gì và đang đọc file nào. "Xếp lô hàng" khóa, lý do "Đang đọc tài liệu" |
| `#/lo/<id>` | Lô | Từ trên xuống: **dải tài liệu** (mỗi file có icon theo loại, tên, loại và quy mô như "Excel · 5 dòng hàng", trạng thái đọc, nút xóa (hỏi xác nhận, khóa khi còn tệp đang đọc; dữ liệu lấy từ tệp đó bị bỏ, câu trả lời dựa trên nó được hỏi lại); cuối dải là nút "Thêm tài liệu", và kéo file vào bất kỳ đâu trên màn cũng thêm được); **panel Câu hỏi** hoặc dải đã xác nhận (§4); **bảng Dữ liệu lô** (mỗi dòng có nút sửa và bỏ; form loại kiện: mã và số lượng có nút −/+, kích thước, khối lượng mỗi kiện hoặc tất cả, tư thế, chồng, dễ vỡ bằng nút chọn, hình hộp đúng tỉ lệ bên phải, "Lưu và thêm dòng khác"; form khóa trường đang ở câu hỏi, mã và mô tả của dòng từ tài liệu; dưới bảng là nút "Thêm dòng", dòng tự thêm ghi "người dùng nhập"); lô chưa có dòng thì ô trống có hai nút "Chọn file" và "Thêm dòng"; mục gấp **Không đưa vào lô** (dòng người dùng đã bỏ có nút "Đưa lại vào lô"); dưới cùng là **Các lần xếp** (khi đã có: lần, cách xếp, kết quả, lúc; 3 lần gần nhất, nút "Xem tất cả n lần"; mỗi lần mở lại màn kết quả của nó, kể cả lần của bản thử). Thanh công cụ: nhãn trạng thái và nút "Xếp lô hàng" |
| `#/lo/<id>/chay` | Xếp lô hàng | Hai thẻ chọn cách xếp (radio thật: Tab vào, mũi tên đổi): **Chọn container rẻ nhất** (chế độ A), **Xếp vào container có sẵn** (chế độ B), mỗi thẻ một câu mô tả từ brief §2.2. Bên phải là thẻ tóm tắt lô (dòng, kiện, khối lượng, thể tích, trạng thái dữ liệu), dính theo khi cuộn; dưới đó là thẻ Thời gian chạy (1 / 2 / 5 phút: mỗi mức một chữ nhỏ "mặc định", "kỹ hơn", "lô lớn"; ô thứ tư "Khác…" mở ô số giây, 10–600 giây (`SERVICE.time_range`), sai thì tô đỏ ô và báo dưới nút; dưới là "Thường xong trong khoảng …" theo mức đang chọn; nút "Xếp lô hàng"); dưới cùng là thẻ **Thiết lập nâng cao**: gấp mặc định, khi gấp có một dòng "khe hở 0,05 m · đỡ 80% · chủ động lật"; mở ra có "Cho bộ giải chủ động lật kiện" (bật sẵn, khóa khi không mã nào được lật), δ (m) và α, mỗi ô có ⓘ và một dòng giải thích; giá trị sai thì tô đỏ ô, mở thẻ và báo dưới nút. Màn Kết quả tính baseline và cận dưới với δ, α của lần chạy; So sánh ghi δ, α ở "Đầu vào khác nhau" khi hai lần khác nhau. Phần giữa đổi theo chế độ, xem dưới bảng |
| `#/lo/<id>/ket-qua/<run>` | Kết quả | Thanh công cụ: lần chạy ("Lần n · giờ"; có nhiều lần cùng cách xếp thì là ô chọn, mỗi dòng kèm cước hoặc số kiện), "So sánh" (với một lần cùng cách xếp) và "Xuất" (nút chính, menu). Trong lúc giải là thẻ đang giải (§6). **Bốn ô số**, ô đầu rộng 1,5 phần: xem dưới bảng. **Lưới thẻ container** (số tự thêm cột theo bề rộng; mỗi thẻ có ảnh 3D, loại, cước hoặc "có sẵn", số kiện, thanh thể tích và khối lượng, chip mã hàng; bấm mở màn một container). **Bảng theo mã hàng**: xem dưới bảng |
| `#/lo/<id>/so-sanh/<run>/<run>` | So sánh | Chỉ so hai lần **cùng cách xếp**: thanh công cụ có hai ô chọn lần chạy, mỗi ô liệt kê các lần cùng cách xếp; hai lần khác cách xếp thì báo không so được. Thẻ **Đầu vào khác nhau** (liệt kê thay đổi, ghi nguồn của thay đổi, ví dụ "theo yêu cầu trong chat lúc 14:44", và những gì giữ nguyên). **Bảng chỉ số** (tổng cước, container, số kiện, thể tích dùng, khối lượng, kiểm tra ràng buộc; xếp vào container có sẵn thì dòng đầu là hàng đã xếp "a / b kiện", không có cước và số kiện, và Đầu vào khác nhau ghi container có sẵn, thứ tự ưu tiên, cho xếp một phần) với một cột cho mỗi lần chạy ("Lần n") và một cột **Chênh lệch**. Dưới là **hai cột**, mỗi cột một lần chạy, có tiêu đề kèm cước (hoặc số kiện) và số container, và lưới thẻ container của lần đó |

**Bảng Dữ liệu lô.** Mỗi dòng có dải màu của mã hàng, mã và mô tả, số lượng kèm đơn vị kiện (thùng, pallet), dài × rộng × cao (m), khối lượng một kiện cả bì (kg), tư thế và chồng. Cùng một mã có nhiều dòng thì giữ nhiều dòng. Đầu bảng có chú giải ba trạng thái và mã câu hỏi (H1, H2…). Dưới bảng ghi: đơn vị đã đổi về m và kg, giá trị gốc nằm ở nguồn.

Mỗi điều trợ lý cần người dùng chốt gọi là **câu hỏi**, mã **H + số** (H1, H2…; không dùng `#`, đã là số container). Mã hiện thành chip cam ở ô bảng, panel, nút và trong chữ của trợ lý; chip trong chat bấm được, mở đúng câu hỏi. Giao diện và chat gọi packing list là "bảng kê hàng", spec là "thông số kỹ thuật" (màn Lô mới ghi kèm chữ gốc trong ngoặc); tên file và chữ trích từ tài liệu giữ nguyên. Giao diện và chat không dùng chữ "chế độ A/B", chỉ hai tên trên; A/B là tên trong code và tài liệu kỹ thuật. Cũng vậy: baseline là "cách xếp đơn giản", cận dưới là "mức thấp nhất có thể", checker là "bộ kiểm tra độc lập", bản what-if là "bản thử"; một lần chạy là "Lần n", số thứ tự trong họ lô, lần đầu là 1.

**Thiết lập theo chế độ** (màn Xếp lô hàng):
- **Chế độ A:** thẻ **Bảng cước**, mỗi loại container một dòng gồm ô dùng/không dùng, kích thước trong, tải tối đa và ô cước sửa được. Có nút "Nhập từ file cước"; dưới bảng ghi nguồn của bảng cước, và ghi rằng bộ giải không tự đặt giá.
- **Chế độ B:** thẻ **Container có sẵn**, mỗi loại một ô số lượng có nút − và +. Thẻ **Thứ tự ưu tiên** liệt kê mã hàng theo hạng; mỗi dòng có nút lên/xuống (không kéo thả). Ô chọn "Cho xếp một phần mã hàng".

**Bốn ô số ở màn Kết quả:**
- **Chế độ A:** Tổng cước; Container (số lượng, kèm đội như "1 × 40HC, 1 × 20GP"); So với cách xếp đơn giản (chênh lệch cước; dưới là đội và cước của cách đó, rồi mức thấp nhất có thể; ⓘ cạnh nhãn giải thích hai số đó); Kiểm tra ràng buộc (Đạt hoặc số vi phạm, ghi "bộ kiểm tra độc lập"). Chênh lệch bằng 0 không tô màu.
- **Chế độ B:** ô đầu là Hàng đã xếp "a / b kiện"; ô So với cách xếp đơn giản là chênh lệch số kiện so với cách lấp lần lượt theo thứ tự ưu tiên. Hai ô còn lại như chế độ A.
- Cách xếp đơn giản và mức thấp nhất tính trên lô **lúc chạy**, không phải lô hiện tại. Lô đã đổi sau lần chạy (dòng hàng hoặc bảng cước) thì trên các ô hiện dòng cảnh báo "Dữ liệu lô đã đổi sau lần chạy này; xếp lại để có phương án theo dữ liệu mới" kèm nút "Xếp lại".

**Bảng theo mã hàng ở màn Kết quả:**
- **Chế độ A:** mỗi mã nằm ở container nào, bao nhiêu kiện, và các ràng buộc.
- **Chế độ B:** ưu tiên, đã xếp / tổng, còn lại, lý do. Dòng còn hàng tô `--warn-soft`; đầu bảng có nhãn "Còn lại n kiện".

**What-if.** Người dùng hỏi trong chat ("nếu bỏ SKU-D thì sao?"). Trợ lý tạo một bản lô mới, giao diện gọi là **bản thử** (lô gốc giữ nguyên; thay đổi ghi nguồn "yêu cầu trong chat lúc hh:mm", số lượng mới phải được xác nhận), người dùng mở bản đó và chạy, rồi so sánh hai lần chạy. Màn So sánh chỉ so các lần chạy trong cùng họ lô (lô gốc và các bản what-if).

**Bản build lệch prototype ở:**
- **Đang đọc:** mỗi tài liệu có trạng thái Chờ / Đang đọc / Đã đọc / Lỗi, không có tiến độ theo trang, vì mỗi tài liệu là một lần gọi Gemini.
- **Thẻ container** ở màn Kết quả và So sánh: thẻ do app vẽ (loại, cước, số kiện, khối lượng, thanh thể tích và khối lượng, chip mã hàng), ảnh 3D từ viewer (`grid.js` `drawThumbInto`). Bấm thẻ mở màn một container `#/lo/<id>/ket-qua/<run>/c/<n>` ngay trong app (bản đầu mở trang `/viewer` ở tab mới, đã bỏ). Màn đó là màn một container dựng một lần trong `#scr-view` của `index.html`: thanh công cụ có "Quay lại" (về Kết quả), "Ẩn panel", "Trước i/n Sau"; ←/→ đổi container, Esc về Kết quả; không có cột chat. Không dùng: lưới container, ô số và bảng loại kiện của trang kết quả viewer (màn Kết quả của app đã có).
- **Chế độ B:** thẻ Container có sẵn là bảng, mỗi loại một dòng có nút − và +. Bảng ở màn Kết quả không có nhãn màu `--warn-soft` ở đầu bảng; số còn lại ghi bằng chữ. Thẻ container ghi "có sẵn" thay cho cước; màn một container vẫn hiện cước.
- **Xuất:** kế hoạch xếp (CSV, mỗi kiện một dòng theo thứ tự xếp) và phương án (JSON).
- **Bảng cước** chưa có nút "Nhập từ file cước"; cước sửa ngay trong bảng.

## 6. Màn dùng chung

Các màn sau dùng khuôn có sẵn của hệ thiết kế, chỉ đổi chữ cho đúng sản phẩm này:
- đăng nhập;
- đang giải: thẻ đồng hồ lớn ("0:12 / 1:00", lúc chờ thì thứ trong hàng đợi), hình container xếp dần (`fillart.js`, chỉ trang trí, không phải tiến độ), thanh tiến độ, một câu về việc bộ giải đang làm, nút Dừng, và ghi rằng rời màn thì lần chạy vẫn tiếp tục (bản đầu chỉ có dòng chữ và thanh);
- giải không ra (bản build: khung lỗi kèm link "Sửa thiết lập rồi chạy lại");
- một container 3D (cảnh, tua từng kiện, danh sách kiện), ở `#/lo/<id>/ket-qua/<run>/c/<n>`;
- hộp xác nhận xóa kèm Hoàn tác;
- khung lỗi `.alert.bad`.

Lỗi khi đọc tài liệu (file hỏng, ảnh không đọc được, Gemini quá tải) hiện bằng khung lỗi đó, đặt ngay trên dải tài liệu, nêu tên file và việc nên làm. Câu lỗi là tiếng Việt ("Gemini đang quá tải, thử lại sau ít phút"), không có nguyên văn trả về của model; thẻ tài liệu lỗi có nút "Đọc lại". Lô chưa có dòng mà có tài liệu lỗi, hoặc chưa có bảng kê hàng, thì ô trống nói rõ lý do; chưa đọc được bảng kê hàng thì không mã nào bị đưa vào "Không đưa vào lô".
