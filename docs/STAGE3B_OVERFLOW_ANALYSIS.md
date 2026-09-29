# Tầng 3b — Khảo sát định lượng: mực gây FP ở cột 1 & 3 có "tràn từ cột bên phải" không?

> **Loại tài liệu:** khảo sát để HIỂU, không chỉnh tham số. Không sửa file nào trong `tools/`, `config/`, `output/stage4_dynamic_gt/`.
> **Script:** `scratch/stage3b_overflow_analysis.py` (đo) + `scratch/stage3b_overflow_rule.py` (phân tích luật). Dữ liệu thô: `scratch/stage3b_overflow_rows.json`.
> **Ngày:** 2026-09-27

## 0. Giả thuyết được kiểm định

> Mực gây False Positive ở cột `Trưởng BP Kho` (index 1) và `Người nhận hàng` (index 3) **nằm sát BIÊN PHẢI của ROI và thuộc chữ ký của cột bên phải**. Lập luận: C2 và C4 là hai cột duy nhất có hàng xóm phải luôn ký (C3 Tài xế, C5 Thủ kho).

## 1. Phương pháp

- Chạy khung **MỚI** `tools/stage3b_zone_resolver.py:detect_loading_plan_signature_zone` (bám nhãn chức danh OCR) trên **19 ảnh LOADING_PLAN** của `output/stage1_out/images/form_samples/`.
- **13/19 ảnh** trả `has_signatures=True` → **65 ô** (13 × 5 cột). 6 ảnh còn lại là Trang 1 đa trang / không có khối ký.
- Mặt nạ mực = mực xanh HSV `[90,40,40]–[145,255,255]` **OR** mực tối theo nền (`gray < max(40, median−35)`, đúng công thức `tools/stage4_verifier.py:183-193`), rồi `MORPH_OPEN 2×2`.
- **Lọc chữ in sẵn** như v1: bỏ connected component có `area < 100px²` hoặc `height < 22px`.
- Chỉ số mỗi ô: tổng pixel mực `ink`, mật độ `ink_ratio`, trọng tâm X chuẩn hóa `cx` (0 = sát trái, 1 = sát phải), `L15` = tỉ lệ mực trong 15% bề rộng sát biên trái, `R15` = tỉ lệ mực trong 15% sát biên phải, `xmax`, cờ chạm mép.

### Giới hạn phải nêu rõ
`output/stage4_dynamic_gt/gt_labeled.json` được gán nhãn trên **khung CŨ** (`zone_source = kido_pipeline.detect_loading_plan_signature_zone`, hằng số cột 0.02/0.20/0.36/0.54/0.72/0.98). Khung MỚI đo biên cột từ nhãn chức danh nên hộp lệch đi; nhãn PRESENT/ABSENT vì vậy chỉ **gần đúng** cho khung mới. 18/75 ô trong GT vốn đã bị chính annotator đánh `box_placement = PARTIAL`. Mọi con số dưới đây phải đọc với sai số này. 3 agent khác đang gán nhãn lại trên khung mới.

Kích thước ROI khung mới khá đều (bề rộng median 254–279 px, cao 418–442 px) nên so sánh giữa các cột là hợp lệ.

## 2. Số liệu

### 2.1 Phân bố mực theo trục X, theo nhóm cột (n = ô có mực)

| Nhóm | n | `R15` med | `R15` max | `L15` med | `L15` max | `cx` med |
|---|---|---|---|---|---|---|
| **cột 1** (Trưởng BP Kho) | 13 | **0.127** | 0.283 | **0.000** | 0.000 | 0.539 |
| **cột 3** (Người nhận hàng) | 13 | **0.073** | 0.349 | **0.000** | 0.136 | 0.536 |
| cột 0 / 2 / 4 | 39 | 0.036 | 0.187 | 0.067 | 0.213 | 0.499 |

### 2.2 Mức độ "dồn hẳn về biên phải"

