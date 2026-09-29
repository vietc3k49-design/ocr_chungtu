"""
TẦNG 4 — VER 2: ENGINE KIỂM MỘC & CHỮ KÝ CHUẨN HÌNH HỌC
========================================================

Module lõi được TÁCH RA từ chuỗi Python nhúng trong `tools/generate_nb4_ver2.py`
(Cell 2 của `ocr-tang4-stamp-ver2.ipynb`).

Mục đích: triệt tiêu nguồn sự thật trùng lặp — generator và notebook nay
`import` từ đây thay vì nhúng lại code dưới dạng chuỗi.

KHÔNG đổi thuật toán, KHÔNG đổi ngưỡng so với bản nhúng trong generator,
NGOẠI TRỪ một sửa lỗi tường minh đã được yêu cầu:

  * FIX-C — bỏ silent fallback `STAMP_CLASS.get(name, COMPANY_ROUND_RED)`.
    Khi không xác định được lớp mộc, engine KHÔNG đoán về mộc tròn đỏ nữa mà
    trả `detected=False` + `evidence="STAMP_CLASS_UNRESOLVED"` +
    `review_required=True`.

Khác biệt cốt lõi so với v1 (`tools/stage4_verifier.py` — PHẢI GIỮ NGUYÊN):
  - ROI clamp cứng SAFE_X/SAFE_Y thay cho margin 15% liếm lề.
  - Engine mộc màu đi qua 3 cổng: màu + HÌNH HỌC + diện tích.
  - Engine photo B/W bắt buộc có viền khép kín + inner_ink + valid_text_comps.
  - CẤM fallback chéo giữa color-engine và bw-engine.

Nguồn sự thật cho zone động vẫn là Tầng 3b (`tools/kido_pipeline.py`).
Module này chỉ NHẬN `targets[]` và trả phán quyết từng vị trí.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np

__all__ = [
    "SAFE_X",
    "SAFE_Y",
    "STAMP_MARGIN",
    "SIG_MARGIN",
    "STAMP_CLASS",
    "REVIEW_REQUIRED_EVIDENCE",
    "extract_safe_roi",
    "circularity",
    "resolve_stamp_class",
    "verify_stamp_color",
    "verify_stamp_bw",
    "verify_signature",
    "SIG_CFG",
    "verify_single_target",
    "evaluate_document_verdict_v2",
    "ABSTAIN_NO_REQUIRED_STATUS",
    "REVIEW_REQUIRED_STATUS",
    "REVIEW_REQUIRED_ACTION",
]

# =============================================================================
# SỬA 2 — Cấm Margin 15% Liếm Lề, Clamp Cứng SAFE_X >= 0.08
# =============================================================================
SAFE_X = (0.08, 0.96)
SAFE_Y = (0.02, 0.97)
STAMP_MARGIN = 0.08
# Phase 4 (27/09): chữ ký đo trong BOX CHẶT — margin 12% cũ kéo mực xanh cột bên + hàng
# "Tổng cộng" vào ROI (AUC đặc trưng tụt 0.07–0.12). Xem ghi chú trên verify_signature.
SIG_MARGIN = 0.0

REVIEW_REQUIRED_EVIDENCE = "STAMP_CLASS_UNRESOLVED"


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


# =============================================================================
# SỬA 3 — Engine A Mộc Màu: Cấm Đếm Pixel Thô, Bắt Buộc Qua Cổng Hình Học Mộc
# =============================================================================
STAMP_CLASS = {
    "COMPANY_ROUND_RED": {
        "hsv": [([0, 50, 40], [14, 255, 255]), ([165, 50, 40], [180, 255, 255])],
        "shape": "circle",
        "min_diameter_ratio": 0.22,
        "max_diameter_ratio": 0.95,
        "min_ink_px": 400,
        "allow_blue_purple": False,
    },
    "SUPERMARKET_SQUARE": {
        "hsv": [
            ([0, 50, 40], [14, 255, 255]),
            ([165, 50, 40], [180, 255, 255]),
            ([90, 40, 40], [145, 255, 255]),   # xanh
            ([130, 40, 40], [165, 255, 255]),  # tím
        ],
        "shape": "rect",
        "min_side_ratio": 0.20,
        "min_ink_px": 350,
        "allow_blue_purple": True,
        "need_closed_border": True,
    },
}


def _unresolved_stamp_class(stamp_class_name, mask=None):
    """FIX-C: không đoán bừa về mộc tròn đỏ khi không xác định được lớp mộc."""
    return {
        "detected": False,
        "confidence": 0.0,
        "ink_type": "unknown",
        "reason": (
            f"Không xác định được lớp mộc (stamp_class={stamp_class_name!r}) — "
            f"chuyển người kiểm tra thay vì mặc định về mộc tròn đỏ"
        ),
        "evidence": REVIEW_REQUIRED_EVIDENCE,
        "review_required": True,
        "mask": mask,
    }


def resolve_stamp_class(target):
    """Xác định lớp mộc TƯỜNG MINH từ target. Trả None nếu không xác định được.

    FIX-C: thay cho `STAMP_CLASS.get(name, "COMPANY_ROUND_RED")` — không có
    nhánh mặc định âm thầm nào.
    """
    name = target.get("stamp_class")
    if name:
        return name if name in STAMP_CLASS else None
    exp = target.get("expected_color")
    if exp == "any_stamp":
        return "SUPERMARKET_SQUARE"
    if exp == "red_stamp":
        return "COMPANY_ROUND_RED"
    return None


def circularity(cnt):
    a = cv2.contourArea(cnt)
    p = cv2.arcLength(cnt, True)
    return 0.0 if p < 1 else 4 * np.pi * a / (p * p)


def verify_stamp_color(crop, stamp_class_name):
    cfg = STAMP_CLASS.get(stamp_class_name)
    if cfg is None:
        return _unresolved_stamp_class(stamp_class_name)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h_crop, w_crop = crop.shape[:2]
    min_dim = min(h_crop, w_crop)

    # 1. Trích mask màu theo cấu hình mộc
    masks = []
    for lower, upper in cfg["hsv"]:
        m = cv2.inRange(hsv, np.array(lower), np.array(upper))
        masks.append(m)
    color_mask = masks[0]
    for m in masks[1:]:
        color_mask = color_mask | m

    ink_px = int(np.sum(color_mask > 0))
    if ink_px < cfg["min_ink_px"]:
        return {
            "detected": False,
            "confidence": 0.0,
            "ink_type": "none",
            "reason": f"Mực màu {stamp_class_name} quá ít ({ink_px} < {cfg['min_ink_px']} px)",
            "evidence": "TOO_FEW_COLOR_PIXELS",
            "mask": color_mask
        }

    # Cổng âm: Tuyệt đối CẤM nhận chữ ký xanh là mộc đỏ công ty
    if not cfg["allow_blue_purple"]:
        blue_mask = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([145, 255, 255]))
        red1 = cv2.inRange(hsv, np.array([0, 50, 40]), np.array([14, 255, 255]))
        red2 = cv2.inRange(hsv, np.array([165, 50, 40]), np.array([180, 255, 255]))
        actual_red_px = int(np.sum((red1 | red2) > 0))
        if actual_red_px < cfg["min_ink_px"]:
            return {
                "detected": False,
                "confidence": 0.0,
                "ink_type": "unexpected_blue_ink",
                "reason": f"Mộc đỏ không đủ pixel đỏ ({actual_red_px} px), từ chối nhận nhầm chữ ký xanh",
                "evidence": "UNEXPECTED_BLUE_INK_REJECTED",
                "mask": color_mask
            }

    # 2. Morph close để gom nét mộc thành contour khép kín
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return {
            "detected": False, "confidence": 0.0, "ink_type": "none",
            "reason": "Không tìm thấy contour mộc", "evidence": "NO_CONTOURS",
            "mask": color_mask
        }

    shape_target = cfg["shape"]

    if shape_target == "circle":
        # HoughCircles HOẶC contour circularity >= 0.65
        best_circ = 0.0
        best_cnt = None
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 300:
                continue
            c = circularity(cnt)
            if c > best_circ:
                best_circ = c
                best_cnt = cnt

        circles = cv2.HoughCircles(
            closed, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min_dim // 3,
            param1=50, param2=20,
            minRadius=int(min_dim * cfg["min_diameter_ratio"] / 2),
            maxRadius=int(min_dim * cfg["max_diameter_ratio"] / 2)
        )
        hough_found = circles is not None and len(circles) > 0

        passed_shape = False
        reason = ""
        if best_circ >= 0.65:
            eq_diameter = 2 * np.sqrt(cv2.contourArea(best_cnt) / np.pi)
            ratio = eq_diameter / float(min_dim)
            if cfg["min_diameter_ratio"] <= ratio <= cfg["max_diameter_ratio"]:
                passed_shape = True
                reason = f"Mộc tròn đạt chuẩn contour (circ={best_circ:.2f}>=0.65, ratio={ratio:.2f}, ink={ink_px}px)"

        if not passed_shape and hough_found:
            r = circles[0][0][2]
            ratio = (2 * r) / float(min_dim)
            if cfg["min_diameter_ratio"] <= ratio <= cfg["max_diameter_ratio"]:
                passed_shape = True
                reason = f"Mộc tròn đạt chuẩn HoughCircles (r={r:.1f}, ratio={ratio:.2f}, ink={ink_px}px)"

        if passed_shape:
            return {
                "detected": True,
                "confidence": min(1.0, 0.75 + ink_px / 1500.0),
                "ink_type": "red_round_stamp",
                "reason": reason,
                "evidence": "ROUND_STAMP_CONFIRMED",
                "mask": color_mask
            }
        else:
            return {
                "detected": False,
                "confidence": 0.2,
                "ink_type": "unstructured_red_ink",
                "reason": f"Mực đỏ chưa đủ hình học mộc tròn (circ={best_circ:.2f}, hough={hough_found})",
                "evidence": "SHAPE_REJECTED",
                "mask": color_mask
            }

    elif shape_target == "rect":
        # minAreaRect / convex hull: 0.50 <= aspect <= 2.35, side_ratio >= 0.20
        best_rect_match = False
        reason = ""
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 300:
                continue
            rect = cv2.minAreaRect(cnt)
            (rx, ry), (rw, rh), angle = rect
            if rw == 0 or rh == 0:
                continue
            aspect = max(rw, rh) / min(rw, rh)
            min_side = min(rw, rh)
            side_ratio = min_side / float(min_dim)
            hull = cv2.convexHull(cnt)
            hull_solidity = cv2.contourArea(hull) / float(rw * rh) if rw * rh > 0 else 0

            if 0.50 <= aspect <= 2.35 and side_ratio >= cfg["min_side_ratio"] and (hull_solidity >= 0.65 or area >= 1500):
                best_rect_match = True
                reason = f"Mộc tiếp nhận đạt chuẩn hình học (aspect={aspect:.2f}, side_ratio={side_ratio:.2f}, ink={ink_px}px)"
                break

        if best_rect_match:
            return {
                "detected": True,
                "confidence": min(1.0, 0.70 + ink_px / 1200.0),
                "ink_type": "supermarket_square_stamp",
                "reason": reason,
                "evidence": "SQUARE_STAMP_CONFIRMED",
                "mask": color_mask
            }
        else:
            return {
                "detected": False,
                "confidence": 0.2,
                "ink_type": "unstructured_stamp_ink",
                "reason": f"Mực tiếp nhận chưa đủ hình học mộc vuông (ink={ink_px}px)",
                "evidence": "SHAPE_REJECTED",
                "mask": color_mask
            }

    # Hình dạng lạ — không đoán
    return _unresolved_stamp_class(stamp_class_name, mask=color_mask)


# =============================================================================
# SỬA 4 — Engine B Photocopy: Cấm max_area > 350 => Mộc, Bắt Buộc Có Viền Khép
# =============================================================================
def verify_stamp_bw(crop, stamp_class_name):
    cfg = STAMP_CLASS.get(stamp_class_name)
    if cfg is None:
        return _unresolved_stamp_class(stamp_class_name)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h_crop, w_crop = crop.shape[:2]
    min_dim = min(h_crop, w_crop)

    edges = cv2.Canny(gray, 40, 120)
    shape_target = cfg["shape"]

    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8)

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh)
    inner_ink_px = 0
    valid_text_comps = 0
    for i in range(1, n_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        ch = stats[i, cv2.CC_STAT_HEIGHT]
        cw = stats[i, cv2.CC_STAT_WIDTH]
        if area > 10 and (ch < h_crop * 0.90 and cw < w_crop * 0.90):
            inner_ink_px += area
            if ch >= 12:
                valid_text_comps += 1

    if inner_ink_px < 300:
        return {
            "detected": False,
            "confidence": 0.0,
            "ink_type": "none",
            "reason": f"Bản photo không đủ mực trong mộc ({inner_ink_px} < 300 px)",
            "evidence": "NO_INNER_INK",
            "mask": thresh
        }

    if shape_target == "circle":
        circles = cv2.HoughCircles(
            edges, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min_dim // 3,
            param1=50, param2=25,
            minRadius=int(min_dim * cfg["min_diameter_ratio"] / 2),
            maxRadius=int(min_dim * cfg["max_diameter_ratio"] / 2)
        )
        if circles is not None and len(circles) > 0 and valid_text_comps >= 2:
            r = circles[0][0][2]
            return {
                "detected": True,
                "confidence": 0.85,
                "ink_type": "bw_round_stamp_border",
                "reason": f"Phát hiện viền mộc tròn khép kín photo (r={r:.1f}, inner_ink={inner_ink_px}px)",
                "evidence": "BW_ROUND_STAMP_CONFIRMED",
                "mask": thresh
            }

    # Mộc chữ nhật / vuông tiếp nhận
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    gradient = cv2.morphologyEx(thresh, cv2.MORPH_GRADIENT, kernel)
    contours_grad, _ = cv2.findContours(gradient, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed_th = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, k_close)
    contours_closed, _ = cv2.findContours(closed_th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in list(contours_grad) + list(contours_closed):
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 60 or h < 30:
            continue
        rect = cv2.minAreaRect(cnt)
        (rx, ry), (rw, rh), angle = rect
        if rw == 0 or rh == 0:
            continue
        aspect = max(rw, rh) / min(rw, rh)
        min_side = min(rw, rh)
        side_ratio = min_side / float(min_dim)
        hull = cv2.convexHull(cnt)
        hull_solidity = cv2.contourArea(hull) / float(rw * rh) if rw * rh > 0 else 0

        if 0.50 <= aspect <= 2.35 and side_ratio >= 0.20 and hull_solidity >= 0.70:
            if valid_text_comps >= 1 and inner_ink_px >= 350:
                return {
                    "detected": True,
                    "confidence": 0.88,
                    "ink_type": "bw_square_stamp_border",
                    "reason": f"Viền chữ nhật mộc khép kín photo (aspect={aspect:.2f}, side_ratio={side_ratio:.2f}, inner_ink={inner_ink_px}px)",
                    "evidence": "BW_SQUARE_STAMP_CONFIRMED",
                    "mask": thresh
                }

    return {
        "detected": False,
        "confidence": 0.2,
        "ink_type": "none",
        "reason": f"Bản photo không có viền mộc khép kín hợp lệ",
        "evidence": "BW_STAMP_BORDER_NOT_FOUND",
        "mask": thresh
    }


# =============================================================================
# Engine Chữ Ký (Signature)
# =============================================================================
# -----------------------------------------------------------------------------
# ❌ THỰC NGHIỆM ĐÃ THỬ VÀ BỊ LOẠI (27/09) — ĐỪNG THỬ LẠI HƯỚNG NÀY
# -----------------------------------------------------------------------------
# GIẢ THUYẾT: FP của ver2 sinh ra vì hai lý do — (a) `adaptiveThreshold` thô
# khuếch đại chữ in mờ và vân giấy thành connected component giả, (b) ngưỡng là
# pixel TUYỆT ĐỐI nên không scale theo kích thước ROI. Sửa hai điều đó — thay
# bằng ink-mask theo nền `gray < median-35` + `MORPH_OPEN` giống v1, và quy đổi
# toàn bộ ngưỡng sang TỈ LỆ diện tích/chiều ROI — thì Precision sẽ tăng.
#
# ĐÃ LÀM THẬT, ĐÃ ĐO THẬT. Lý lẽ đúng, kết quả sai.
#
#   A/B trên 70 signature target của zone ĐỘNG LOADING_PLAN, GT gán nhãn bằng
#   mắt (`tools/ab_v2_signature_fix.py`, `output/stage4_out/stage4_v2_signature_ab.json`):
#
#     | bản                       | TP | TN | FP | FN | Precision | Recall |
#     |---------------------------|----|----|----|----|-----------|--------|
#     | CŨ (adaptiveThreshold)    | 43 | 15 | 11 |  1 | 79.63%    | 97.73% |
#     | MỚI (ink-mask + tỉ lệ)    | 44 |  0 | 26 |  0 | 62.86%    | 100.0% |
#
#   16 target đổi phán quyết: **15 xấu đi, 1 tốt lên**. Precision −16.77 điểm.
#   Trên bộ hộp TĨNH còn tệ hơn: LOADING_PLAN Precision 65.22% -> 46.88%.
#
# VÌ SAO: ink-mask `gray < median(gray) - 35` nhạy hơn adaptiveThreshold trên
# đúng loại ROI hay gặp ở đây — ô ký TRỐNG chỉ có chữ in sẵn. Nền ô trống gần
# như trắng tuyệt đối nên median cao, ngưỡng `median-35` vẫn bắt trọn chữ in,
# rồi `MORPH_OPEN (2,2)` nối chúng thành khối đủ lớn vượt cổng. 14/14 ô
# "Trưởng BP Kho" (luôn trống) bị bản mới chấm PRESENT — TN tụt về 0.
#
# PHẦN GIỮ LẠI: bản mới ĐÚNG về mặt bất biến tỉ lệ — `tools/test_v2_signature_unit.py`
# CA 11 chứng minh bản cũ sinh FP ở scale 3.0x còn bản mới thì không. Nhưng
# contract hiện tại cố định ảnh A4 ở H=2200 nên scale 3x KHÔNG BAO GIỜ xảy ra
# trong sản xuất. Đổi 16.77 điểm Precision thật lấy một tính chất không dùng
# đến là lỗ vốn. Nếu sau này contract resize thay đổi, đọc lại mục này trước.
#
# ⚠️ FP CÒN LẠI KHÔNG PHẢI LỖI ENGINE NÀY. Theo vai trò, FP tập trung tuyệt đối
# ở 2 cột: "Người nhận hàng" (10 FP) và "Trưởng BP Kho" (9 FP); 3 vai trò còn
# lại 0 FP. Hai cột đó thực tế LUÔN TRỐNG, mực nằm trong ROI là chữ ký của cột
# BÊN CẠNH tràn sang do ranh giới cột của zone động Tầng 3b đặt lệch trái.
# Mực có thật trong ROI — không ngưỡng detector nào phân biệt được. Chỗ phải
# sửa là hình học cột trong `kido_pipeline.detect_loading_plan_signature_zone`,
# KHÔNG phải hàm dưới đây.
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# THIẾT KẾ LẠI 27/09 (Phase 4) — engine chữ ký BẤT BIẾN TỈ LỆ, đo trong BOX CHẶT
# -----------------------------------------------------------------------------
# Nguyên nhân gốc đã xác minh (scratch/_phase4/rootcause/REPORT.md): trên đường
# production (ảnh Tầng 1 H=2200, upscale ~x2.6 so với ảnh gốc) cả v1 lẫn bản
# `verify_signature` cũ cho TN=0 vì:
#   (1) ngưỡng PIXEL TUYỆT ĐỐI (`blue_px>40`, `area>120`, `max_stroke_area>=150`,
#       lọc kẻ `ch<=3`) — diện tích tăng x6.8 khi upscale;
#   (2) chữ in sẵn đen bắn cổng nét 23/23 ô chưa ký;
#   (3) đường kẻ bảng dày 4–6px thoát lọc `ch<=3`;
#   (4) SIG_MARGIN 12% kéo mực xanh cột bên + hàng "Tổng cộng" vào ROI.
#
# Thiết kế mới (mọi ngưỡng là ĐƠN VỊ VẬT LÝ mm / mm² quy đổi qua px_per_mm):
#   * px_per_mm lấy từ ẢNH LÀM VIỆC: cạnh dài trang / 297 mm (A4). Gọi trực tiếp
#     không có ảnh trang (unit test) thì suy từ chiều cao ROI với giả định ô ký
#     cao SIG_CFG["ref_cell_height_mm"] — ghi rõ trong kết quả `scale_source`.
#   * ROI = box chặt (SIG_MARGIN = 0.0): box_norm đã là ô cột do Tầng 3b dựng;
#     margin chỉ kéo mực/đường kẻ của ô khác vào.
#   * Ảnh MÀU: bằng chứng chính là MỰC XANH (định nghĩa màu HSV giữ nguyên như
#     v1/ver2, không dò lại). Chữ in sẵn đen/xám KHÔNG bao giờ được tính.
#       - bỏ đốm xanh < min_blue_cc_mm2 (nhiễu sắc độ JPEG);
#       - gom cụm nét cách nhau <= cluster_link_mm (một chữ ký là một cụm nét);
#       - cụm có TÂM nằm trong dải biên trái/phải side_gutter_frac của ô là mực
#         TRÀN từ cột bên (người ký ký dưới nhãn của mình, tức vùng giữa ô) —
#         không tính là chữ ký của ô này;
#       - chữ ký của ô = tổng mực các cụm còn lại >= min_sig_ink_mm2.
#   * Không có mực xanh của ô ⇒ nhánh NÉT TỐI (bút đen): tách đường kẻ dài theo
#     TỈ LỆ ô (open với kernel line_len_frac), bỏ thành phần thấp hơn
#     min_stroke_height_mm (chiều cao chữ in 10–12pt + dấu ~<= 4.5 mm), bỏ thành
#     phần dạng vạch thẳng (cạnh ngắn bbox <= line_max_thickness_mm), bỏ thành phần
#     chạm mép TRÊN/DƯỚI ô (mép trên ô = chân bảng do Tầng 3b neo; nội dung chạm nó
#     là của hàng bảng — quy tắc này THÊM SAU khi thấy 1 FP trên tập đánh giá
#     `Load_3.6__0__T03`, số "51" in cỡ lớn, xem REPORT), bỏ cụm ở dải biên. ⚠️ GT production KHÔNG có ô nào ký bằng bút đen ⇒ nhánh này CHỈ được
#     đo tỉ lệ báo nhầm trên ô chưa ký, Recall của nó CHƯA được kiểm chứng.
#   * Ảnh KHÔNG MÀU (BW/photo): không có GT nào trên đường production ⇒ không
#     tuyên bố hiệu quả. Chạy nhánh nét tối nhưng gắn `review_required=True` và
#     evidence `BW_*_UNVALIDATED` tường minh.
# -----------------------------------------------------------------------------
SIG_CFG = {
    # quy đổi tỉ lệ
    "a4_long_edge_mm": 297.0,
    "ref_cell_height_mm": 60.0,      # chỉ dùng khi không biết ảnh trang (ô ký LP ~ 0.20 x 297 mm)
    # màu mực xanh — GIỮ NGUYÊN định nghĩa của v1/ver2 (không dò)
    "blue_hsv_lo": (90, 40, 40),
    "blue_hsv_hi": (145, 255, 255),
    # nhánh mực xanh
    "min_blue_cc_mm2": 0.25,          # đốm < 0.5 x 0.5 mm: nhiễu sắc độ, không phải nét bút
    "cluster_link_mm": 1.5,           # khoảng hở giữa các nét của CÙNG một chữ ký
    "side_gutter_frac": 0.20,         # dải biên trái/phải ô: vùng mực tràn từ cột bên
    "min_sig_ink_mm2": 2.0,           # chữ ký tối thiểu: nét 10 mm x 0.2 mm (bi mảnh)
    # nhánh nét tối
    "dark_delta": 60,                 # mực tối hơn nền giấy (p90 xám) ít nhất 60 mức
    "line_len_frac": 0.30,            # vạch kẻ: đoạn thẳng >= 30% bề ngang/chiều cao ô
    "line_max_thickness_mm": 1.2,     # thành phần có cạnh ngắn bbox <= 1.2 mm là vạch
    "min_stroke_height_mm": 6.0,      # nét tay: cao >= 6 mm (> chữ in ~4.5 mm có dấu)
}

SIG_EVIDENCE_BLUE = "BLUE_SIGNATURE_DETECTED"
SIG_EVIDENCE_STROKE = "HANDWRITING_STROKE_DETECTED"
SIG_EVIDENCE_NONE = "NO_SIGNATURE_DETECTED"
SIG_EVIDENCE_EDGE_ONLY = "BLUE_INK_ONLY_AT_COLUMN_EDGE"
SIG_EVIDENCE_BW_STROKE = "BW_STROKE_DETECTED_UNVALIDATED"
SIG_EVIDENCE_BW_NONE = "BW_NO_STROKE_UNVALIDATED"
# Chữ ký ONLINE: hệ thống in sẵn họ tên người lập trên biểu mẫu. Bằng chứng RIÊNG,
# không trộn với chữ ký tay — xem config/stage4_lp_required_policy.json mục `ky_online`.
SIG_EVIDENCE_ESIGN = "E_SIGNATURE_PRINTED_NAME"


def _sig_result(detected, confidence, ink_type, reason, evidence, mask, **extra):
    r = {"detected": bool(detected), "confidence": float(confidence), "ink_type": ink_type,
         "reason": reason, "evidence": evidence, "mask": mask}
    r.update(extra)
    return r


def _clusters(mask01, link_px):
    """Gom thành phần của mask thành cụm (nối nếu hở <= link_px). Trả list
    (ink_px, centroid_x_frac, x0, y0, x1, y1) theo pixel mực GỐC (không tính phần giãn)."""
    h, w = mask01.shape
    k = max(1, int(round(link_px)))
    if k > 1:
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        grown = cv2.dilate(mask01, ker)
    else:
        grown = mask01
    n, lab = cv2.connectedComponents(grown, connectivity=8)
    out = []
    ys, xs = np.nonzero(mask01)
    if len(xs) == 0:
        return out
    labs = lab[ys, xs]
    for c in range(1, n):
        sel = labs == c
        if not sel.any():
            continue
        cx, cy = xs[sel], ys[sel]
        out.append((int(sel.sum()), float(cx.mean()) / w, int(cx.min()), int(cy.min()),
                    int(cx.max()) + 1, int(cy.max()) + 1))
    return out


def _drop_small_cc(mask01, min_px):
    if min_px <= 1:
        return mask01
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask01, connectivity=8)
    keep = np.zeros(n, dtype=np.uint8)
    keep[1:] = (st[1:, cv2.CC_STAT_AREA] >= min_px).astype(np.uint8)
    return keep[lab]


def _dark_strokes(crop, ppm, exclude01, cfg):
    """Nhánh nét tối, bất biến tỉ lệ. Trả (n_strokes, own_ink_mm2, max_h_mm, mask)."""
    h, w = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    paper = float(np.percentile(gray, 90))
    dark = (gray.astype(np.int16) < paper - cfg["dark_delta"]).astype(np.uint8)
    if exclude01 is not None:
        dark[exclude01 > 0] = 0
    # tách vạch kẻ dài theo tỉ lệ ô
    lh = max(3, int(round(w * cfg["line_len_frac"])))
    lv = max(3, int(round(h * cfg["line_len_frac"])))
    hl = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (lh, 1)))
    vl = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, lv)))
    lines = cv2.dilate(hl | vl, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    dark[lines > 0] = 0
    min_cc = max(1, int(round(cfg["min_blue_cc_mm2"] * ppm * ppm)))
    dark = _drop_small_cc(dark, min_cc)
    n, lab, st, cen = cv2.connectedComponentsWithStats(dark, connectivity=8)
    thin_px = cfg["line_max_thickness_mm"] * ppm
    min_h_px = cfg["min_stroke_height_mm"] * ppm
    g = cfg["side_gutter_frac"]
    n_str, ink, max_h = 0, 0, 0.0
    stroke_mask = np.zeros_like(dark)
    for i in range(1, n):
        bw_, bh_, a_ = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT], st[i, cv2.CC_STAT_AREA]
        if min(bw_, bh_) <= thin_px:          # vạch thẳng mảnh (ngang/dọc)
            continue
        y0_ = st[i, cv2.CC_STAT_TOP]
        if y0_ == 0 or y0_ + bh_ >= h:         # cắt qua mép trên/dưới ô: thuộc hàng bảng phía trên
            continue                          # (vd. số in cỡ lớn hàng "Tổng cộng") hoặc chữ in phía dưới
        if bh_ < min_h_px:                    # thấp như chữ in
            continue
        cxf = cen[i][0] / w
        if cxf < g or cxf > 1 - g:            # nằm ở dải biên: tràn từ cột bên
            continue
        n_str += 1
        ink += int(a_)
        max_h = max(max_h, bh_ / ppm)
        stroke_mask[lab == i] = 255
    return n_str, ink / (ppm * ppm), max_h, stroke_mask


def verify_signature(crop, is_color=True, px_per_mm=None, cfg=None):
    """Phán quyết 1 ô chữ ký. `px_per_mm` nên truyền từ ảnh trang (verify_single_target
    làm việc này); None ⇒ suy từ chiều cao ROI (giả định ô cao ref_cell_height_mm)."""
    cfg = SIG_CFG if cfg is None else cfg
    if crop is None or getattr(crop, "size", 0) == 0 or getattr(crop, "ndim", 0) != 3 \
       or crop.shape[0] < 3 or crop.shape[1] < 3:
        return _sig_result(False, 0.0, "none", "ROI rỗng hoặc quá nhỏ để phân tích",
                           SIG_EVIDENCE_NONE, None)
    h, w = crop.shape[:2]
    if px_per_mm is not None and px_per_mm > 0:
        ppm, scale_source = float(px_per_mm), "page_long_edge_a4"
    else:
        ppm, scale_source = h / cfg["ref_cell_height_mm"], "roi_height_ref_cell"
    mm2 = ppm * ppm
    g = cfg["side_gutter_frac"]
    diag = {"scale_source": scale_source, "px_per_mm": round(ppm, 4)}

    if is_color:
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue = (cv2.inRange(hsv, np.array(cfg["blue_hsv_lo"]), np.array(cfg["blue_hsv_hi"])) > 0).astype(np.uint8)
        blue = _drop_small_cc(blue, max(1, int(round(cfg["min_blue_cc_mm2"] * mm2))))
        cl = _clusters(blue, cfg["cluster_link_mm"] * ppm)
        own = [c for c in cl if g <= c[1] <= 1 - g]
        edge = [c for c in cl if not (g <= c[1] <= 1 - g)]
        own_mm2 = sum(c[0] for c in own) / mm2
        edge_mm2 = sum(c[0] for c in edge) / mm2
        diag.update({"blue_own_mm2": round(own_mm2, 3), "blue_edge_mm2": round(edge_mm2, 3),
                     "blue_clusters_own": len(own), "blue_clusters_edge": len(edge)})
        if own_mm2 >= cfg["min_sig_ink_mm2"]:
            return _sig_result(True, min(1.0, 0.60 + 0.40 * own_mm2 / (4 * cfg["min_sig_ink_mm2"])),
                               "blue_ink",
                               f"Chữ ký mực xanh trong ô ({own_mm2:.1f} mm² >= {cfg['min_sig_ink_mm2']} mm², "
                               f"{len(own)} cụm; bỏ {edge_mm2:.1f} mm² ở dải biên)",
                               SIG_EVIDENCE_BLUE, blue * 255, **diag)
        # Không đủ mực xanh của ô: thử nhánh nét tối (bút đen), loại mọi pixel xanh.
        n_str, ink_mm2, max_h, smask = _dark_strokes(crop, ppm, blue if blue.any() else None, cfg)
        diag.update({"dark_strokes": n_str, "dark_stroke_mm2": round(ink_mm2, 3),
                     "dark_stroke_max_h_mm": round(max_h, 2)})
        if n_str >= 1 and ink_mm2 >= cfg["min_sig_ink_mm2"]:
            return _sig_result(True, 0.60, "dark_ink_stroke",
                               f"Nét tay tối cao {max_h:.1f} mm ({n_str} nét, {ink_mm2:.1f} mm²) — nhánh bút "
                               f"đen CHƯA được kiểm chứng Recall trên GT",
                               SIG_EVIDENCE_STROKE, smask, dark_branch_unvalidated=True, **diag)
        if edge_mm2 >= cfg["min_sig_ink_mm2"]:
            return _sig_result(False, 0.0, "neighbor_blue_ink",
                               f"Chỉ có mực xanh ở dải biên ô ({edge_mm2:.1f} mm²) — coi là tràn từ cột bên",
                               SIG_EVIDENCE_EDGE_ONLY, blue * 255, **diag)
        return _sig_result(False, 0.0, "none",
                           f"Không có mực xanh của ô ({own_mm2:.1f} mm²) và không có nét tay tối",
                           SIG_EVIDENCE_NONE, blue * 255, **diag)

    # Ảnh không màu: không có GT production ⇒ chỉ báo kèm cờ kiểm tra tay.
    n_str, ink_mm2, max_h, smask = _dark_strokes(crop, ppm, None, cfg)
    diag.update({"dark_strokes": n_str, "dark_stroke_mm2": round(ink_mm2, 3),
                 "dark_stroke_max_h_mm": round(max_h, 2)})
    det = n_str >= 1 and ink_mm2 >= cfg["min_sig_ink_mm2"]
    return _sig_result(det, 0.5 if det else 0.0, "bw_stroke" if det else "none",
                       ("Ảnh không màu: " + (f"có nét tay tối cao {max_h:.1f} mm" if det else "không thấy nét tay")
                        + " — engine chữ ký BW CHƯA có GT, cần người kiểm tra"),
                       SIG_EVIDENCE_BW_STROKE if det else SIG_EVIDENCE_BW_NONE, smask,
                       review_required=True, **diag)


# =============================================================================
# Chữ ký ONLINE — chỉ cho vai trò được config cho phép (mặc định: Người lập phiếu)
# =============================================================================
try:
    from rapidfuzz import fuzz as _fuzz          # cùng thư viện Tầng 3b dùng cho nhãn cột
except ImportError:
    _fuzz = None

_KY_ONLINE_CACHE = None


def _nap_ky_online():
    """Đọc mục `ky_online` của chính sách LP. Không có mục ⇒ TẮT (trả None).

    Tắt là mặc định an toàn: không có luật thì không ai được hưởng, khác hẳn
    'dự phòng hardcode' mà dự án cấm.
    """
    global _KY_ONLINE_CACHE
    if _KY_ONLINE_CACHE is not None:
        return _KY_ONLINE_CACHE or None
    import json as _json
    p = Path(__file__).resolve().parents[1] / "config/stage4_lp_required_policy.json"
    cfg = None
    if p.is_file():
        try:
            k = _json.loads(p.read_text(encoding="utf-8")).get("ky_online")
            if k and k.get("bat"):
                cfg = k
        except Exception:
            cfg = None
    _KY_ONLINE_CACHE = cfg or {}
    return cfg


def _bo_dau_hoa(s):
    """NFD bỏ dấu + viết hoa. `đ/Đ` KHÔNG phân rã theo NFD nên phải thay tay —
    thiếu bước này thì "Quy đổi" ra "QUY ĐOI", không khớp chuỗi loại trừ "QUY DOI"
    và nhãn biểu mẫu bị nhận nhầm thành họ tên (đo 29/09: 2/2 ca sai đúng kiểu này)."""
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def _do_ten_in(img, box_norm, k):
    """OCR vùng ô (nới xuống dưới) tìm HỌ TÊN IN SẴN. Trả (ten, None) hoặc (None, ly_do).

    Nới ROI xuống dưới vì tên in nằm ở mép dưới ô, một phần lọt ra ngoài hộp đo mực
    (đo 29/09 trên Loading_Plan3.1__0). KHÔNG đụng vùng đo mực xanh.
    """
    try:
        import pytesseract
    except ImportError:
        return None, "OCR_UNAVAILABLE"
    H, W = img.shape[:2]
    y0, x0, y1, x1 = box_norm[0], box_norm[1], box_norm[2], box_norm[3]
    cao = y1 - y0
    y1 = min(1.0, y1 + cao * float(k.get("roi_mo_rong_duoi", 0.30)))
    crop = img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
    if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
        return None, "ROI_TOO_SMALL"
    loai_tru = [_bo_dau_hoa(t) for t in (k.get("chuoi_loai_tru") or [])]
    nguong_mo = float(k.get("nguong_loai_tru_mo", 80))
    min_tu = int(k.get("so_tu_toi_thieu", 2))
    min_chu = int(k.get("so_chu_cai_toi_thieu", 6))
    for psm in (k.get("ocr_psm") or [6]):
        try:
            txt = pytesseract.image_to_string(crop, lang="vie", config=f"--psm {int(psm)}")
        except Exception:
            return None, "OCR_UNAVAILABLE"
        for dong in (l.strip() for l in txt.splitlines()):
            if not dong:
                continue
            D = _bo_dau_hoa(dong)
            if any(lt in D for lt in loai_tru):
                continue
            # So khớp MỜ: OCR đọc sai chính tả nhãn in sẵn thì khớp chính xác trượt.
            if _fuzz is not None:
                if max((_fuzz.partial_ratio(D, lt) for lt in loai_tru), default=0) >= nguong_mo:
                    continue
            if any(ch.isdigit() for ch in dong):
                continue
            tu = [t for t in re.split(r"[^A-Za-zÀ-ỹ]+", dong) if len(t) >= 2]
            if len(tu) < min_tu:
                continue
            if sum(len(t) for t in tu) < min_chu:
                continue
            return " ".join(tu), None
    return None, "KHONG_THAY_TEN_IN"


# =============================================================================
# SỬA 5 — Cấm Fallback BW Khi Kiểm Mộc Đỏ Trên Tài Liệu Màu
# =============================================================================
def verify_single_target(img, target, is_color=True):
    is_stamp = target.get("expected_color") in ("red_stamp", "any_stamp") or target.get("stamp_class") is not None
    margin = STAMP_MARGIN if is_stamp else SIG_MARGIN
    crop, bbox = extract_safe_roi(img, target["box_norm"], margin)

    if crop is None:
        return {
            "detected": False,
            "confidence": 0.0,
            "ink_type": "none",
            "reason": "ROI_TOO_SMALL",
            "evidence": "INPUT_ERROR",
            "bbox_px": bbox,
            "mask": None
        }

    if is_stamp:
        # FIX-C: không còn nhánh mặc định âm thầm về COMPANY_ROUND_RED
        stamp_class = resolve_stamp_class(target)
        if stamp_class is None:
            res = _unresolved_stamp_class(target.get("stamp_class"))
            res["bbox_px"] = bbox
            return res
        if is_color:
            res = verify_stamp_color(crop, stamp_class)
        else:
            res = verify_stamp_bw(crop, stamp_class)
    else:
        # px/mm từ cạnh dài trang A4 của ảnh làm việc — ngưỡng chữ ký là mm, bất biến tỉ lệ
        ppm = max(img.shape[:2]) / SIG_CFG["a4_long_edge_mm"]
        res = verify_signature(crop, is_color=is_color, px_per_mm=ppm)

        # --- Chữ ký ONLINE: chỉ chạy khi KHÔNG tìm thấy chữ ký tay, và chỉ cho
        # vai trò được config cho phép. Không bao giờ ghi đè một kết luận "đã ký".
        k = _nap_ky_online()
        if k and not res.get("detected"):
            vai_tro = target.get("role") or ""
            if vai_tro in (k.get("label_roles") or []):
                ten, ly_do = _do_ten_in(img, target["box_norm"], k)
                if ten:
                    res.update({
                        "detected": True,
                        "confidence": 0.90,
                        "ink_type": "e_signature",
                        "evidence": SIG_EVIDENCE_ESIGN,
                        "reason": f"Ký online: hệ thống in sẵn họ tên “{ten}” trong ô "
                                  f"(không có mực tay). Chỉ áp cho vai trò trong "
                                  f"config ky_online.roles.",
                        "e_signature_name": ten,
                        "e_signature_prev_evidence": res.get("evidence"),
                    })
                else:
                    res["e_signature_checked"] = ly_do or "KHONG_THAY_TEN_IN"

    res["bbox_px"] = bbox
    return res


# =============================================================================
# Verdict cấp tài liệu (SỬA 6 — tôn trọng required=False)
# =============================================================================
ABSTAIN_NO_REQUIRED_STATUS = "CHUA_CHUAN_HOA_VUNG_KY"
# Có target bắt buộc mang review_required=True ⇒ chuyển người kiểm tra (xem verdict).
REVIEW_REQUIRED_STATUS = "CAN_KIEM_TRA_TAY"
REVIEW_REQUIRED_ACTION = "REVIEW_REQUIRED"


def evaluate_document_verdict_v2(verified_targets, is_color=True):
    """Trả (doc_status, action, reason). Chỉ tính trên các target required=True.

    [SỬA 27/09 — Giai đoạn 1a] Không có target required nào (danh sách rỗng
    hoặc toàn optional) ⇒ ABSTAIN, KHÔNG BAO GIỜ là CHUA_KY_DONG_DAU. Trước đây
    `req_targets == []` rơi vào nhánh `len(det_req) == 0` và bị phán "chưa ký"
    — tức kết luận về chữ ký từ một tập rỗng, trong khi thực chất Tầng 3b đã
    không dựng được vùng ký (vd. COLUMN_DETECTION_FAILED). Không có vị trí bắt
    buộc thì không có căn cứ để phán ký hay chưa ký.
    """
    req_targets = [vt for vt in verified_targets if vt.get("required", True)]
    det_req = [vt for vt in req_targets if vt.get("detected")]

    if not req_targets:
        return (ABSTAIN_NO_REQUIRED_STATUS, "ABSTAIN",
                f"NO_REQUIRED_TARGETS: {len(verified_targets)} target, 0 bắt buộc "
                "— không có căn cứ phán ký/chưa ký")

    # [Giai đoạn 4 — tích hợp 27/09] Cờ `review_required` của engine (nhánh ảnh BW
    # `BW_*_UNVALIDATED`, hoặc `STAMP_CLASS_UNRESOLVED`) nghĩa là phán quyết của ô đó
    # CHƯA được kiểm chứng trên GT. Chỉ cần MỘT target bắt buộc mang cờ này thì tài
    # liệu KHÔNG được kết luận "chưa ký / yêu cầu ký lại" (sẽ là kết luận từ engine
    # chưa kiểm chứng), và cũng KHÔNG được kết luận "đạt" vì cùng lý do. Trả trạng
    # thái kiểm tra tay tường minh; action dùng lại tên `REVIEW_REQUIRED` đã có trong
    # contract (kido_pipeline._VERDICT_ACTION, detection_status của v1).
    review_req = [vt for vt in req_targets if vt.get("review_required")]
    if review_req:
        roles = ", ".join(f"{vt.get('role')}[{vt.get('evidence')}]" for vt in review_req)
        return (REVIEW_REQUIRED_STATUS, REVIEW_REQUIRED_ACTION,
                f"REVIEW_REQUIRED_TARGETS: {len(review_req)}/{len(req_targets)} vị trí bắt buộc chưa có "
                f"engine đã kiểm chứng ({roles}); máy đếm được {len(det_req)}/{len(req_targets)} "
                "— cần người kiểm tra, không phán ký/chưa ký")

    if len(det_req) == len(req_targets):
        doc_status = "DAT_CHUAN_GOC" if is_color else "DAT_CHUAN_PHOTO"
        return doc_status, "DUYET", f"Đạt chuẩn tất cả {len(req_targets)} chữ ký/mộc bắt buộc"
    if len(det_req) == 0:
        return ("CHUA_KY_DONG_DAU", "YEU_CAU_KY_LAI",
                "Chưa phát hiện chữ ký hoặc con dấu bắt buộc nào")
    missing_roles = [vt.get("role") for vt in req_targets if not vt.get("detected")]
    return ("THIEU_MOT_SO_CHU_KY", "CANH_BAO",
            f"Thiếu {len(missing_roles)} vị trí bắt buộc: {', '.join(str(m) for m in missing_roles)}")
