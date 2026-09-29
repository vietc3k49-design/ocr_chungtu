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
Sinh crop + contact sheet cho việc GÁN NHÃN THỦ CÔNG zone động LOADING_PLAN (Tầng 3b).
Không suy ra nhãn từ detector -> GT độc lập thật sự.
Xuất:
  output/stage4_dynamic_gt/crops/<doc>__<idx>_<role_slug>.png   (từng ô ký, phóng to)
  output/stage4_dynamic_gt/sheets/<doc>.png                     (ảnh full + khung đánh số)
  output/stage4_dynamic_gt/gt_skeleton.json                     (khung GT, expected_presence=null)
"""
import json, os, re, sys, unicodedata
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from tools.kido_pipeline import detect_loading_plan_signature_zone  # noqa: E402

OUT = ROOT / "output" / "stage4_dynamic_gt"
(OUT / "crops").mkdir(parents=True, exist_ok=True)
(OUT / "sheets").mkdir(parents=True, exist_ok=True)


def slug(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40]


def main():
    s2 = json.loads((ROOT / "output/stage2_out/stage2_classified_results.json").read_text(encoding="utf-8"))
    recs = s2 if isinstance(s2, list) else s2.get("results", s2.get("records", []))
    lp = [r for r in recs if r.get("doc_type") == "LOADING_PLAN"]
    lp.sort(key=lambda r: r.get("file_name", ""))
    print(f"LOADING_PLAN records: {len(lp)}")

    gt = {
        "dataset_name": "KIDO LOADING_PLAN Dynamic Signature Zone Ground Truth",
        "version": "1.0.0-skeleton",
        "zone_source": "kido_pipeline.detect_loading_plan_signature_zone (Tang 3b)",
        "annotation_method": "DIRECT_IMAGE_REVIEW (crop phong to, nguoi/agent nhin anh)",
        "note": "expected_presence=null nghia la CHUA GAN NHAN. Khong duoc suy tu detector.",
        "targets": [],
    }

    n_img = 0
    for r in lp:
        fn = r.get("file_name")
        page_role = r.get("page_role", "HEADER") or "HEADER"
        src = ROOT / "output/form_samples" / fn
        if not src.exists():
            print(f"  !! MISSING {fn}")
            continue
        img = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"  !! UNREADABLE {fn}")
            continue
        n_img += 1
        h, w = img.shape[:2]
        zone = detect_loading_plan_signature_zone(img, page_role=page_role)
        doc = Path(fn).stem

        sheet = img.copy()
        if not zone["has_signatures"]:
            gt["targets"].append({
                "target_id": f"{doc}__ZONE",
                "file_name": fn, "doc_type": "LOADING_PLAN", "page_role": page_role,
                "zone_status": zone["status"], "role": None, "box_norm": None,
                "required": None, "expected_color": None,
                "expected_presence": "NO_SIGNATURE_BLOCK",
                "crop_file": None, "annotator": None, "note": zone["description"],
            })
            cv2.putText(sheet, f"{zone['status']}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 255), 4)
        else:
            for i, t in enumerate(zone["targets"]):
                y1, x1, y2, x2 = t["box_norm"]
                p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
                cv2.rectangle(sheet, p1, p2, (0, 0, 255), 3)
                cv2.putText(sheet, str(i), (p1[0] + 6, p1[1] + 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 0, 0), 4)
                crop = img[max(0, p1[1]):min(h, p2[1]), max(0, p1[0]):min(w, p2[0])]
                cname = f"{doc}__{i}_{slug(t['role'])}.png"
                if crop.size:
                    sc = max(1.0, 420.0 / max(1, crop.shape[0]))
                    big = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
                    cv2.imencode(".png", big)[1].tofile(str(OUT / "crops" / cname))
                gt["targets"].append({
                    "target_id": f"{doc}__T{i:02d}",
                    "file_name": fn, "doc_type": "LOADING_PLAN", "page_role": page_role,
                    "zone_status": zone["status"], "role": t["role"], "box_norm": t["box_norm"],
                    "required": t["required"], "expected_color": t["expected_color"],
                    "expected_presence": None,
                    "crop_file": f"output/stage4_dynamic_gt/crops/{cname}",
                    "annotator": None, "note": None,
                })
        cv2.imencode(".png", sheet)[1].tofile(str(OUT / "sheets" / f"{doc}.png"))

    gt["total_images"] = n_img
    gt["total_targets"] = len(gt["targets"])
    (OUT / "gt_skeleton.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"images={n_img}  targets={len(gt['targets'])}")
    print(f"-> {OUT/'gt_skeleton.json'}")


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] build_lp_dynamic_crops.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
