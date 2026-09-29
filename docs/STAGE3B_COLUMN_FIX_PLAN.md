# Kế hoạch sửa ranh giới cột khối ký LOADING_PLAN (Tầng 3b)

> Trạng thái: **THIẾT KẾ** — chưa động vào `tools/`.
> Ngày khảo sát: 2026-09-27. Script thăm dò: `scratch/stage3b_survey/` (`survey_columns.py`, `survey_h2.py`, `survey_h2b.py`, `survey_final.py`, `y2_percol.py`, `y2_lines.py`, `gapdist.py`).
> Ảnh khảo sát: `output/stage1_out/images/form_samples/` (bản A4 2200px mà pipeline thật dùng), danh sách 19 ảnh + `page_role` lấy từ `output/stage4_dynamic_gt/gt_labeled.json`.
> **Không đọc bất kỳ kết quả detector Tầng 4 nào để hiệu chỉnh hình học.** Mọi con số dưới đây là tín hiệu ảnh (vạch kẻ, hộp chữ OCR, hình chiếu mực), không phải điểm benchmark.

---

## 0. Hiện trạng

`tools/kido_pipeline.py:63 detect_loading_plan_signature_zone()`:
- Dò đáy bảng ĐỘNG → `anchor_y` (**chính xác 5/5, GIỮ NGUYÊN**).
- `PAGE_1_NO_SIGNATURES` cho Trang 1 đa trang (**5/19 ảnh, khảo sát xác nhận rơi đúng nhánh này, GIỮ NGUYÊN**).
- Ranh giới cột **HARDCODE**: `0.02–0.20 / 0.20–0.36 / 0.36–0.54 / 0.54–0.72 / 0.72–0.98`.
- `y1 = anchor_y − 0.01`, `y2 = anchor_y + 0.18` (hằng số `box_h = 0.18`).

14/19 ảnh có khối ký thật (5 ảnh còn lại là Trang 1 miễn trừ).

---

## 1. Khảo sát: 3 hướng dò ranh giới cột

### Hướng 1 — Vạch kẻ dọc (morphology kernel dọc)

Dải đo: `[anchor_y, anchor_y+0.20]`, kernel dọc cao 45% chiều cao dải, ngưỡng cột ≥ 40% chiều cao dải.

| Ảnh | Số vạch dọc tìm được | Vị trí (x chuẩn hoá) |
|---|---|---|
| Load3.3__0 | 3 | 0.001 / 0.990 / 0.999 |
| Load_3.11__0 | 3 | 0.002 / 0.983 / 0.992 |
| Load_3.2__0 | 1 | 0.993 |
| Load_3.5__0 | 2 | 0.001 / 0.997 |
| Load_3.6__0 | 3 | 0.001 / 0.988 / 0.999 |
| Load_3.7__0 | 2 | 0.005 / 0.988 |
| Load_3.8__0 | 3 | 0.003 / 0.982 / 0.989 |
| Loading_3.4__0 | 2 | 0.001 / 0.997 |
| Loading_Plan2.1__0 | 2 | 0.001 / 0.996 |
| Loading_Plan3.1__0 | 3 | 0.001 / 0.986 / 0.999 |
| Loading_Plan_2.2__0 | 2 | 0.981 / 0.989 |
| Loading_Plan_2.3__0 | 1 | 0.992 |
| Loading_Plan_5.2__0 | 1 | 0.994 |
| Loadingplan_5.1__0 | 1 | 0.993 |

**Kết quả: 0/14 ảnh có vạch phân cách cột ở bên trong.** Mọi vạch tìm được đều nằm ở `x < 0.006` hoặc `x > 0.98` — đó là **viền khung trang**, không phải vách cột.

⇒ **Kết luận đã kiểm chứng: khối ký LOADING_PLAN là vùng TRẮNG KHÔNG KẺ**, nằm *dưới* đáy bảng hàng hoá chứ không nằm trong bảng. Hướng 1 **không khả thi về nguyên tắc**, không phải vì ngưỡng chưa chỉnh. (Nhìn trực tiếp `output/stage4_dynamic_gt/sheets/Load3.3__0.png`: 5 khung đỏ nằm trên nền trắng, không có đường kẻ nào giữa chúng.)

