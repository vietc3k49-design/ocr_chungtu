# TẦNG 4 (VER 2) — KẾ HOẠCH SỬA: KIỂM MỘC TRÊN VÙNG KÝ ĐỘNG
## Phạm vi MVP web: chỉ `LOADING_PLAN` (19) + `HOA_DON` (21) = 40/72 ảnh
## KHÔNG viết lại Tầng 4 từ đầu. KHÔNG đụng PO / PGH / PXK / BBBG ở vòng này.

---

## 0. Kết luận rà soát (đọc trước khi code)

| Ý định | Đánh giá | Lý do |
|---|---|---|
| Đóng băng template, chưa làm PO | ✅ GIỮ | 40 ảnh đủ demo web; PO chưa có zone động thì web sẽ vẽ khung sai |
| Làm Tầng 4 kiểm mộc rồi mới web | ✅ GIỮ thứ tự | Web cần API `verdict + crop + lý do`, không cần 72/72 template |
| Viết Tầng 4 mộc mới từ đầu | ❌ BỎ | `ocr-tang4-verify.ipynb` + `tools/stage4_verifier.py` đã có Engine A/B. Tầng 3 ver 2 **đã gọi** `verify_single_target` cho cả chữ ký lẫn mộc |
| Cắm web vào Tầng 4 cũ như hiện tại | ❌ CẤM | Tầng 4 cũ đọc BBox hardcode từ `stage3_batched_manifest.json`. Tầng 3 ver 2 đã chứng minh BBox đó đè bảng kem (Trang 1) và rơi giấy trắng Y=0.62 (Trang 2) |
| Bỏ Tầng 3 batch (`ocr-tang3-batch.ipynb`) | ❌ CẤM | Web cần **lô chuyến xe**. Tầng 3 ver 2 chỉ sửa **hình học vùng ký**, không thay gom lô |
| Chạy Tầng 4 trên 32 ảnh chưa chuẩn hóa zone | ❌ CẤM | Abstain `CHUA_CHUAN_HOA_VUNG_KY`, không đoán |

**Tách tầng đúng cho web (đóng băng tên, đừng đổi nữa):**
```text
Tầng 1  Chuẩn hóa ảnh          → output/stage1_out/
Tầng 2  Phân loại + key field  → output/stage2_out/stage2_classified_results.json
Tầng 3  Gom lô chuyến xe       → output/stage3_out/stage3_batched_manifest.json
Tầng 3b Zone động theo template → detect_loading_plan_signature_zone / detect_invoice_signature_zone
Tầng 4  Kiểm CHỮ KÝ + MỘC trên zone động → output/stage4_out/
```
Tầng 4 **không** tự dò lại đáy bảng. Tầng 4 **nhận** `targets[]` (đã có `box_norm`, `role`, `expected_color`, `required`, `stamp_shape`) rồi trả `detected / ink_type / confidence / reason`.

---

## 1. Tám chỗ phải sửa trong Tầng 4 cũ (map 1-1 sang code)

### SỬA 1 — Nguồn BBox: bỏ manifest hardcode, lấy zone động

**Sai (Cell 3 + Cell 9 Tầng 4 cũ):**
```python
MANIFEST_PATH = "output/stage3_out/stage3_batched_manifest.json"
targets = doc.get("signature_targets", [])   # BBox cứng Y=0.62 / Y=0.78
```

**Đúng:**
```python
from tools.stage2_classifier import *  # chỉ để đọc JSON Tầng 2
from tools.kido_pipeline import (
    detect_loading_plan_signature_zone,
    detect_invoice_signature_zone,
)
from tools.stage4_verifier import (
    detect_document_modality,
    evaluate_document_verdict,   # bản đã hiểu required=False
)

# Ảnh vào Tầng 4 bắt buộc đã scale H=2200 (cùng contract Tầng 3 ver 2)
scale = 2200.0 / raw.shape[0]
a4 = cv2.resize(raw, (int(raw.shape[1] * scale), 2200))

s2 = s2_map[fn]
if s2["doc_type"] == "LOADING_PLAN":
    zone = detect_loading_plan_signature_zone(a4, page_role=s2.get("page_role", "HEADER"))
elif s2["doc_type"] == "HOA_DON":
    zone = detect_invoice_signature_zone(a4, system=s2.get("system", "COMMON"))
else:
    zone = {"status": "CHUA_CHUAN_HOA_VUNG_KY", "has_signatures": False, "targets": []}
```
Nếu `zone["status"] == "PAGE_1_NO_SIGNATURES"` → không gọi verifier, verdict = `TRANG_1_CHUA_KY` (HỢP LỆ).
Nếu `CHUA_CHUAN_HOA_VUNG_KY` → abstain, không fallback BBox cứng.