| Điều kiện | Số ô / 65 |
|---|---|
| ≥ 50% mực nằm trong 15% bề rộng sát biên phải | **0** |
| ≥ 80% mực nằm trong 15% bề rộng sát biên phải | **0** |

### 2.3 Khả năng tách PRESENT (41 ô) vs ABSENT (24 ô) — AUC Mann–Whitney

| Chỉ số | PRESENT med | ABSENT med | AUC |
|---|---|---|---|
| `right15` | 0.063 | 0.115 | **0.384** (tức 0.616 theo chiều ngược) |
| `cx` | 0.505 | 0.537 | 0.362 (→ 0.638) |
| `xmax` | 0.996 | 0.996 | **0.510** (vô dụng) |
| `left15` | 0.064 | 0.000 | 0.836 |
| `ink` (tổng pixel mực) | 9 346 | 4 233 | **0.956** |
| `ink_ratio` (mật độ) | 0.0788 | 0.0374 | **0.962** |

### 2.4 Luật "bỏ mực chỉ chạm dải 15% sát biên phải"

Mô phỏng: mực còn lại = `ink × (1 − R15)`.

| | giá trị |
|---|---|
| ABSENT — `ink_ngoài` **lớn nhất** | **8 402** |
| PRESENT — `ink_ngoài` **nhỏ nhất** | **5 141** |
| Hai nhóm tách rời? | **KHÔNG** (chồng lấn 5 141 – 8 402) |

Nhóm chồng lấn không hề nhỏ hơn khi bỏ dải biên phải: ngưỡng thuần trên `ink` (không đụng gì tới biên phải) đã cho `ink ≥ 5100` → **TP 41 / FN 0 / TN 20 / FP 4**, accuracy 93.8%. Bỏ dải biên phải **không cải thiện** con số này.

### 2.5 Ô PRESENT lệch hẳn về biên phải (câu hỏi 3)

| Ô | `cx` | `R15` | `ink` |
|---|---|---|---|
| `Load_3.11__0.png` cột 0 (Người lập phiếu) | 0.675 | 0.187 | 8 393 |

Đây là ô PRESENT duy nhất thỏa `cx > 0.65` hoặc `R15 > 0.25`. Ô ABSENT có `R15` cao nhất là `Load_3.7__0.png` cột 3 (`R15 = 0.349`, `cx = 0.657`) — tức **ô PRESENT lệch phải nhất và ô ABSENT lệch phải nhất nằm trùng dải giá trị**.

## 3. Trả lời 3 câu hỏi

**Câu 1 — Mực ở cột 1 và 3 tập trung biên PHẢI hay TRÁI?**
Lệch về **phải**, nhưng rất nhẹ và không hề "tập trung". `R15` median 0.127 (cột 1) và 0.073 (cột 3) so với 0.036 ở nhóm 0/2/4 — nghĩa là **87.3% và 92.7% lượng mực nằm NGOÀI dải biên phải**. Trọng tâm `cx` chỉ dịch 0.036–0.040 (0.539 / 0.536 vs 0.499), tương đương ~10 px trên ROI rộng ~265 px. Tín hiệu mạnh hơn nằm ở phía **trái**: cột 1 có `L15 = 0.000` ở **13/13 ảnh** (max cũng là 0.000), cột 3 có median 0.000 — tức 15% bề rộng bên trái của hai cột này **luôn trắng**, trong khi cột 0/2/4 có median 0.067.

**Câu 2 — Luật "bỏ mực chỉ chạm dải X% sát biên phải" có tách được nhóm FP không?**
**KHÔNG.** Không tồn tại X nào làm được việc đó, vì tiền đề của luật không đúng: **0/65 ô** có dù chỉ 50% lượng mực nằm trong dải 15% biên phải. Mực ở các ô ABSENT **trải đều khắp ROI**, không dồn vào mép. Bỏ dải biên phải chỉ cắt trung bình 11.5% lượng mực của ô ABSENT, để lại vùng chồng lấn 5 141 – 8 402 px với nhóm PRESENT. Bản thân `right15` có AUC 0.384/0.616 — gần như ngẫu nhiên. `xmax` AUC 0.510, tức "mực có chạm mép phải không" **hoàn toàn vô nghĩa** làm tín hiệu (56/65 ô chạm mép, cả PRESENT lẫn ABSENT).