### Hướng 2 — Vị trí nhãn chức danh (OCR `pytesseract`, `lang=vie`)

Dải đo: `[anchor_y, anchor_y+0.10]` (dải nhãn in sẵn), upscale ×2, Otsu, `--psm 6`.
Khớp **cụm 2 token liền nhau trên cùng một dòng OCR**, chấp nhận sai chính tả bằng `rapidfuzz.fuzz.ratio ≥ 75`:

| Cột | Cụm từ khoá |
|---|---|
| C1 | `NGUOI LAP` / `LAP PHIEU` |
| C2 | `TRUONG BP` / `NHOM TRUONG` / `TRUONG BO` |
| C3 | `TAI XE` / `LAI XE` |
| C4 | `NGUOI NHAN` |
| C5 | `NGUOI GIAO` / `THU KHO` |

Tâm nhãn đo được (x chuẩn hoá) — nguồn `scratch/stage3b_survey/final.json`:

| Ảnh | C1 | C2 | C3 | C4 | C5 | số nhãn |
|---|---|---|---|---|---|---|
| Load3.3__0 | 0.135 | 0.306 | 0.494 | 0.664 | 0.841 | 5 |
| Load_3.11__0 | – | 0.305 | 0.491 | 0.661 | 0.869 | 4 |
| Load_3.2__0 | – | 0.308 | 0.494 | 0.666 | 0.811 | 4 |
| Load_3.5__0 | 0.153 | – | – | 0.668 | – | 2 |
| Load_3.6__0 | 0.170 | 0.303 | – | 0.662 | – | 3 |
| Load_3.7__0 | 0.163 | 0.313 | 0.497 | 0.665 | 0.838 | 5 |
| Load_3.8__0 | 0.159 | 0.309 | 0.493 | 0.661 | – | 4 |
| Loading_3.4__0 | 0.159 | 0.312 | 0.500 | 0.671 | – | 4 |
| Loading_Plan2.1__0 | 0.160 | 0.314 | 0.500 | 0.670 | 0.845 | 5 |
| Loading_Plan3.1__0 | 0.153 | 0.305 | 0.491 | 0.660 | – | 4 |
| Loading_Plan_2.2__0 | 0.154 | 0.306 | – | 0.659 | 0.801 | 4 |
| Loading_Plan_2.3__0 | 0.159 | 0.311 | 0.496 | 0.665 | 0.810 | 5 |
| Loading_Plan_5.2__0 | 0.116 | 0.287 | 0.495 | – | 0.846 | 4 |
| Loadingplan_5.1__0 | 0.117 | 0.287 | 0.496 | 0.686 | 0.881 | 5 |

- Tỉ lệ từng nhãn: **C1 12/14 · C2 13/14 · C3 11/14 · C4 13/14 · C5 9/14**.
- Đủ 5 nhãn: **5/14**. ≥ 4 nhãn: **12/14**. ≥ 3 nhãn: **13/14**. ≥ 2 nhãn: **14/14**.
- **Thứ tự trái→phải đúng 14/14 (0 ca đảo cột)** — tín hiệu rất sạch, không nhãn nào bị gán nhầm cột.
- Ca yếu nhất: `Load_3.5__0` (2 nhãn) và `Load_3.6__0` (3 nhãn), đều là ảnh DPI thấp; OCR trả `TGUII LAP PHIEA`, `TAI RE`, `NGUOI GIAE/ THA KHO`.

> Ghi chú: bản khớp **chính xác** (không fuzzy) chỉ đạt 5/14 đủ nhãn và 0 nhãn ở 2 ảnh. Fuzzy ≥ 75 là điều kiện cần, không phải tinh chỉnh làm đẹp.

**Bù nhãn thiếu — nội suy tuyến tính, kiểm chứng leave-one-out:** bỏ 1 nhãn đã biết, khớp `center(k) = a + b·k` (k = 0..4) trên các nhãn còn lại rồi dự đoán nhãn bị bỏ:

```
n = 56 phép thử   sai số |dự đoán − thực|:   median 0.0152   p90 0.0257   max 0.0930
```

