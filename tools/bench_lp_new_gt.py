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
Hop nhat nhan gan LAI tren khung MOI + cham diem Tang 4 tren dung khung do.

Vi sao can file nay: `gt_labeled.json` duoc gan nhan tren khung CU. Sau khi
hinh hoc cot doi, noi dung trong khung da khac, nen cham khung MOI bang nhan CU
la so lech he quy chieu. Day la phep do dung he quy chieu: nhan MOI x khung MOI.

Chay:  .venv/Scripts/python.exe tools/bench_lp_new_gt.py
Ghi:   output/stage4_dynamic_gt/gt_labeled_new.json
       output/stage4_out/stage4_lp_newgt_benchmark.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools.stage3b_zone_resolver import detect_loading_plan_signature_zone  # noqa: E402
from tools.stage4_verifier import detect_document_modality  # noqa: E402
from tools.stage4_verifier import verify_single_target as v1_verify  # noqa: E402
from tools.stage4_verifier_v2 import verify_single_target as v2_verify  # noqa: E402

D = ROOT / "output/stage4_dynamic_gt"
OLD_GT = D / "gt_labeled.json"
NEW_GT = D / "gt_labeled_new.json"
OUT = ROOT / "output/stage4_out/stage4_lp_newgt_benchmark.json"
SAMPLES = ROOT / "output/form_samples"

VALID = {"PRESENT", "ABSENT", "AMBIGUOUS"}
VALID_OVF = {"NONE", "FROM_LEFT", "FROM_RIGHT", "BOTH"}
VALID_BP = {"GOOD", "PARTIAL", "WRONG_PLACE"}