---

### SỬA 2 — extract_adaptive_roi: cấm margin 15% liếm lề
- **Sai:** `ADAPTIVE_MARGIN = 0.15` rồi `x1 = (xmin - 0.15*box_w)*w` → với xmin=0.05 sẽ chạm X=0, Engine B nhận nhầm vạch đen máy photo thành chữ ký/mộc (`Hoadon_2.1__0`, `Hoadon3.11__0`).
- **Đúng — clamp cứng theo Tầng 3 ver 2:**
```python
SAFE_X = (0.08, 0.96)   # hóa đơn cột trái: xmax <= 0.44 đã được zone resolver set
SAFE_Y = (0.02, 0.97)
STAMP_MARGIN = 0.08     # mộc tròn/vuông được nới ÍT hơn chữ ký
SIG_MARGIN   = 0.12

def extract_safe_roi(img, box_norm, margin, safe_x=SAFE_X, safe_y=SAFE_Y):
    h, w = img.shape[:2]
    ymin, xmin, ymax, xmax = box_norm
    bh, bw = ymax - ymin, xmax - xmin
    y1 = int(max(safe_y[0], ymin - margin * bh) * h)
    y2 = int(min(safe_y[1], ymax + margin * bh) * h)
    x1 = int(max(safe_x[0], xmin - margin * bw) * w)
    x2 = int(min(safe_x[1], xmax + margin * bw) * w)
    y1, x1 = max(0, y1), max(0, x1)
    y2, x2 = min(h, y2), min(w, x2)
    if y2 - y1 < 8 or x2 - x1 < 8:
        return None, (y1, x1, y2, x2)
    return img[y1:y2, x1:x2], (y1, x1, y2, x2)
```
Xóa mọi BBox hardcode trong case study:
- `[0.606, 0.317, 0.796, 0.549]` (Cell 13–14 Tầng 4 cũ)
- `LEGACY_LOADING_PLAN_PRESET` Y=0.62
- `LEGACY_INVOICE_PRESET` Y=0.78–0.95
Case study chỉ lấy `zone["targets"]`.

---

### SỬA 3 — Engine A mộc: cấm đếm pixel. Phải có HÌNH HỌC mộc
- **Sai:**
```python
if red_px > 60: detected = True          # 60 px = nhiễu / chữ đỏ in sẵn
elif blue_px > 100: detected = True      # chữ ký xanh bị nhận là mộc đỏ công ty
```
Hậu quả: logo KIDO đỏ, tiêu đề đỏ, dòng FPT chân trang, chữ ký xanh trong cùng ROI → DAT ảo.
- **Đúng — tách 2 class mộc, bắt buộc qua cổng hình học:**
```python
STAMP_CLASS = {
    "COMPANY_ROUND_RED": {   # mộc pháp nhân KIDO trên Hóa đơn / PXK
        "hsv": [([0, 50, 40], [14, 255, 255]), ([165, 50, 40], [180, 255, 255])],
        "shape": "circle",          # HoughCircles HOẶC contour circularity >= 0.65
        "min_diameter_ratio": 0.22, # so với min(w,h) của ROI
        "max_diameter_ratio": 0.95,
        "min_ink_px": 400,          # trên ảnh H=2200, ROI mộc ~180–280 px
        "allow_blue_purple": False, # CẤM nhận chữ ký xanh là mộc đỏ
    },
    "SUPERMARKET_SQUARE": {  # Co.op / GS25 CJ / Satra / BigC / BHX
        "hsv": [
            ([0, 50, 40], [14, 255, 255]),
            ([165, 50, 40], [180, 255, 255]),
            ([90, 40, 40], [145, 255, 255]),   # xanh
            ([130, 40, 40], [165, 255, 255]),  # tím
        ],
        "shape": "rect",            # minAreaRect, 0.55 <= w/h <= 1.80
        "min_side_ratio": 0.25,
        "min_ink_px": 350,
        "allow_blue_purple": True,
        "need_closed_border": True, # viền khung khép (morph gradient)
    },
}

def circularity(cnt):
    a = cv2.contourArea(cnt)
    p = cv2.arcLength(cnt, True)
    return 0.0 if p < 1 else 4 * np.pi * a / (p * p)

def verify_stamp_color(crop, stamp_class):
    # 1) mask màu theo class
    # 2) morph close 5x5 → contours
    # 3) cổng HÌNH: circle | rect
    # 4) cổng DIỆN TÍCH + đường kính
    # 5) reject nếu chỉ là blob nhỏ / chữ in / vệt lề
    # Trả detected chỉ khi VƯỢT CẢ 3 cổng (màu + hình + diện tích)
```
Gán `stamp_class` ngay trong zone resolver (Tầng 3b), không suy từ role.lower() chứa chữ "siêu thị":
- `HOA_DON` + role chứa "Con dấu mộc đỏ" / "Người bán" overlap mộc → `COMPANY_ROUND_RED`
- `HOA_DON` + system ∈ `{MT_COOP, MT_GS25, MT_SATRA, MT_BIGC, MT_BHX}` + role mộc tiếp nhận → `SUPERMARKET_SQUARE`
- `LOADING_PLAN` → không có target mộc đỏ công ty. Đừng bịa thêm.