Bước cột `b` đo trên ảnh: **median 0.171, min 0.133, max 0.209**. Sai số nội suy median ≈ **0.015 ≈ 9% bề rộng một cột**, p90 ≈ 15% — nhỏ hơn nhiều so với độ lệch đang gây lỗi (xem §2). Ca `max = 0.093` là `Load_3.5__0` khi chỉ còn 1 nhãn để khớp ⇒ phải **cấm** nội suy khi < 3 nhãn.

### Hướng 3 — Gom cụm rãnh trắng dọc (vertical projection gap)

Chiếu mực theo cột trong dải `[anchor_y, anchor_y+0.20]`, làm mượt Gauss, đếm rãnh trắng rộng ≥ 1.2% bề rộng trang:

| Ảnh | số rãnh | Ảnh | số rãnh |
|---|---|---|---|
| Load3.3__0 | 2 | Loading_3.4__0 | 3 |
| Load_3.11__0 | 3 | Loading_Plan2.1__0 | 2 |
| Load_3.2__0 | 2 | Loading_Plan3.1__0 | 3 |
| Load_3.5__0 | 3 | Loading_Plan_2.2__0 | 2 |
| Load_3.6__0 | 2 | Loading_Plan_2.3__0 | 1 |
| Load_3.7__0 | **0** | Loading_Plan_5.2__0 | 1 |
| Load_3.8__0 | 4 | Loadingplan_5.1__0 | 3 |

Cần đúng **4 rãnh** để cắt 5 cột. Đạt: **0/14**. (`Load_3.8__0` có 4 rãnh nhưng 2 trong số đó ở `0.725` và `0.954` — không phải ranh giới cột. `Load_3.7__0` có **0 rãnh** vì chữ ký viết tay kéo dài nối liền các cột.)

Biến thể đã thử (`survey_h2b.py`): thay vì chiếu mực thô, **gom cụm hộp chữ OCR** trên dải nhãn với khe ≥ 2.5% bề rộng trang. Kết quả: **5 cụm chỉ 1/14 ảnh**, còn lại 4 cụm (12/14) hoặc 3 cụm (1/14) — cột 2 và cột 3 (`Trưởng BP Kho / Nhóm trưởng` và `Tài xế`) luôn dính nhau vì nhãn cột 2 xuống dòng và tràn sang phải.

⇒ Hướng 3 **không ổn định**, kể cả bản gom cụm hộp chữ. Chỉ giữ làm tín hiệu kiểm tra chéo, không làm nguồn quyết định.

### Tổng kết khảo sát

| Hướng | Hoạt động trên 14 ảnh có khối ký | Ca hỏng | Kết luận |
|---|---|---|---|
| 1. Vạch kẻ dọc | **0/14** | tất cả — khối ký không có vách kẻ | LOẠI (sai về nguyên tắc) |
| 2. Nhãn chức danh (OCR + fuzzy) | ≥2 nhãn **14/14** · ≥3 nhãn **13/14** · thứ tự đúng **14/14** | `Load_3.5__0` chỉ 2 nhãn | **CHỌN** |
| 3. Rãnh trắng dọc | **0/14** đủ 4 rãnh | chữ ký nối cột, nhãn tràn cột | LOẠI (phụ trợ) |

---

## 2. Vì sao FP dồn đúng vào cột 2 và cột 4 — cơ chế đã đo được

Tâm cột **đo từ nhãn** (median 14 ảnh) so với tâm hộp **hardcode hiện tại**:

| Cột | Tâm nhãn đo được | Tâm hộp hiện tại | Lệch |
|---|---|---|---|
| C1 Người lập phiếu | 0.157 | 0.110 | **−0.047** |
| C2 Trưởng BP Kho | 0.306 | 0.280 | **−0.026** |
| C3 Tài xế | 0.495 | 0.450 | **−0.045** |
| C4 Người nhận hàng | 0.665 | 0.630 | **−0.035** |
| C5 Người giao / Thủ kho | 0.841 | 0.850 | +0.009 |

Toàn bộ hộp lệch **sang trái** 0.03–0.05 (≈ 20–30% bề rộng một cột). Hệ quả cơ học:

- Hộp C2 `[0.20, 0.36]` có mép trái `0.20`, trong khi cột C1 thật kéo tới `≈0.232`. Nét ký dài của **người lập phiếu** thò vào dải `0.20–0.232` ⇒ detector thấy mực trong ô C2, mà C2 thực tế **luôn trống** ⇒ **9 FP**.
- Hộp C4 `[0.54, 0.72]` có mép trái `0.54`, trong khi cột C3 thật kéo tới `≈0.580`. Nét ký của **tài xế** thò vào `0.54–0.58` ⇒ **10 FP** (v1).
- C1, C3, C5 không có hàng xóm bên trái nào đang ký nên 0 FP.

