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
A/B: engine chu ky ver2 BAN CU (adaptiveThreshold + nguong tuyet doi)
     vs   BAN MOI (ink-mask + nguong ti le)
tren CUNG bo hop DONG + GT gan nhan bang mat.

Ban cu duoc dung lai nguyen van tu lich su file (khong sua file hien tai).
Muc dich: tra loi "ban sua co that su tot hon khong", khong phong doan.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools.stage4_verifier import detect_document_modality  # noqa: E402
from tools import stage4_verifier_v2 as V2  # noqa: E402

GT = ROOT / "output/stage4_dynamic_gt/gt_labeled.json"
OUT = ROOT / "output/stage4_out/stage4_v2_signature_ab.json"


def verify_signature_OLD(crop, is_color=True):
    """Ban CU nguyen van (truoc khi sua) — chep tu lich su stage4_verifier_v2.py:407-461."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([145, 255, 255]))
    blue_px = int(np.sum(blue_mask > 0))
    if is_color and blue_px > 40:
        return {"detected": True, "evidence": "BLUE_SIGNATURE_DETECTED"}

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h_c, w_c = crop.shape[:2]
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 15, 8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(thresh)
    sig_strokes = 0
    max_stroke_area = 0
    for i in range(1, n_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        ch = stats[i, cv2.CC_STAT_HEIGHT]
        cw = stats[i, cv2.CC_STAT_WIDTH]
        if cw <= 3 and ch > h_c * 0.7:
            continue
        if ch <= 3 and cw > w_c * 0.7:
            continue
        if ch < 20 and area < 100:
            continue
        if area > 120 and (ch >= 15 or cw >= 25):
            sig_strokes += 1
            max_stroke_area = max(max_stroke_area, area)
    if sig_strokes >= 1 and max_stroke_area >= 150:
        return {"detected": True, "evidence": "HANDWRITING_STROKE_DETECTED"}
    return {"detected": False, "evidence": "NO_SIGNATURE_DETECTED"}


def metrics(rows, key):
    tp = tn = fp = fn = 0
    for r in rows:
        e, d = r["expected"] == "PRESENT", r[key]
        if e and d:
            tp += 1
        elif e:
            fn += 1
        elif d:
            fp += 1
        else:
            tn += 1
    P = tp / (tp + fp) if tp + fp else None
    R = tp / (tp + fn) if tp + fn else None
    F = 2 * P * R / (P + R) if P and R else None
    return {"n": len(rows), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": round(P * 100, 2) if P else None,
            "recall": round(R * 100, 2) if R else None,
            "f1": round(F * 100, 2) if F else None}


def main():
    gt = json.loads(GT.read_text(encoding="utf-8"))
    cache = {}
    rows = []
    for t in gt["targets"]:
        if t.get("expected_presence") not in ("PRESENT", "ABSENT"):
            continue
        if t.get("expected_color") in ("red_stamp", "any_stamp"):
            continue  # A/B nay chi ve engine CHU KY
        fn_ = t["file_name"]
        if fn_ not in cache:
            p = ROOT / "output/form_samples" / fn_
            im = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
            cache[fn_] = (im, detect_document_modality(im)["modality"] == "TRUE_COLOR")
        img, is_color = cache[fn_]
        crop, _ = V2.extract_safe_roi(img, t["box_norm"], V2.SIG_MARGIN)
        if crop is None:
            continue
        old = verify_signature_OLD(crop, is_color=is_color)
        new = V2.verify_signature(crop, is_color=is_color)
        rows.append({
            "target_id": t["target_id"], "role": t["role"],
            "expected": t["expected_presence"],
            "box_placement": t.get("box_placement"),
            "old_detected": bool(old["detected"]), "old_evidence": old["evidence"],
            "new_detected": bool(new["detected"]), "new_evidence": new["evidence"],
        })

    rep = {
        "question": "Ban sua engine chu ky ver2 co tot hon ban cu khong (tren zone DONG + GT thuc)?",
        "n": len(rows),
        "OLD_adaptiveThreshold_absolute": metrics(rows, "old_detected"),
        "NEW_inkmask_relative": metrics(rows, "new_detected"),
        "changed": [r for r in rows if r["old_detected"] != r["new_detected"]],
        "per_target": rows,
    }
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"n={len(rows)} signature targets (loai bo target mộc)")
    print("  CU  :", rep["OLD_adaptiveThreshold_absolute"])
    print("  MOI :", rep["NEW_inkmask_relative"])
    print(f"  doi phan quyet: {len(rep['changed'])} target")
    for c in rep["changed"]:
        d = "CU=K,MOI=C" if c["new_detected"] else "CU=C,MOI=K"
        verdict = "tot len" if (c["new_detected"] == (c["expected"] == "PRESENT")) else "xau di"
        print(f"    {c['target_id']:28s} GT={c['expected']:8s} {d}  => {verdict}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] ab_v2_signature_fix.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