---

### SỬA 4 — Engine B photocopy: cấm max_area > 350 ⇒ mộc
- **Sai:**
```python
if stamp_components > 0 or max_area > 350 or total_stroke_area > 500:
    detected = True
    ink_type = "bw_stamp_border"
```
Trên bản photo, đường kẻ bảng / khối chữ in / vệt lề đều > 350 px → False Accept hàng loạt.
- **Đúng — photo mộc chỉ đạt khi có VIỀN KHÉP:**
```python
def verify_stamp_bw(crop, stamp_class):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # không dùng threshold diện tích thô
    edges = cv2.Canny(gray, 40, 120)
    # vòng tròn: HoughCircles (minR/maxR theo ROI)
    # vuông: findContours trên morph gradient, approxPolyDP 4 đỉnh, độ đặc > 0.7
    # connected component bên TRONG viền phải có "mực" (chữ trong mộc), không phải khung rỗng in sẵn
    # reject component cao < 22px (font in '(Ký, ghi rõ họ tên)')
```
Photocopy đạt mộc → `DAT_CHUAN_PHOTO`. Không bao giờ gắn `DAT_CHUAN_GOC` cho `PHOTOCOPY_BW` (SOP KIDO: nghiệm thu gốc phải có mộc đỏ sống — giữ nguyên luật này, chỉ ghi chú trên UI web).

---

### SỬA 5 — Cấm fallback BW khi đang kiểm MỘC ĐỎ trên tài liệu MÀU
- **Sai (Cell 8 Tầng 4 cũ):**
```python
if is_color:
    res = verify_color_roi(...)
    if not res["detected"]:
        bw_res = verify_bw_roi(...)   # bảng kẻ / chữ in → "black_ink_on_color_doc" = ĐẠT ẢO
```
Fallback BW chỉ hợp lệ với chữ ký (bút đen trên scan màu). Với mộc đỏ pháp nhân trên tài liệu `TRUE_COLOR`: không có đỏ → THIẾU MỘC. Không được cứu bằng viền đen.
```python
def verify_single_target(img, target, is_color=True):
    is_stamp = target.get("expected_color") in ("red_stamp", "any_stamp") or target.get("stamp_class")
    margin = STAMP_MARGIN if is_stamp else SIG_MARGIN
    crop, bbox = extract_safe_roi(img, target["box_norm"], margin)
    if crop is None:
        return {"detected": False, "confidence": 0.0, "ink_type": "none", "reason": "ROI_TOO_SMALL"}
    
    if is_stamp:
        if is_color:
            res = verify_stamp_color(crop, target.get("stamp_class", "COMPANY_ROUND_RED"))
            # KHÔNG fallback BW
        else:
            res = verify_stamp_bw(crop, target.get("stamp_class", "COMPANY_ROUND_RED"))
    else:
        # chữ ký: giữ Engine A rồi fallback Engine B (bút đen) như cũ
        ...
```