Đây là **giải thích cơ học khớp hoàn toàn với bảng FP đã đo**, suy ra từ hình học chứ không từ điểm số.

Ranh giới nếu lấy median toàn tập (chỉ để minh hoạ độ lệch — thuật toán **không** dùng median này làm hằng số, mỗi ảnh tự tính ranh giới của nó):

| | b0 | b1 | b2 | b3 | b4 | b5 |
|---|---|---|---|---|---|---|
| Hiện tại (hardcode) | 0.020 | 0.200 | 0.360 | 0.540 | 0.720 | 0.980 |
| Suy từ nhãn (median) | 0.072 | 0.232 | 0.400 | 0.580 | 0.753 | 0.927 |

---

## 3. Mép dưới `y2` — sửa bằng "đóng cụm mực" (Ink-Group Closure)

**Triệu chứng đo được** (`y2_lines.py`, ví dụ `Load3.3__0`, `anchor_y = 0.529`, `y2` hiện tại `= 0.709`):

```
cột 1: cụm mực [0.534,0.545] nhãn · [0.578,0.600] "(Ký và ghi rõ họ tên)" · [0.650,0.720] NÉT KÝ + TÊN
                                                                             ^ y2=0.709 CẮT GIỮA CỤM
cột 5: cụm mực [0.570,0.661]                                            → y2=0.709 nằm ngoài, không cắt
```

GT ghi đúng hiện tượng này: *"Tên in tay 'Ngô Thị Lệ Huyền' nằm NGAY DƯỚI mép dưới khung nên bị cắt"* → `box_placement = PARTIAL`.

**Quy tắc đề xuất — không thêm hằng số mới:**

> Nếu `y2` hiện tại rơi **vào bên trong** một cụm mực liên tục của chính cột đó, kéo `y2` xuống **đáy của cụm mực đó**. Nếu `y2` rơi vào vùng trắng, giữ nguyên.

Cụm mực = các dòng có mực trong dải x của cột, gộp lại khi khe trắng ≤ `0.008·H` (≈ 18px ở ảnh 2200px — nhỏ hơn khoảng cách giữa hai dòng chữ in, đo được ≥ `0.03·H`, nên không gộp nhầm hai dòng khác nhau).

Tính chất:
- **Đơn điệu**: `y2` chỉ nới ra, không bao giờ co lại ⇒ **không thể gây mất Recall**.
- **Không nuốt nội dung lạ**: dừng đúng tại đáy cụm đang bị cắt, không nhảy sang cụm kế tiếp. Ở `Load3.3__0` cột 4, đoạn ghi chú `"- Hàng hoá đã nhận..."` nằm ở `[0.732,0.754]` là **cụm khác** ⇒ không bị nuốt.
- Không cần hằng số `K` nào.

**Đã thử và BỊ LOẠI — các phương án `y2` khác, bác bỏ bằng số đo:**

| Phương án | Số đo | Kết luận |
|---|---|---|
| "Đáy mực toàn trang" | 12/14 ảnh trả `y2 = 1.000` vì footer (`ngày giờ in`, `Trang 2/2`) cũng là mực | LOẠI |
| "Dừng ở khe trắng ≥ 0.03·H" (`y2_percol.py`) | Dừng ngay sau **dòng nhãn** ở cả 4 cột đầu (`y2 ≈ anchor+0.015`) vì khe nhãn→chữ ký vốn lớn hơn 0.03·H | LOẠI |
| "Khe trắng ≥ K × pitch dòng chữ" (`gapdist.py`) | Ước lượng pitch không ổn định (0.002–0.050 giữa các ảnh); phân bố khe sau chuẩn hoá **không lưỡng đỉnh** ⇒ không tồn tại `K` có cơ sở | LOẠI |

---

## 4. Thuật toán đề xuất (từng bước)

Đầu vào: `a4_img`, `page_role`.

