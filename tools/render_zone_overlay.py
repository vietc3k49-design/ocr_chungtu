# -*- coding: utf-8 -*-
# >>> HISTORICAL-BANNER (Giai doan 5 cleanup)
# HISTORICAL — raw images, KHONG phan anh production.
# Cong cu nay doc anh goc output/form_samples (~850px) va/hoac box/GT cu
# (output/stage4_dynamic_gt/), trong khi production doc anh Tang 1 resize H=2200
# voi zone Tang 3b hien tai. So do cua file nay KHONG duoc dung de ket luan ve
# production (DINH CHINH AGENTS.md 9.10.D). Duong do hien hanh:
#   tools/lp_production_path.py -> tools/bench_lp_prod.py (GT output/stage4_dynamic_gt_v4/).
# <<< HISTORICAL-BANNER
"""
Vẽ đối chiếu hình học vùng ký LOADING_PLAN: hộp CŨ (ĐỎ) vs hộp MỚI (XANH LÁ).

- Hộp CŨ  : box_norm lưu trong output/stage4_dynamic_gt/gt_labeled.json.
- Hộp MỚI : tools.stage3b_zone_resolver.detect_loading_plan_signature_zone.
            Chưa có module -> chỉ vẽ hộp CŨ và in cảnh báo.

Xuất:
  output/stage4_dynamic_gt/overlay/<doc>.png
  output/stage4_dynamic_gt/crops_new/<doc>__<idx>_<role_slug>.png   (chỉ khi có module mới)

Ghi ảnh bằng cv2.imencode(...).tofile vì đường dẫn Windows có dấu tiếng Việt.
Chạy: .venv\\Scripts\\python.exe tools\\render_zone_overlay.py
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GT_FILE = ROOT / "output/stage4_dynamic_gt/gt_labeled.json"
IMG_DIR = ROOT / "output/form_samples"
OUT = ROOT / "output/stage4_dynamic_gt"
OVERLAY_DIR = OUT / "overlay"
CROPS_NEW_DIR = OUT / "crops_new"

RED = (0, 0, 255)      # hộp CŨ
GREEN = (0, 200, 0)    # hộp MỚI

# viết tắt vai trò cho nhãn cạnh hộp
ABBR = {
    "Người lập phiếu": "LAP",
    "Trưởng BP Kho / Nhóm trưởng": "TBP",
    "Tài xế (Lái xe nhận hàng)": "TAIXE",
    "Người nhận hàng": "NHAN",
    "Người giao / Thủ kho xuất": "GIAO",
}


def slug(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40]


def abbr(role):
    return ABBR.get(role) or slug(role)[:8].upper() or "?"


def imwrite_u(path: Path, img):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", img)[1].tofile(str(path))


def imread_u(path: Path):
    if not path.exists():
        return None
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def load_new_resolver():
    try:
        from tools.stage3b_zone_resolver import detect_loading_plan_signature_zone as fn
        return fn, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def draw_box(canvas, box_norm, color, label, side):
    """side='top' vẽ nhãn phía trên hộp, 'bottom' vẽ phía dưới -> 2 nhãn không đè nhau."""
    h, w = canvas.shape[:2]
    y1, x1, y2, x2 = box_norm
    p1 = (int(max(0.0, x1) * w), int(max(0.0, y1) * h))
    p2 = (int(min(1.0, x2) * w), int(min(1.0, y2) * h))
    cv2.rectangle(canvas, p1, p2, color, 3)
    ty = p1[1] - 8 if side == "top" else min(h - 4, p2[1] + 26)
    ty = max(20, ty)
    cv2.putText(canvas, label, (p1[0] + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 5)
    cv2.putText(canvas, label, (p1[0] + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    return p1, p2


def main():
    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    new_fn, reason = load_new_resolver()
    if new_fn is None:
        print(f"[CANH BAO] tools.stage3b_zone_resolver CHUA CO ({reason}) "
              f"-> CHI VE HOP CU (do). Khong sinh crops_new/.")
    else:
        print("[NEW] tools.stage3b_zone_resolver DA CO -> ve ca hop CU (do) va MOI (xanh la).")

    # gom GT theo file
    per_file = {}
    for t in gt["targets"]:
        d = per_file.setdefault(t["file_name"], {"page_role": t.get("page_role") or "HEADER",
                                                 "targets": [], "zone_only": []})
        if t.get("role") is None:
            d["zone_only"].append(t)
        else:
            d["targets"].append(t)

    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    n_ov = n_crop = 0

    for fname in sorted(per_file):
        info = per_file[fname]
        img = imread_u(IMG_DIR / fname)
        if img is None:
            print(f"  !! KHONG DOC DUOC {fname}")
            continue
        doc = Path(fname).stem
        canvas = img.copy()
        h, w = canvas.shape[:2]

        for t in info["targets"]:
            draw_box(canvas, t["box_norm"], RED, f"OLD:{abbr(t['role'])}", "top")

        note = "OLD=DO"
        if new_fn is not None:
            try:
                zone = new_fn(img, page_role=info["page_role"])
            except Exception as e:
                print(f"  !! NEW loi tren {fname}: {type(e).__name__}: {e}")
                zone = None
            if zone is None:
                note += " | NEW=LOI"
            elif not zone.get("has_signatures"):
                note += f" | NEW=NO_BLOCK({zone.get('status')})"
                cv2.putText(canvas, f"NEW: {zone.get('status')}", (20, h - 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, GREEN, 3)
            else:
                note += " | NEW=XANH_LA"
                for i, tt in enumerate(zone["targets"]):
                    p1, p2 = draw_box(canvas, tt["box_norm"], GREEN,
                                      f"NEW:{abbr(tt['role'])}", "bottom")
                    crop = img[max(0, p1[1]):min(h, p2[1]), max(0, p1[0]):min(w, p2[0])]
                    if crop.size:
                        sc = max(1.0, 420.0 / max(1, crop.shape[0]))
                        big = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
                        imwrite_u(CROPS_NEW_DIR / f"{doc}__{i}_{slug(tt['role'])}.png", big)
                        n_crop += 1
        else:
            note += " | NEW=CHUA CO MODULE"

        cv2.putText(canvas, note, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
        cv2.putText(canvas, note, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        imwrite_u(OVERLAY_DIR / f"{doc}.png", canvas)
        n_ov += 1

    print(f"overlay={n_ov} -> {OVERLAY_DIR}")
    print(f"crops_new={n_crop} -> {CROPS_NEW_DIR}")


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] render_zone_overlay.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