---

### SỬA 6 — Verdict phải tôn trọng required=False (WinMart Row 33)
- **Sai:**
```python
req_count = len(targets)          # đếm cả ô miễn trừ
det_count = sum(vt["detected"] for vt in verified_targets)
if det_count == req_count: DAT_CHUAN_...
```
WinMart (`Hoadon_3.6__0`, `Hoadon2.2__2`) sẽ `THIEU_MOT_SO_CHU_KY` oan vì người mua không ký trên HĐ.
- **Đúng — bắt buộc dùng evaluate_document_verdict của Tầng 3 ver 2:**
```python
v = evaluate_document_verdict(
    target_results,
    mapping_status=zone["status"],
    doc_type=s2["doc_type"],
)
# Chỉ đếm target required=True
# Optional miss → không hạ DAT
# PAGE_1_NO_SIGNATURES → TRANG_1_CHUA_KY (HỢP LỆ)
```

**Ma trận SOP khóa cứng (không suy diễn):**

| system | Người mua | Mộc vuông ST | Mộc đỏ / ký số KIDO |
|---|---|---|---|
| MT_COOP / MT_GS25 / MT_SATRA / MT_BIGC | required | required `SUPERMARKET_SQUARE` | required `COMPANY_ROUND_RED` |
| MT_WINMART | required=False | không có | required |
| MT_AEON / MT_LOTTE / MT_EMART | required | không có | required |
| MT_BHX | miễn trừ trên HĐ | required (thủ kho DC) | required |
| GT | required (Đại diện NPP) | không có | required |

---

### SỬA 7 — Phạm vi chạy + hợp đồng abstain cho web
Chỉ duyệt file có `doc_type ∈ {LOADING_PLAN, HOA_DON}`.
32 ảnh còn lại (PO, PGH, PXK, BBBG, Lệnh điều xe, nhiệt độ, thu hồi, nợ/trả…):
```json
{
  "doc_status": "CHUA_CHUAN_HOA_VUNG_KY",
  "action": "ABSTAIN",
  "reason": "Template chưa có zone động Tầng 3b — không chạy Tầng 4"
}
```
Web MVP filter doc_type 2 loại này. Nút "xem PO" chỉ hiện badge chưa chuẩn hóa, không vẽ BBox giả.
Tầng 3 batch vẫn nạp để group theo `batch_id` / kênh trên UI. Tầng 4 chỉ ghi đè `verification_summary` của 40 ảnh đã map.

---

### SỬA 8 — Contract JSON Tầng 4 (web đọc đúng 1 file)
Xuất `output/stage4_out/stage4_verification_manifest.json`:
```json
{
  "version": "2.0.0-stamp-geometry",
  "scope": ["LOADING_PLAN", "HOA_DON"],
  "n_documents_in_scope": 40,
  "n_documents_abstain": 32,
  "documents": [
    {
      "file_name": "Hoa_don_3.8__0.png",
      "doc_type": "HOA_DON",
      "system": "MT_GS25",
      "page_role": "HEADER",
      "modality": "PHOTOCOPY_BW",
      "zone_status": "FLOATING_BELOW_TABLE",
      "anchor_y": 0.56,
      "doc_status": "DAT_CHUAN_PHOTO",
      "required_targets": 3,
      "detected_required_targets": 3,
      "targets": [
        {
          "role": "Mộc tiếp nhận siêu thị",
          "stamp_class": "SUPERMARKET_SQUARE",
          "expected_color": "any_stamp",
          "required": true,
          "box_norm": [0.56, 0.10, 0.70, 0.42],
          "bbox_px": [1232, 160, 1540, 672],
          "detected": true,
          "confidence": 0.88,
          "ink_type": "bw_square_border",
          "reason": "viền chữ nhật khép, aspect=1.21, ink_px=2140"
        }
      ]
    }
  ]
}
```
Cấm serialize `red_mask` / `fg_mask` numpy vào JSON.
CSV kế toán: 1 dòng / target, cột `required`, `stamp_class`, `reason`, `abstain`.