1. **Dò đáy bảng → `anchor_y`** — *giữ nguyên nguyên văn code hiện tại* (`kido_pipeline.py:69-113`), gồm cả nhánh `PAGE_1_NO_SIGNATURES`, `TOP_SIGNATURES_DETECTED`, `DEFAULT_SINGLE_PAGE`.
2. **Cắt dải nhãn** `label_band = [anchor_y, anchor_y + 0.10]`, toàn bề rộng.
3. **OCR dải nhãn**: xám → upscale ×2 (INTER_CUBIC) → Otsu → `image_to_data(lang='vie', config='--psm 6')`, giữ từ có `conf > 10`.
4. **Khớp nhãn**: với mỗi cột C1..C5, quét mọi cụm 2 từ liền nhau **cùng một dòng OCR**, chấp nhận khi `min(fuzz.ratio(token_j, mẫu_j)) ≥ 75`. Tâm nhãn = trung điểm `[x0 từ đầu, x1 từ cuối]`. Nhiều lần khớp cho cùng một cột → lấy **median**.
5. **Cổng số lượng & thứ tự**:
   - `n_labels < 3` → **ABSTAIN** `COLUMN_DETECTION_FAILED`.
   - Tâm các cột tìm được không tăng dần theo chỉ số cột → **ABSTAIN** `COLUMN_ORDER_VIOLATION`.
6. **Nội suy cột thiếu**: khớp bình phương tối thiểu `center(k) = a + b·k` trên các cột đã tìm (k = chỉ số cột 0..4), suy ra đủ 5 tâm.
   - `b` ngoài `[0.10, 0.25]` → **ABSTAIN** `COLUMN_PITCH_IMPLAUSIBLE`.
7. **Ranh giới cột**: `b_i = (center_{i-1} + center_i)/2` với i = 1..4; `b_0 = center_0 − b/2`; `b_5 = center_4 + b/2`; clamp về `[0.01, 0.99]`.
8. **`y1` = `anchor_y − 0.01`** (giữ nguyên). **`y2` khởi tạo = `anchor_y + 0.18`** (giữ nguyên), rồi áp **Ink-Group Closure** (§3) **riêng cho từng cột** ⇒ mỗi cột có `y2` riêng.
9. Trả `targets` với `box_norm = [y1, b_i, y2_i, b_{i+1}]`; giữ nguyên `role` / `required` / `expected_color` / `description` đang có; **thêm** `column_source ∈ {OCR_LABEL, INTERPOLATED}` cho từng target để audit được cột nào là đo, cột nào là suy.

### Hành vi khi dò thất bại — **cấm silent fallback**

| Tình huống | `zone_status` | `has_signatures` | `targets` |
|---|---|---|---|
| < 3 nhãn đọc được | `COLUMN_DETECTION_FAILED` | `False` | `[]` |
| Thứ tự cột bị đảo | `COLUMN_ORDER_VIOLATION` | `False` | `[]` |
| Bước cột ngoài `[0.10, 0.25]` | `COLUMN_PITCH_IMPLAUSIBLE` | `False` | `[]` |
| OCR ném lỗi / Tesseract vắng mặt | `COLUMN_OCR_UNAVAILABLE` | `False` | `[]` |

**Tuyệt đối KHÔNG rơi về bộ hằng số cũ.** Tầng 4 nhận `targets = []` và phải ABSTAIN đúng contract (cùng cơ chế với `UNMAPPED`, `AGENTS.md` mục 7.A.7).

Trên tập 19 ảnh hiện có, dự kiến: **13/14 ảnh có khối ký dò được cột động, 1/14 ABSTAIN** (`Load_3.5__0`, chỉ 2 nhãn). Mất 1 ảnh là **giá phải trả có chủ đích** để không đoán bừa; 5 ảnh Trang 1 vẫn `PAGE_1_NO_SIGNATURES` như cũ.

---

## 5. Tách module

### File mới `tools/stage3b_zone_resolver.py`