**Câu 3 — Luật đó có làm hỏng ô nào đang đúng không?**
Có, và đây là lý do thứ hai để loại. `Load_3.11__0.png` cột 0 là ô PRESENT với `cx = 0.675`, `R15 = 0.187` — lệch phải hơn 10/24 ô ABSENT. Ô ABSENT lệch phải nhất (`Load_3.7__0` c3, `R15 = 0.349`) và ô PRESENT lệch phải nhất nằm cùng dải, nên mọi ngưỡng cắt sẽ hoặc bỏ sót FP hoặc giết chữ ký thật. Với nguyên tắc đã chốt của dự án (*không đánh đổi Recall chữ ký thật để lấy Precision*), luật này không đạt.

## 4. Kết luận

**GIẢ THUYẾT SAI.** Mực gây FP ở cột 1 và 3 **không** nằm sát biên phải và **không** giải thích được bằng "tràn từ chữ ký cột bên phải". Có một độ lệch phải nhẹ (Δ`cx` ≈ 0.04), nhưng nó quá nhỏ và quá chồng lấn để làm cơ sở cho bất kỳ luật lọc nào.

**Tín hiệu thật nằm ở chỗ khác:** lượng/mật độ mực. `ink_ratio` cho AUC **0.962** so với 0.384 của `right15` — chênh lệch một bậc về sức phân biệt. Ô ABSENT ở cột 1 và 3 có `ink_ratio` median 0.037–0.039, bằng khoảng **một nửa** cột 0/2/4 (0.064–0.100). Nghĩa là mực trong các ô FP đó là **nhiễu nền phân tán** (vệt scan, chữ in còn sót sau bộ lọc, đường kẻ mảnh) chứ không phải nét ký của hàng xóm.

**Quan sát phụ đáng theo đuổi hơn:** `L15 = 0.000` tuyệt đối ở 13/13 ảnh cột 1 gợi ý biên trái của hai cột này bị đặt lệch sang trái so với vùng nội dung thật — nhãn chức danh của cột 1 và 3 có lẽ ngắn hơn nên tâm nhãn không trùng tâm vùng ký. Đó là vấn đề **đặt hộp**, khác hẳn với vấn đề **tràn mực** mà giả thuyết nêu.

## 5. Mức độ tin cậy

**Trung bình-cao** cho kết luận bác bỏ; **thấp** cho mọi con số tuyệt đối.

- Cao vì: kết quả không sát ranh. `0/65` ô dồn mực về biên phải là một số tuyệt đối, không phụ thuộc nhãn GT. `xmax` AUC 0.510 cũng không phụ thuộc gì vào việc gán nhãn đúng hay sai. Khoảng cách AUC 0.962 vs 0.384 quá lớn để bị lật bởi vài nhãn sai.
- Hạn chế: (a) nhãn PRESENT/ABSENT lấy từ GT khung **CŨ**, chỉ gần đúng cho khung mới — mọi số phân tách PRESENT/ABSENT (mục 2.3, 2.4, 2.5) phải đo lại sau khi 3 agent kia gán nhãn xong; (b) n = 65 ô / 13 ảnh, trong đó nhóm PRESENT ở cột 1+3 chỉ có **4 ô** — quá ít để nói chắc về hành vi của chữ ký thật tại hai cột này; (c) mặt nạ mực là hợp của mực xanh và mực tối, chưa tách riêng đóng góp của từng kênh; (d) ảnh demo 45–150 DPI.