def imread_u(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


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
    n = max(1, len(rows))
    return {"n": len(rows), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": round(P * 100, 2) if P is not None else None,
            "recall": round(R * 100, 2) if R is not None else None,
            "f1": round(F * 100, 2) if F is not None else None,
            "accuracy": round((tp + tn) / n * 100, 2)}


def merge_labels():
    labels, dup, badval = {}, [], []
    for tag in ("A", "B", "C"):
        f = D / f"labels_new_batch{tag}.json"
        if not f.exists():
            sys.exit(f"THIEU FILE NHAN: {f}")
        arr = json.loads(f.read_text(encoding="utf-8"))
        for L in arr:
            tid = L["target_id"]
            if tid in labels:
                dup.append(tid)
                continue
            if L.get("expected_presence") not in VALID:
                badval.append((tid, "presence", L.get("expected_presence")))
            if L.get("overflow") not in VALID_OVF:
                badval.append((tid, "overflow", L.get("overflow")))
            if L.get("box_placement") not in VALID_BP:
                badval.append((tid, "box_placement", L.get("box_placement")))
            L["_batch"] = tag
            labels[tid] = L
        print(f"  batch{tag}: {len(arr)} nhan")
    if dup:
        sys.exit(f"NHAN TRUNG: {dup}")
    if badval:
        sys.exit(f"GIA TRI KHONG HOP LE: {badval}")
    return labels


def main():
    print("== Hop nhat nhan moi ==")
    labels = merge_labels()

    old = json.loads(OLD_GT.read_text(encoding="utf-8"))
    page_role = {t["file_name"]: t["page_role"] for t in old["targets"]}

    files = sorted({fn for fn in page_role})
    targets, zone_rows = [], []
    img_cache = {}
    unmatched_label = set(labels)

    for fn in files:
        img = imread_u(SAMPLES / fn)
        z = detect_loading_plan_signature_zone(img, page_role=page_role[fn])
        doc = Path(fn).stem
        if not z["has_signatures"]:
            zone_rows.append({"file_name": fn, "status": z["status"]})
            continue
        img_cache[fn] = (img, detect_document_modality(img)["modality"] == "TRUE_COLOR")
        for i, t in enumerate(z["targets"]):
            tid = f"{doc}__T{i:02d}"
            L = labels.get(tid)
            if L is None:
                sys.exit(f"CHUA GAN NHAN: {tid} ({t['role']})")
            unmatched_label.discard(tid)
            targets.append({
                "target_id": tid, "file_name": fn, "role": t["role"], "role_index": i,
                "box_norm": t["box_norm"], "required": t["required"],
                "expected_color": t["expected_color"],
                "column_source": t.get("column_source"),
                "expected_presence": L["expected_presence"],
                "overflow": L["overflow"], "box_placement": L["box_placement"],
                "note": L.get("note"), "annotator": f"agent_new_batch{L['_batch']}",
            })
    if unmatched_label:
        sys.exit(f"NHAN THUA khong khop target nao: {sorted(unmatched_label)}")

    NEW_GT.write_text(json.dumps({
        "dataset_name": "KIDO LOADING_PLAN Dynamic Zone GT — khung MOI (bam nhan chuc danh)",
        "version": "2.0.0",
        "zone_source": "tools.stage3b_zone_resolver.detect_loading_plan_signature_zone",
        "annotation_method": "DIRECT_IMAGE_REVIEW tren crops_new + overlay; 3 annotator doc lap; "
                             "khong chay detector, khong doc GT cu",
        "total_targets": len(targets),
        "label_distribution": dict(Counter(t["expected_presence"] for t in targets)),
        "overflow_distribution": dict(Counter(t["overflow"] for t in targets)),
        "box_placement_distribution": dict(Counter(t["box_placement"] for t in targets)),
        "abstained_pages": zone_rows,
        "targets": targets,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {NEW_GT}  ({len(targets)} target)")

    print("\n== Cham diem tren khung MOI + nhan MOI ==")
    rows, amb = [], []
    for t in targets:
        if t["expected_presence"] == "AMBIGUOUS":
            amb.append(t["target_id"])
            continue
        img, is_color = img_cache[t["file_name"]]
        tgt = {"role": t["role"], "box_norm": t["box_norm"], "bbox": t["box_norm"],
               "expected_color": t["expected_color"], "required": t["required"],
               "description": t["role"]}
        r1 = v1_verify(img, dict(tgt), is_color=is_color)
        r2 = v2_verify(img, dict(tgt), is_color=is_color)
        rows.append({**{k: t[k] for k in ("target_id", "file_name", "role", "role_index",
                                          "required", "overflow", "box_placement", "note")},
                     "expected": t["expected_presence"],
                     "v1_detected": bool(r1["detected"]), "v1_evidence": r1.get("evidence_type"),
                     "v2_detected": bool(r2["detected"]), "v2_evidence": r2.get("evidence")})

    rep = {
        "benchmark": "Tang 4 tren khung MOI, cham bang GT gan lai tren chinh khung do",
        "gt": str(NEW_GT.relative_to(ROOT)).replace("\\", "/"),
        "n_scored": len(rows), "n_ambiguous_excluded": len(amb), "ambiguous": amb,
        "abstained_pages": zone_rows,
        "overall": {"v1": metrics(rows, "v1_detected"), "v2": metrics(rows, "v2_detected")},
        "by_role": {}, "by_overflow": {}, "by_box_placement": {},
        "per_target": rows,
    }
    for role in sorted({r["role"] for r in rows}):
        sub = [r for r in rows if r["role"] == role]
        rep["by_role"][role] = {"v1": metrics(sub, "v1_detected"), "v2": metrics(sub, "v2_detected")}
    for ov in sorted({r["overflow"] for r in rows}):
        sub = [r for r in rows if r["overflow"] == ov]
        rep["by_overflow"][ov] = {"v1": metrics(sub, "v1_detected"), "v2": metrics(sub, "v2_detected")}
    for bp in sorted({r["box_placement"] for r in rows}):
        sub = [r for r in rows if r["box_placement"] == bp]
        rep["by_box_placement"][bp] = {"v1": metrics(sub, "v1_detected"), "v2": metrics(sub, "v2_detected")}

    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    def line(nm, m):
        print(f"  {nm:5s} n={m['n']:3d} TP={m['tp']:3d} TN={m['tn']:3d} FP={m['fp']:3d} FN={m['fn']:3d} "
              f"P={m['precision']}% R={m['recall']}% F1={m['f1']}% Acc={m['accuracy']}%")
    print(f"  ({len(zone_rows)} trang ABSTAIN / khong co khoi ky, {len(amb)} AMBIGUOUS loai bo)")
    line("v1", rep["overall"]["v1"])
    line("ver2", rep["overall"]["v2"])
    print("\n  FP theo vai tro:")
    for role, m in rep["by_role"].items():
        print(f"    {role[:30]:30s} n={m['v1']['n']:2d}  v1 FP={m['v1']['fp']:2d}  ver2 FP={m['v2']['fp']:2d}")
    print("\n  Theo huong muc tran (nhan boi annotator):")
    for ov, m in rep["by_overflow"].items():
        print(f"    {ov:12s} n={m['v1']['n']:2d}  v1 FP={m['v1']['fp']:2d}  ver2 FP={m['v2']['fp']:2d}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] bench_lp_new_gt.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