```python
# --- hằng số hình học, tất cả có nguồn gốc vật lý (xem §6) ---
LABEL_BAND_HEIGHT   = 0.10
INK_GROUP_MERGE_GAP = 0.008
COLUMN_PITCH_RANGE  = (0.10, 0.25)
MIN_LABELS_REQUIRED = 3
FUZZ_MIN_SCORE      = 75

COLUMN_LABEL_PATTERNS: list[tuple[int, tuple[str, ...]]]   # (chỉ số cột, cụm token)

def detect_table_lines(a4_img) -> list[float]:
    """Helper dò vạch kẻ ngang, dùng chung cho LOADING_PLAN và HOA_DON
    (hiện đang bị chép 2 lần — AGENTS.md mục 6)."""

def detect_signature_columns(a4_img, anchor_y: float) -> dict:
    """Dò ranh giới 5 cột từ nhãn chức danh in sẵn.
    Trả {'ok': bool, 'status': str, 'centers': list[float]|None,
         'bounds': list[float]|None, 'pitch': float|None,
         'label_hits': dict[int, float], 'sources': list[str]}"""

def close_ink_group_bottom(a4_img, x0: float, x1: float, y2: float) -> float:
    """Ink-Group Closure: nếu y2 cắt giữa một cụm mực thì kéo xuống đáy cụm."""

def detect_loading_plan_signature_zone(a4_img, page_role="HEADER") -> dict: ...
def detect_invoice_signature_zone(a4_img, page_role="HEADER", system="COMMON") -> dict: ...
detect_channel_aware_invoice_zone = detect_invoice_signature_zone
```

Hai hàm `detect_*_signature_zone` **chuyển nguyên trạng** từ `kido_pipeline.py:63-404`, chỉ thay phần sinh ranh giới cột của `LOADING_PLAN`. Chữ ký hàm và tên khoá trả về **giữ y nguyên**.

### `tools/kido_pipeline.py` sau khi tách

```python
from tools.stage3b_zone_resolver import (
    detect_loading_plan_signature_zone,
    detect_invoice_signature_zone,
    detect_channel_aware_invoice_zone,
)
```

Vì `from tools.kido_pipeline import detect_loading_plan_signature_zone` vẫn phân giải được qua tên đã re-export, **không file nào phải sửa**:
`generate_nb3_ver2.py:111` · `generate_nb4_ver2.py:95,398` · `generate_nb_e2e.py` · `test_pipeline_e2e.py` · `build_lp_dynamic_crops.py:17` · `stage4_verifier_v2.py` (chỉ tham chiếu trong comment).
`tools/bench_lp_zone_ab.py:45` và `tools/render_zone_overlay.py:71` đã import sẵn từ `tools.stage3b_zone_resolver` ⇒ sẽ tự chạy được ngay khi module tồn tại.

### Thứ tự thực hiện đề xuất (không gộp bước)

1. Tạo `stage3b_zone_resolver.py` = **chép nguyên trạng** 2 hàm + re-export ở `kido_pipeline.py`. Chạy `test_pipeline_e2e.py` → phải giữ **9/9 PASS**, và manifest ver2 phải **không đổi** (diff toàn bộ trừ `elapsed_ms`). Đây là refactor thuần, kiểm chứng được bằng diff.
2. Mới thay phần cột + `y2`. Chạy A/B bằng `tools/bench_lp_zone_ab.py` (đã có sẵn), đối chiếu `gt_labeled.json`.
3. Tách `detect_table_lines()` dùng chung sau cùng, làm riêng một bước.

---

## 6. Bảng "hằng số nào còn lại và nó đến từ đâu"

