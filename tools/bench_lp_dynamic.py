# -*- coding: utf-8 -*-
# >>> HISTORICAL-BANNER (Giai doan 5 cleanup)
# DEPRECATED — raw images, KHONG phan anh production.
# Cong cu nay doc anh goc output/form_samples (~850px) va/hoac box/GT cu
# (output/stage4_dynamic_gt/), trong khi production doc anh Tang 1 resize H=2200
# voi zone Tang 3b hien tai. So do cua file nay KHONG duoc dung de ket luan ve
# production (DINH CHINH AGENTS.md 9.10.D). Duong do hien hanh:
#   tools/lp_production_path.py -> tools/bench_lp_prod.py (GT output/stage4_dynamic_gt_v4/).
# <<< HISTORICAL-BANNER
"""
Benchmark Tầng 4 (v1 vs ver2) trên ZONE ĐỘNG LOADING_PLAN + GT gán nhãn bằng mắt.
Đây là phép đo mà benchmark cũ KHÔNG làm được: bản cũ chạy ver2 dưới hộp TĨNH của v1.

Quy ước:
- Chỉ chấm các target có expected_presence in {PRESENT, ABSENT}.
- AMBIGUOUS bị LOẠI khỏi mẫu số và được báo riêng (không âm thầm tính là đúng).
- NO_SIGNATURE_BLOCK / HAS_SIGNATURE_BLOCK_MISSED chấm riêng ở mục zone-level.
Xuất: output/stage4_out/stage4_lp_dynamic_benchmark.json
"""
import json, sys, time
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))

from tools.stage4_verifier import verify_single_target as v1_verify, detect_document_modality  # noqa
from tools.stage4_verifier_v2 import verify_single_target as v2_verify  # noqa

GT_FILE = ROOT / "output/stage4_dynamic_gt/gt_labeled.json"
OUT = ROOT / "output/stage4_out/stage4_lp_dynamic_benchmark.json"


def metrics(rows, key):
    tp = tn = fp = fn = 0
    for r in rows:
        e, d = r["expected"] == "PRESENT", r[key]
        if e and d: tp += 1
        elif e and not d: fn += 1
        elif (not e) and d: fp += 1
        else: tn += 1
    n = max(1, len(rows))
    P = tp / (tp + fp) if tp + fp else None
    R = tp / (tp + fn) if tp + fn else None
    F = 2 * P * R / (P + R) if P and R and (P + R) else None
    return {"n": len(rows), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": round(P * 100, 2) if P is not None else None,
            "recall": round(R * 100, 2) if R is not None else None,
            "f1": round(F * 100, 2) if F is not None else None,
            "accuracy": round((tp + tn) / n * 100, 2)}


def main():
    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    targets = gt["targets"]
    img_cache = {}
    rows, zone_rows, ambiguous = [], [], []
    t0 = time.time()

    for t in targets:
        fn_ = t["file_name"]
        exp = t.get("expected_presence")
        if exp in ("NO_SIGNATURE_BLOCK", "HAS_SIGNATURE_BLOCK_MISSED"):
            zone_rows.append(t); continue
        if exp == "AMBIGUOUS":
            ambiguous.append(t); continue
        if exp not in ("PRESENT", "ABSENT"):
            raise SystemExit(f"Target {t['target_id']} CHUA GAN NHAN (expected_presence={exp!r}). Khong the cham diem.")

        if fn_ not in img_cache:
            p = ROOT / "output/form_samples" / fn_
            im = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
            img_cache[fn_] = (im, detect_document_modality(im)["modality"] == "TRUE_COLOR")
        img, is_color = img_cache[fn_]

        tgt = {"role": t["role"], "box_norm": t["box_norm"], "bbox": t["box_norm"],
               "expected_color": t["expected_color"], "required": t["required"],
               "description": t.get("role", "")}
        r1 = v1_verify(img, dict(tgt), is_color=is_color)
        r2 = v2_verify(img, dict(tgt), is_color=is_color)
        rows.append({
            "target_id": t["target_id"], "file_name": fn_, "role": t["role"],
            "required": t["required"], "expected": exp,
            "box_placement": t.get("box_placement"),
            "gt_note": t.get("note"),
            "v1_detected": bool(r1["detected"]),
            "v1_evidence": r1.get("evidence_type"), "v1_engine": r1.get("engine"),
            "v2_detected": bool(r2["detected"]), "v2_evidence": r2.get("evidence"),
            "is_color": is_color,
        })

    rep = {
        "benchmark": "Tang 4 tren ZONE DONG LOADING_PLAN (Tang 3b)",
        "gt_source": str(GT_FILE.relative_to(ROOT)).replace("\\", "/"),
        "gt_method": gt.get("annotation_method"),
        "elapsed_sec": round(time.time() - t0, 2),
        "n_scored": len(rows), "n_ambiguous_excluded": len(ambiguous),
        "n_zone_level": len(zone_rows),
        "ambiguous_targets": [a["target_id"] for a in ambiguous],
        "overall": {"v1": metrics(rows, "v1_detected"), "v2": metrics(rows, "v2_detected")},
        "by_required": {},
        "by_role": {},
        "by_box_placement": {},
        "zone_level": {
            "total": len(zone_rows),
            "correct_no_signature_block": sum(1 for z in zone_rows if z["expected_presence"] == "NO_SIGNATURE_BLOCK"),
            "missed_signature_block": [z["target_id"] for z in zone_rows if z["expected_presence"] == "HAS_SIGNATURE_BLOCK_MISSED"],
        },
        "per_target": rows,
    }
    for req in (True, False):
        sub = [r for r in rows if r["required"] is req]
        if sub:
            rep["by_required"][str(req)] = {"v1": metrics(sub, "v1_detected"), "v2": metrics(sub, "v2_detected")}
    for role in sorted({r["role"] for r in rows}):
        sub = [r for r in rows if r["role"] == role]
        rep["by_role"][role] = {"v1": metrics(sub, "v1_detected"), "v2": metrics(sub, "v2_detected")}
    for bp in sorted({r["box_placement"] or "NA" for r in rows}):
        sub = [r for r in rows if (r["box_placement"] or "NA") == bp]
        rep["by_box_placement"][bp] = {"v1": metrics(sub, "v1_detected"), "v2": metrics(sub, "v2_detected")}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    def line(name, m):
        print(f"  {name:5s} n={m['n']:3d} TP={m['tp']:3d} TN={m['tn']:3d} FP={m['fp']:3d} FN={m['fn']:3d} "
              f"P={m['precision']}% R={m['recall']}% F1={m['f1']}% Acc={m['accuracy']}%")
    print(f"=== ZONE DONG LOADING_PLAN — {len(rows)} targets cham diem, {len(ambiguous)} AMBIGUOUS loai bo ===")
    line("v1", rep["overall"]["v1"]); line("ver2", rep["overall"]["v2"])
    print(f"-> {OUT}")


if __name__ == "__main__":
    import sys
    print("[DEPRECATED] bench_lp_dynamic.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