---

## 2. Bộ nghiệm thu bắt buộc (fail 1 ca = chưa được phép web)

Chạy đúng 8 ca này, in bảng PASS/FAIL. Không được "ước lượng":

| # | File | Kỳ vọng | Cấm |
|---|---|---|---|
| 1 | `Hoadon_2.1__0.png` (GT, chưa ký) | `CHUA_KY_DONG_DAU` ; ROI người mua trắng, X $\ge$ 0.08 | Đạt ảo vì liếm lề photo |
| 2 | `Hoadon3.11__0.png` (Satra liên 1) | `THIEU_MOT_SO_CHU_KY` (chỉ KIDO) | Đạt đủ 3/3 |
| 3 | `Hoa_don_3.8__0.png` / `__1.png` (GS25 bảng ngắn) | Bắt mộc vuông CJ Logistics, `anchor_y ≈ 0.55` | BBox Y=0.78–0.95 liếm chữ FPT |
| 4 | `Hoadon_3.6__0.png` (WinMart) | Người mua `required=False` ; vẫn DAT nếu KIDO + mộc đỏ đủ | Rớt vì thiếu chữ ký người mua |
| 5 | `Hoadon2.2__0.png` (mộc đè chữ ký) | Tách được lớp đỏ và lớp xanh ; mộc COMPANY_ROUND_RED circularity $\ge$ 0.65 | `red_px > 60` là đủ |
| 6 | `Hoadon_3.2__0.png` (photo Co.op) | `DAT_CHUAN_PHOTO` chỉ khi có viền mộc khép | `max_area > 350` |
| 7 | `Load_3.5__1.png` (LP Trang 1) | `TRANG_1_CHUA_KY` (HỢP LỆ), 0 BBox | Khung đè dòng kem |
| 8 | `Load_3.5__0.png` (LP Trang 2) | `anchor_y ∈ [0.08, 0.35]`, ôm 5 cột ký | Fallback Y=0.62 giấy trắng |

**Thêm 2 cổng âm:**
- Không target `COMPANY_ROUND_RED` nào được `detected=True` chỉ vì `blue_px`.
- Không file `doc_type ∉ {LOADING_PLAN, HOA_DON}` nào có `doc_status` khác `CHUA_CHUAN_HOA_VUNG_KY`.

---

## 3. Việc KHÔNG làm ở vòng này

- Không viết detector mộc cho PO / PGH / PXK / BBBG / Lệnh điều xe.
- Không train model, không YOLO, không SAM. Rule-based HSV + Hough/contour trên ROI đã neo.
- Không nhị phân hóa ảnh gốc (giữ 3 kênh — Tầng 1 đã cam kết).
- Không `%matplotlib inline`.
- Không `fn.startswith("Load_")` / regex tên file. Zone chỉ nhận `doc_type`, `page_role`, `system` từ Tầng 2.
- Không đổi `evaluate_document_verdict` theo hướng "đếm mọi target".
- Không serve web cho đến khi 8 ca nghiệm thu PASS.

---

## 4. Thứ tự cell notebook `ocr-tang4-stamp-ver2.ipynb`

1. **Cell 0 (Markdown):** Chính toàn bộ nội dung kế hoạch sửa này.
2. **Cell 1 (Code):** Import + nạp `stage2_classified_results.json` + `stage3_batched_manifest.json` (chỉ để lấy `batch_id`).
3. **Cell 2 (Code):** Patch `extract_safe_roi` + `verify_stamp_color` + `verify_stamp_bw` + `verify_single_target` (Sửa 2–5).
4. **Cell 3 (Code):** Runner 40 ảnh in-scope + 32 abstain (Sửa 1, 6, 7).
5. **Cell 4 (Code):** Bảng nghiệm thu 8 ca (Sửa 8 / mục 2) — assert hoặc in bảng PASS/FAIL chuẩn tắc.
6. **Cell 5 (Code):** Visual Crop inspector: 1 hàng = 1 target mộc (ảnh ROI \| mask màu \| overlay hình học \| verdict).
7. **Cell 6 (Code):** Xuất JSON/CSV contract (`stage4_verification_manifest.json` và `stage4_audit_summary.csv`).