| Hằng số | Giá trị | Nguồn gốc | Dò theo benchmark? |
|---|---|---|---|
| `LABEL_BAND_HEIGHT` | 0.10 | Dải nhãn in sẵn gồm 2 dòng chữ (chức danh + `(Ký và ghi rõ họ tên)`) ngay dưới đáy bảng; đo được chiếm 0.03–0.06 chiều cao trang, lấy 0.10 cho dư gấp đôi | Không |
| `MIN_LABELS_REQUIRED` | 3 | Cần ≥ 2 điểm để khớp đường thẳng; lấy 3 để có tối thiểu 1 bậc tự do kiểm tra. LOO cho thấy với 2 nhãn sai số vọt lên 0.093 | Không — tính chất bài toán khớp tuyến tính |
| `COLUMN_PITCH_RANGE` | (0.10, 0.25) | 5 cột chia đều một trang ⇒ bước danh nghĩa 1/5 = 0.20; biên ±25%. Dải đo thực tế 0.133–0.209 nằm gọn bên trong | Không — hình học biểu mẫu |
| `FUZZ_MIN_SCORE` | 75 | Ngưỡng `rapidfuzz.ratio` chịu được 1 ký tự sai trên token 4–7 ký tự (`LIP`↔`LAP`, `RE`↔`XE`) | Không — tính chất lỗi OCR |
| `INK_GROUP_MERGE_GAP` | 0.008·H | ≈ 18px ở ảnh A4 2200px; nhỏ hơn khoảng cách giữa hai dòng chữ in (đo được ≥ 0.03·H) nên không gộp nhầm 2 dòng | Không — độ phân giải ảnh |
| `conf > 10` (lọc từ OCR) | 10 | Ngưỡng tin cậy tối thiểu của Tesseract, chỉ để bỏ hộp rỗng/nhiễu | Không |
| `anchor_y = last_line + 0.015` | giữ nguyên | Code hiện tại, đang đúng 5/5, không đụng | — |
| `y1 = anchor_y − 0.01` | giữ nguyên | Code hiện tại | — |
| `y2 khởi tạo = anchor_y + 0.18` | giữ nguyên | Code hiện tại; sau sửa nó chỉ còn là **điểm xuất phát** cho Ink-Group Closure, không còn là mép cuối cùng | — |
| **Ranh giới cột `0.02/0.20/0.36/0.54/0.72/0.98`** | **XOÁ** | — | thay bằng đại lượng đo trên từng ảnh |

---

## 7. Rủi ro

1. **Tầng 3b nay phụ thuộc Tesseract.** Trước đây thuần hình học. Nếu Tesseract vắng mặt hoặc sai cấu hình, toàn bộ LOADING_PLAN ABSTAIN. Giảm nhẹ: nhánh `COLUMN_OCR_UNAVAILABLE` tường minh + kiểm tra tại import.
2. **Chi phí thời gian.** Thêm 1 lần OCR dải nhãn cho mỗi trang LOADING_PLAN (~0.25–0.45 s/ảnh trên dải `0.10·H` của ảnh 2200px). E2E hiện đã 5.75–6.36 s/trang với `MAX_LATENCY_SEC = 8.0` (`test_pipeline_e2e.py:40`) ⇒ **biên còn mỏng**; phải đo lại latency, có thể phải nâng ngưỡng. Rủi ro thật, không phải giả định.
3. **Mất 1 ảnh (`Load_3.5__0`) do ABSTAIN.** Đổi 1 ảnh không được chấm lấy việc bỏ hẳn hằng số — cần người nghiệp vụ đồng ý.
4. **Hai nguồn sự thật vẫn tồn tại.** `SIGNATURE_PRESET_MAP['LOADING_PLAN']` (3 vai trò, preset tĩnh Tầng 3) vẫn mâu thuẫn với zone động (5 vai trò). Kế hoạch này **không giải quyết** việc đó; benchmark v1 vs ver2 vẫn không so trực tiếp được (`AGENTS.md` mục 6 và 8).
5. **GT `gt_labeled.json` gắn với hộp CŨ.** Sau khi đổi hình học, `box_norm` trong GT không còn khớp hộp mới ⇒ **phải gán nhãn lại**, hoặc đối chiếu theo cặp `(file, role)` thay vì theo hộp. Nếu không làm, mọi số đo "sau khi sửa" đều vô nghĩa — đây là bẫy PASS giả thứ tư của dự án.
6. **Mẫu số chỉ 14.** Mọi tỉ lệ trong tài liệu này có mẫu số 14 ảnh. Từ điển nhãn (`NGUOI LAP`, `TRUONG BP`, …) gắn với biểu mẫu LOADING_PLAN của KIDO — đổi khách hàng là mất hiệu lực, cùng hạn chế với `ORIENTATION_KEYWORDS` ở Tầng 1. Nên tách ra `config/` từ đầu.
7. **Biểu mẫu 5.1/5.2 lệch hệ trục thật.** Tâm C1 ở hai ảnh này là 0.116/0.117 trong khi 12 ảnh còn lại là 0.135–0.170 — bố cục biểu mẫu kho khác hẳn. Đây chính là lý do bắt buộc phải đo **từng ảnh**; đồng thời là cảnh báo rằng bất kỳ median toàn tập nào cũng sai cho nhóm này.
