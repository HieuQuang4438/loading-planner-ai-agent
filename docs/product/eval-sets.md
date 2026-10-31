---
status: living
updated: 2026-10-26
owner: Hiếu
---

# Từng bộ eval agent

Sinh bằng `python -m scripts.gen_eval --doc` từ cùng danh sách bộ và cùng seed với `data/eval/`; **không sửa tay** (test so file này với script). Mọi giá trị là **giả lập**. Bộ eval là gì, chỉ số, kết quả: [eval.md](eval.md). Hành vi đúng với từng bẫy: [`data/probe/README.md`](../../data/probe/README.md).

Giá trị trong bảng là **giá trị thật** (đáp án), không phải giá trị tài liệu ghi: bẫy làm tài liệu ghi khác (mm, khối lượng tịnh, thiếu khối lượng, chiều cao sai ở dòng trùng mã). Cột "Tài liệu nêu" là các trường có tài liệu nào đó nêu; trường còn lại phải hỏi.

## Tổng quan

| Bộ | Seed | Dòng | Bẫy (mã) | Ảnh nhãn |
|---|---|---|---|---|
| [`set-00`](#set-00) | probe | 5 | trùng mã khác chiều cao (SKU-A); khối lượng tịnh (SKU-A, SKU-B); mm, khối lượng không đơn vị (SKU-B); thiếu khối lượng (SKU-C); nhãn ảnh (SKU-C); pallet (SKU-D); mã không giao (SKU-E) | `handling_label_sku_c.png` |
| [`set-01`](#set-01) | 1 | 5 | khối lượng tịnh (SKU-A, SKU-B, SKU-C, SKU-D, SKU-E); mã không giao (SKU-F) | — |
| [`set-02`](#set-02) | 2 | 6 | trùng mã khác chiều cao (SKU-D); khối lượng tịnh (SKU-B, SKU-D, SKU-E); thiếu khối lượng (SKU-A); nhãn ảnh (SKU-B); pallet (SKU-C); mã không giao (SKU-F) | `handling_label_sku_b.png` |
| [`set-03`](#set-03) | 3 | 5 | khối lượng tịnh (SKU-A, SKU-B, SKU-C, SKU-D); mm, khối lượng không đơn vị (SKU-B); thiếu khối lượng (SKU-E); nhãn ảnh (SKU-D); mã không giao (SKU-F) | `handling_label_sku_d.png` |
| [`set-04`](#set-04) | 4 | 6 | trùng mã khác chiều cao (SKU-B); khối lượng tịnh (SKU-A, SKU-B, SKU-C, SKU-E); nhãn ảnh (SKU-C); pallet (SKU-D); mã không giao (SKU-F) | `handling_label_sku_c.png` |
| [`set-05`](#set-05) | 5 | 5 | mm, khối lượng không đơn vị (SKU-E); thiếu khối lượng (SKU-C); nhãn ảnh (SKU-D); pallet (SKU-A); mã không giao (SKU-F) | `handling_label_sku_d.png` |
| [`set-06`](#set-06) | 6 | 6 | trùng mã khác chiều cao (SKU-E); khối lượng tịnh (SKU-B, SKU-C, SKU-D, SKU-E); thiếu khối lượng (SKU-A); mã không giao (SKU-F) | — |
| [`set-07`](#set-07) | 7 | 5 | nhãn ảnh (SKU-B); mã không giao (SKU-F) | `handling_label_sku_b.png` |
| [`set-08`](#set-08) | 8 | 6 | trùng mã khác chiều cao (SKU-A); mm, khối lượng không đơn vị (SKU-B); thiếu khối lượng (SKU-E); nhãn ảnh (SKU-D); pallet (SKU-C); mã không giao (SKU-F) | `handling_label_sku_d.png` |
| [`set-09`](#set-09) | 9 | 6 | trùng mã khác chiều cao (SKU-D); thiếu khối lượng (SKU-E); mã không giao (SKU-F) | — |
| [`set-10`](#set-10) | 10 | 6 | trùng mã khác chiều cao (SKU-D); khối lượng tịnh (SKU-A, SKU-B, SKU-D); mm, khối lượng không đơn vị (SKU-B); thiếu khối lượng (SKU-E); nhãn ảnh (SKU-A); pallet (SKU-C); mã không giao (SKU-F) | `handling_label_sku_a.png` |
| [`set-11`](#set-11) | 11 | 6 | trùng mã khác chiều cao (SKU-D); khối lượng tịnh (SKU-A, SKU-B, SKU-D, SKU-E); mm, khối lượng không đơn vị (SKU-B); thiếu khối lượng (SKU-C) | — |
| [`set-12`](#set-12) | 12 | 5 | khối lượng tịnh (SKU-A, SKU-D, SKU-E); thiếu khối lượng (SKU-C); pallet (SKU-B); mã không giao (SKU-F) | — |
| [`set-13`](#set-13) | 13 | 6 | trùng mã khác chiều cao (SKU-C); khối lượng tịnh (SKU-A, SKU-B, SKU-C, SKU-D, SKU-E); mm, khối lượng không đơn vị (SKU-B); nhãn ảnh (SKU-E); mã không giao (SKU-F) | `handling_label_sku_e.png` |
| [`set-14`](#set-14) | 14 | 6 | trùng mã khác chiều cao (SKU-D); khối lượng tịnh (SKU-A, SKU-C, SKU-D, SKU-E); mm, khối lượng không đơn vị (SKU-E); nhãn ảnh (SKU-C); pallet (SKU-B); mã không giao (SKU-F) | `handling_label_sku_c.png` |
| [`set-15`](#set-15) | 15 | 5 | mm, khối lượng không đơn vị (SKU-C); mã không giao (SKU-F) | — |
| [`set-16`](#set-16) | 16 | 5 | mm, khối lượng không đơn vị (SKU-C); thiếu khối lượng (SKU-A); nhãn ảnh (SKU-B); pallet (SKU-E) | `handling_label_sku_b.png` |
| [`set-17`](#set-17) | 17 | 6 | trùng mã khác chiều cao (SKU-C); khối lượng tịnh (SKU-A, SKU-C, SKU-E); thiếu khối lượng (SKU-D); nhãn ảnh (SKU-E); pallet (SKU-B) | `handling_label_sku_e.png` |
| [`set-18`](#set-18) | 18 | 6 | trùng mã khác chiều cao (SKU-B); khối lượng tịnh (SKU-A, SKU-B, SKU-D); mm, khối lượng không đơn vị (SKU-A); thiếu khối lượng (SKU-C); pallet (SKU-E) | — |
| [`set-19`](#set-19) | 19 | 5 | khối lượng tịnh (SKU-A, SKU-B, SKU-C, SKU-D, SKU-E); mm, khối lượng không đơn vị (SKU-A) | — |
| [`set-20`](#set-20) | 20 | 6 | trùng mã khác chiều cao (SKU-B); thiếu khối lượng (SKU-C) | — |
| [`clean-21`](#clean-21) | 21 | 5 | không | — |
| [`clean-22`](#clean-22) | 22 | 5 | không | — |

## set-00

Lô xuất T11 — điện gia dụng, hóa đơn INV-2026-118.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Quạt đứng FS-40 | thùng | 200 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-B` | Nồi cơm điện RC-18 | thùng | 80 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-C` | Bộ ly thủy tinh GL-06 | thùng | 50 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-D` | Máy xay sinh tố BL-02 | pallet | 10 | 1.2 × 1 × 1.5 | 160 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-A-2` | Quạt đứng FS-40 | thùng | 40 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-E` Ấm siêu tốc KT-17.

## set-01

Lô eval 1, hóa đơn INV-2026-632.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Bộ ly thủy tinh GL-67 | thùng | 41 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-B` | Đèn bàn LED LE-58 | thùng | 43 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-C` | Nồi cơm điện RI-22 | thùng | 34 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-D` | Ấm siêu tốc EL-59 | thùng | 225 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Máy hút bụi VA-10 | thùng | 140 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |

Không giao (chỉ spec nhắc): `SKU-F` Máy xay sinh tố BL-44.

## set-02

Lô eval 2, hóa đơn INV-2026-738.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Quạt đứng ST-95 | thùng | 216 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-B` | Nồi cơm điện RI-42 | thùng | 268 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-C` | Máy hút bụi VA-87 | pallet | 9 | 1.2 × 1 × 2.25 | 367 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-D` | Lò vi sóng MI-97 | thùng | 224 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-E` | Bộ ly thủy tinh GL-65 | thùng | 246 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-D-2` | Lò vi sóng MI-97 | thùng | 37 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Bộ nồi inox ST-75.

## set-03

Lô eval 3, hóa đơn INV-2026-976.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy xay sinh tố BL-70 | thùng | 297 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-B` | Đèn bàn LED LE-18 | thùng | 229 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-C` | Bộ nồi inox ST-70 | thùng | 37 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Bộ ly thủy tinh GL-39 | thùng | 62 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-E` | Lò vi sóng MI-70 | thùng | 111 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Ấm siêu tốc EL-80.

## set-04

Lô eval 4, hóa đơn INV-2026-842.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy xay sinh tố BL-21 | thùng | 169 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-B` | Ấm siêu tốc EL-61 | thùng | 129 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-C` | Nồi cơm điện RI-47 | thùng | 114 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-D` | Bàn ủi hơi nước ST-17 | pallet | 8 | 1.2 × 1 × 1.9 | 91 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-E` | Máy lọc không khí AI-78 | thùng | 178 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-B-2` | Ấm siêu tốc EL-61 | thùng | 21 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |

Không giao (chỉ spec nhắc): `SKU-F` Đèn bàn LED LE-32.

## set-05

Lô eval 5, hóa đơn INV-2026-329.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Đèn bàn LED LE-69 | pallet | 10 | 1.2 × 1 × 1.55 | 92 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-B` | Ấm siêu tốc EL-41 | thùng | 111 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-C` | Lò vi sóng MI-30 | thùng | 66 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-D` | Bộ nồi inox ST-70 | thùng | 101 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-E` | Quạt đứng ST-58 | thùng | 257 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Bàn ủi hơi nước ST-83.

## set-06

Lô eval 6, hóa đơn INV-2026-619.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Đèn bàn LED LE-28 | thùng | 75 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-B` | Nồi cơm điện RI-70 | thùng | 247 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-C` | Máy lọc không khí AI-57 | thùng | 201 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-D` | Ấm siêu tốc EL-12 | thùng | 77 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Quạt đứng ST-35 | thùng | 215 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-E-2` | Quạt đứng ST-35 | thùng | 35 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Bình giữ nhiệt VA-62.

## set-07

Lô eval 7, hóa đơn INV-2026-496.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Lò vi sóng MI-78 | thùng | 233 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-B` | Bộ ly thủy tinh GL-84 | thùng | 55 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-C` | Bàn ủi hơi nước ST-74 | thùng | 143 | 0.35 × 0.2 × 0.2 | 2.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-D` | Quạt đứng ST-21 | thùng | 53 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-E` | Nồi cơm điện RI-18 | thùng | 98 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |

Không giao (chỉ spec nhắc): `SKU-F` Đèn bàn LED LE-80.

## set-08

Lô eval 8, hóa đơn INV-2026-588.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy xay sinh tố BL-15 | thùng | 40 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-B` | Lò vi sóng MI-41 | thùng | 166 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-C` | Bàn ủi hơi nước ST-74 | pallet | 12 | 1.2 × 1 × 2.25 | 104 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-D` | Bộ ly thủy tinh GL-92 | thùng | 238 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-E` | Bình giữ nhiệt VA-72 | thùng | 272 | 0.4 × 0.3 × 0.3 | 7 | tùy | 8 tầng | không | dims, mass, qty, stacking |
| `SKU-A-2` | Máy xay sinh tố BL-15 | thùng | 10 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |

Không giao (chỉ spec nhắc): `SKU-F` Máy hút bụi VA-73.

## set-09

Lô eval 9, hóa đơn INV-2026-804.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy lọc không khí AI-96 | thùng | 151 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-B` | Đèn bàn LED LE-74 | thùng | 56 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-C` | Lò vi sóng MI-87 | thùng | 86 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-D` | Ấm siêu tốc EL-80 | thùng | 97 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Bộ ly thủy tinh GL-99 | thùng | 289 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-D-2` | Ấm siêu tốc EL-80 | thùng | 16 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |

Không giao (chỉ spec nhắc): `SKU-F` Nồi cơm điện RI-58.

## set-10

Lô eval 10, hóa đơn INV-2026-877.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Đèn bàn LED LE-69 | thùng | 175 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-B` | Quạt đứng ST-45 | thùng | 164 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-C` | Bàn ủi hơi nước ST-30 | pallet | 11 | 1.2 × 1 × 1.55 | 78 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-D` | Máy lọc không khí AI-72 | thùng | 119 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-E` | Máy hút bụi VA-41 | thùng | 185 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |
| `SKU-D-2` | Máy lọc không khí AI-72 | thùng | 19 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Nồi cơm điện RI-56.

## set-11

Lô eval 11, hóa đơn INV-2026-447.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy lọc không khí AI-75 | thùng | 300 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-B` | Bộ nồi inox ST-88 | thùng | 62 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-C` | Bình giữ nhiệt VA-22 | thùng | 60 | 0.4 × 0.3 × 0.3 | 7 | tùy | 8 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Đèn bàn LED LE-28 | thùng | 48 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-E` | Máy xay sinh tố BL-98 | thùng | 127 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-D-2` | Đèn bàn LED LE-28 | thùng | 10 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |

## set-12

Lô eval 12, hóa đơn INV-2026-897.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy lọc không khí AI-11 | thùng | 60 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-B` | Ấm siêu tốc EL-71 | pallet | 7 | 1.2 × 1 × 1.9 | 118 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-C` | Bộ nồi inox ST-68 | thùng | 68 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Lò vi sóng MI-86 | thùng | 292 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-E` | Bộ ly thủy tinh GL-10 | thùng | 202 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Máy xay sinh tố BL-28.

## set-13

Lô eval 13, hóa đơn INV-2026-439.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Ấm siêu tốc EL-38 | thùng | 260 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-B` | Bình giữ nhiệt VA-33 | thùng | 253 | 0.4 × 0.3 × 0.3 | 7 | tùy | 8 tầng | không | dims, mass, qty, stacking |
| `SKU-C` | Bộ ly thủy tinh GL-78 | thùng | 101 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-D` | Máy xay sinh tố BL-47 | thùng | 161 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Đèn bàn LED LE-26 | thùng | 212 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-C-2` | Bộ ly thủy tinh GL-78 | thùng | 16 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Bàn ủi hơi nước ST-87.

## set-14

Lô eval 14, hóa đơn INV-2026-867.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Nồi cơm điện RI-42 | thùng | 112 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-B` | Đèn bàn LED LE-19 | pallet | 12 | 1.2 × 1 × 1.9 | 109 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-C` | Bộ nồi inox ST-48 | thùng | 170 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Máy xay sinh tố BL-60 | thùng | 114 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Ấm siêu tốc EL-25 | thùng | 35 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-D-2` | Máy xay sinh tố BL-60 | thùng | 19 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |

Không giao (chỉ spec nhắc): `SKU-F` Lò vi sóng MI-50.

## set-15

Lô eval 15, hóa đơn INV-2026-436.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy xay sinh tố BL-12 | thùng | 190 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-B` | Quạt đứng ST-97 | thùng | 144 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-C` | Bộ nồi inox ST-98 | thùng | 186 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Máy hút bụi VA-40 | thùng | 291 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Bộ ly thủy tinh GL-69 | thùng | 245 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |

Không giao (chỉ spec nhắc): `SKU-F` Nồi cơm điện RI-45.

## set-16

Lô eval 16, hóa đơn INV-2026-517.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Lò vi sóng MI-67 | thùng | 44 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-B` | Máy lọc không khí AI-94 | thùng | 267 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-C` | Máy hút bụi VA-40 | thùng | 263 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |
| `SKU-D` | Ấm siêu tốc EL-11 | thùng | 181 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Bàn ủi hơi nước ST-52 | pallet | 7 | 1.2 × 1 × 1.55 | 78 | đứng | không | không | dims, mass, qty, stacking |

## set-17

Lô eval 17, hóa đơn INV-2026-752.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Bộ nồi inox ST-79 | thùng | 101 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-B` | Bàn ủi hơi nước ST-24 | pallet | 7 | 1.2 × 1 × 2.25 | 104 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-C` | Ấm siêu tốc EL-41 | thùng | 107 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-D` | Lò vi sóng MI-63 | thùng | 137 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-E` | Đèn bàn LED LE-74 | thùng | 199 | 0.5 × 0.25 × 0.2 | 2.8 | tùy | tự do | có | dims, fragile, mass, qty |
| `SKU-C-2` | Ấm siêu tốc EL-41 | thùng | 17 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |

## set-18

Lô eval 18, hóa đơn INV-2026-421.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Bộ ly thủy tinh GL-72 | thùng | 132 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-B` | Nồi cơm điện RI-33 | thùng | 217 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-C` | Máy lọc không khí AI-68 | thùng | 289 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-D` | Lò vi sóng MI-35 | thùng | 133 | 0.55 × 0.45 × 0.35 | 15 | đứng | 4 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-E` | Máy xay sinh tố BL-98 | pallet | 11 | 1.2 × 1 × 1.55 | 174 | đứng | không | không | dims, mass, qty, stacking |
| `SKU-B-2` | Nồi cơm điện RI-33 | thùng | 36 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |

## set-19

Lô eval 19, hóa đơn INV-2026-624.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Máy hút bụi VA-54 | thùng | 88 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |
| `SKU-B` | Quạt đứng ST-47 | thùng | 263 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-C` | Bộ nồi inox ST-86 | thùng | 228 | 0.6 × 0.45 × 0.4 | 14 | tùy | 6 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Nồi cơm điện RI-43 | thùng | 67 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-E` | Máy xay sinh tố BL-44 | thùng | 80 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |

## set-20

Lô eval 20, hóa đơn INV-2026-614.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Bình giữ nhiệt VA-51 | thùng | 198 | 0.4 × 0.3 × 0.3 | 7 | tùy | 8 tầng | không | dims, mass, qty, stacking |
| `SKU-B` | Máy hút bụi VA-31 | thùng | 248 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |
| `SKU-C` | Bộ ly thủy tinh GL-62 | thùng | 77 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-D` | Ấm siêu tốc EL-23 | thùng | 295 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Nồi cơm điện RI-70 | thùng | 281 | 0.8 × 0.6 × 0.5 | 26 | đứng | tự do | không | dims, mass, posture, qty |
| `SKU-B-2` | Máy hút bụi VA-31 | thùng | 41 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |

## clean-21

Lô eval 21, hóa đơn INV-2026-753.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Bộ ly thủy tinh GL-37 | thùng | 253 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-B` | Bàn ủi hơi nước ST-70 | thùng | 238 | 0.35 × 0.2 × 0.2 | 2.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-C` | Máy hút bụi VA-75 | thùng | 256 | 0.5 × 0.35 × 0.4 | 9.5 | tùy | tự do | không | dims, mass, qty |
| `SKU-D` | Ấm siêu tốc EL-77 | thùng | 47 | 0.35 × 0.25 × 0.3 | 3.1 | tùy | tự do | không | dims, mass, qty |
| `SKU-E` | Máy lọc không khí AI-10 | thùng | 198 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |

## clean-22

Lô eval 22, hóa đơn INV-2026-314.

| Dòng | Sản phẩm | Đơn vị | SL | D × R × C (m) | Khối lượng (kg) | Đặt | Chồng | Dễ vỡ | Tài liệu nêu |
|---|---|---|---|---|---|---|---|---|---|
| `SKU-A` | Bộ ly thủy tinh GL-25 | thùng | 165 | 0.5 × 0.5 × 0.6 | 18 | đứng | 2 tầng | có | dims, fragile, mass, posture, qty, stacking |
| `SKU-B` | Máy xay sinh tố BL-54 | thùng | 189 | 0.4 × 0.3 × 0.35 | 6.2 | tùy | tự do | không | dims, mass, qty |
| `SKU-C` | Quạt đứng ST-20 | thùng | 245 | 0.6 × 0.4 × 0.45 | 12.5 | tùy | 5 tầng | không | dims, mass, qty, stacking |
| `SKU-D` | Máy lọc không khí AI-16 | thùng | 127 | 0.45 × 0.4 × 0.7 | 11 | đứng | 3 tầng | không | dims, mass, posture, qty, stacking |
| `SKU-E` | Bình giữ nhiệt VA-86 | thùng | 122 | 0.4 × 0.3 × 0.3 | 7 | tùy | 8 tầng | không | dims, mass, qty, stacking |
