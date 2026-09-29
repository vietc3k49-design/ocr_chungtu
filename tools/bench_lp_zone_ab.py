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
HARNESS A/B hình học vùng ký LOADING_PLAN (Tầng 3b): hộp CŨ vs hộp MỚI.

- OLD  = box_norm đã lưu trong output/stage4_dynamic_gt/gt_labeled.json (hình học hiện tại).
- NEW  = tools.stage3b_zone_resolver.detect_loading_plan_signature_zone (module sắp có).
         Chưa có module -> bỏ qua nhánh NEW TƯỜNG MINH, vẫn chốt được baseline OLD.

Ghép cặp theo (file_name, role) — KHÔNG theo box_norm, vì hình học sẽ đổi.
Role thừa/thiếu so với GT bị báo lỗi tường minh, không âm thầm bỏ qua.

Chấm mỗi nguồn hộp bằng CẢ HAI engine: stage4_verifier (v1) + stage4_verifier_v2 (ver2).
Chỉ chấm expected_presence in {PRESENT, ABSENT}; AMBIGUOUS loại khỏi mẫu số, báo riêng.
NO_SIGNATURE_BLOCK chấm riêng ở mục zone-level.

Xuất: output/stage4_out/stage4_zone_ab_report.json
Chạy:  .venv\\Scripts\\python.exe tools\\bench_lp_zone_ab.py
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools.stage4_verifier import verify_single_target as v1_verify, detect_document_modality  # noqa: E402
from tools.stage4_verifier_v2 import verify_single_target as v2_verify  # noqa: E402

GT_FILE = ROOT / "output/stage4_dynamic_gt/gt_labeled.json"
IMG_DIR = ROOT / "output/form_samples"
OUT = ROOT / "output/stage4_out/stage4_zone_ab_report.json"

ZONE_LABELS = ("NO_SIGNATURE_BLOCK", "HAS_SIGNATURE_BLOCK_MISSED")


# ---------------------------------------------------------------- new module
def load_new_resolver():
    """Trả (fn, None) nếu module mới đã có, ngược lại (None, lý do)."""
    try:
        from tools.stage3b_zone_resolver import detect_loading_plan_signature_zone as fn
        return fn, None
    except Exception as e:  # ModuleNotFoundError hoặc lỗi import khác
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- metrics
def metrics(rows, key):
    tp = tn = fp = fn = 0
    for r in rows:
        e, d = r["expected"] == "PRESENT", r[key]
        if d is None:
            continue
        if e and d:
            tp += 1
        elif e and not d:
            fn += 1
        elif (not e) and d:
            fp += 1
        else:
            tn += 1
    n = tp + tn + fp + fn
    P = tp / (tp + fp) if tp + fp else None
    R = tp / (tp + fn) if tp + fn else None
    F = 2 * P * R / (P + R) if P and R and (P + R) else None
    return {"n": n, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": round(P * 100, 2) if P is not None else None,
            "recall": round(R * 100, 2) if R is not None else None,
            "f1": round(F * 100, 2) if F is not None else None,
            "accuracy": round((tp + tn) / n * 100, 2) if n else None}


def score_target(img, is_color, role, box_norm, expected_color, required):
    tgt = {"role": role, "box_norm": box_norm, "bbox": box_norm,
           "expected_color": expected_color, "required": required,
           "description": role or ""}
    r1 = v1_verify(img, dict(tgt), is_color=is_color)
    r2 = v2_verify(img, dict(tgt), is_color=is_color)
    return (bool(r1["detected"]), r1.get("evidence_type"), r1.get("engine"),
            bool(r2["detected"]), r2.get("evidence"))


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    targets = gt["targets"]

    new_fn, new_skip_reason = load_new_resolver()
    if new_fn is None:
        print(f"[NEW] MODULE CHUA CO, chi do OLD  ({new_skip_reason})")
    else:
        print("[NEW] tools.stage3b_zone_resolver DA CO -> do ca OLD va NEW")

    # ---- ảnh + modality (dùng chung cho cả OLD lẫn NEW, quy ước của bench_lp_dynamic.py)
    img_cache = {}

    def get_img(fn_):
        if fn_ not in img_cache:
            p = IMG_DIR / fn_
            im = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                raise SystemExit(f"KHONG DOC DUOC ANH: {p}")
            img_cache[fn_] = (im, detect_document_modality(im)["modality"] == "TRUE_COLOR")
        return img_cache[fn_]

    # ---- phân loại GT
    gt_scored = {}       # (file, role) -> target
    gt_ambiguous = []
    gt_zone = []         # target cấp zone
    page_role_of = {}
    for t in targets:
        fn_ = t["file_name"]
        page_role_of.setdefault(fn_, t.get("page_role") or "HEADER")
        exp = t.get("expected_presence")
        if exp in ZONE_LABELS:
            gt_zone.append(t)
            continue
        if exp == "AMBIGUOUS":
            gt_ambiguous.append(t)
            continue
        if exp not in ("PRESENT", "ABSENT"):
            raise SystemExit(f"Target {t['target_id']} CHUA GAN NHAN (expected_presence={exp!r}).")
        key = (fn_, t["role"])
        if key in gt_scored:
            raise SystemExit(f"GT TRUNG CAP (file_name, role): {key} — harness khong ghep cap duoc.")
        gt_scored[key] = t

    zone_files_no_block = {z["file_name"] for z in gt_zone
                           if z["expected_presence"] == "NO_SIGNATURE_BLOCK"}

    # ---- OLD: hộp lấy thẳng từ GT
    old_rows = []
    for (fn_, role), t in gt_scored.items():
        img, is_color = get_img(fn_)
        d1, e1, en1, d2, e2 = score_target(img, is_color, role, t["box_norm"],
                                           t["expected_color"], t["required"])
        old_rows.append({
            "target_id": t["target_id"], "file_name": fn_, "role": role,
            "required": t["required"], "expected": t["expected_presence"],
            "box_norm": t["box_norm"], "box_placement": t.get("box_placement"),
            "gt_note": t.get("note"), "is_color": is_color,
            "v1_detected": d1, "v1_evidence": e1, "v1_engine": en1,
            "v2_detected": d2, "v2_evidence": e2,
        })
    old_rows.sort(key=lambda r: r["target_id"])

    # ---- NEW: hộp từ module mới
    new_rows = []
    mismatch = {"roles_new_not_in_gt": [], "roles_gt_not_in_new": [],
                "zone_regression_has_block_expected_none": [],
                "zone_regression_none_expected_block": [],
                "files_failed": []}
    new_zone = {"expected_no_block_files": sorted(zone_files_no_block),
                "new_no_block_files": None, "correct": None, "wrong": None}

    if new_fn is not None:
        new_no_block = set()
        for fn_ in sorted(page_role_of):
            img, is_color = get_img(fn_)
            try:
                zone = new_fn(img, page_role=page_role_of[fn_])
            except Exception as e:
                mismatch["files_failed"].append({"file_name": fn_, "error": f"{type(e).__name__}: {e}"})
                continue
            gt_roles_here = {role for (f, role) in gt_scored if f == fn_}
            if not zone.get("has_signatures"):
                new_no_block.add(fn_)
                if gt_roles_here:
                    mismatch["zone_regression_none_expected_block"].append(
                        {"file_name": fn_, "new_status": zone.get("status"),
                         "gt_roles_lost": sorted(gt_roles_here)})
                continue
            if fn_ in zone_files_no_block:
                mismatch["zone_regression_has_block_expected_none"].append(
                    {"file_name": fn_, "new_status": zone.get("status"),
                     "new_roles": [t["role"] for t in zone["targets"]]})
            seen = set()
            for tt in zone["targets"]:
                role = tt["role"]
                seen.add(role)
                key = (fn_, role)
                g = gt_scored.get(key)
                if g is None:
                    mismatch["roles_new_not_in_gt"].append(
                        {"file_name": fn_, "role": role, "box_norm": tt["box_norm"]})
                    continue
                d1, e1, en1, d2, e2 = score_target(img, is_color, role, tt["box_norm"],
                                                   tt.get("expected_color", g["expected_color"]),
                                                   tt.get("required", g["required"]))
                new_rows.append({
                    "target_id": g["target_id"], "file_name": fn_, "role": role,
                    "required": g["required"], "expected": g["expected_presence"],
                    "box_norm": tt["box_norm"], "box_placement": g.get("box_placement"),
                    "gt_note": g.get("note"), "is_color": is_color,
                    "v1_detected": d1, "v1_evidence": e1, "v1_engine": en1,
                    "v2_detected": d2, "v2_evidence": e2,
                })
            for role in sorted(gt_roles_here - seen):
                mismatch["roles_gt_not_in_new"].append({"file_name": fn_, "role": role})
        new_rows.sort(key=lambda r: r["target_id"])
        new_zone["new_no_block_files"] = sorted(new_no_block)
        new_zone["correct"] = sorted(new_no_block & zone_files_no_block)
        new_zone["wrong"] = {
            "expected_no_block_but_new_has_block": sorted(zone_files_no_block - new_no_block),
            "new_no_block_but_gt_has_targets": sorted(new_no_block - zone_files_no_block),
        }

    # ---- đổi phán quyết OLD -> NEW
    flips = []
    if new_fn is not None:
        old_by_id = {r["target_id"]: r for r in old_rows}
        for r in new_rows:
            o = old_by_id.get(r["target_id"])
            if not o:
                continue
            exp_present = r["expected"] == "PRESENT"
            for eng, k in (("v1", "v1_detected"), ("ver2", "v2_detected")):
                if o[k] == r[k]:
                    continue
                was_right = (o[k] == exp_present)
                flips.append({
                    "target_id": r["target_id"], "file_name": r["file_name"],
                    "role": r["role"], "engine": eng, "expected": r["expected"],
                    "old_detected": o[k], "new_detected": r[k],
                    "verdict": "XAU_DI" if was_right else "TOT_LEN",
                    "old_box": o["box_norm"], "new_box": r["box_norm"],
                })
        flips.sort(key=lambda f: (f["verdict"], f["role"], f["target_id"]))

    # ---- báo cáo
    def block(rows):
        return {"v1": metrics(rows, "v1_detected"), "ver2": metrics(rows, "v2_detected")}

    def by_role(rows):
        out = {}
        for role in sorted({r["role"] for r in rows}):
            out[role] = block([r for r in rows if r["role"] == role])
        return out

    rep = {
        "benchmark": "A/B hinh hoc vung ky LOADING_PLAN (Tang 3b): hop CU vs hop MOI",
        "generated_by": "tools/bench_lp_zone_ab.py",
        "gt_source": "output/stage4_dynamic_gt/gt_labeled.json",
        "gt_method": gt.get("annotation_method"),
        "match_key": "(file_name, role) — KHONG khop theo box_norm",
        "new_module": "tools.stage3b_zone_resolver.detect_loading_plan_signature_zone",
        "new_module_available": new_fn is not None,
        "new_module_skip_reason": new_skip_reason,
        "elapsed_sec": round(time.time() - t0, 2),
        "n_scored_old": len(old_rows),
        "n_scored_new": len(new_rows) if new_fn else None,
        "n_ambiguous_excluded": len(gt_ambiguous),
        "ambiguous_targets": [a["target_id"] for a in gt_ambiguous],
        "overall": {"OLD": block(old_rows)},
        "by_role": {"OLD": by_role(old_rows)},
        "zone_level": {
            "gt_no_signature_block": sorted(zone_files_no_block),
            "gt_missed_signature_block": [z["target_id"] for z in gt_zone
                                          if z["expected_presence"] == "HAS_SIGNATURE_BLOCK_MISSED"],
            "NEW": new_zone if new_fn else None,
        },
        "role_mismatch": mismatch if new_fn else None,
        "flips_old_to_new": flips if new_fn else None,
        "per_target": {"OLD": old_rows, "NEW": new_rows if new_fn else None},
    }
    if new_fn is not None:
        rep["overall"]["NEW"] = block(new_rows)
        rep["by_role"]["NEW"] = by_role(new_rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- stdout
    def line(name, m):
        print(f"  {name:10s} n={m['n']:3d} TP={m['tp']:3d} TN={m['tn']:3d} FP={m['fp']:3d} FN={m['fn']:3d} "
              f"P={m['precision']}% R={m['recall']}% F1={m['f1']}% Acc={m['accuracy']}%")

    print(f"\n=== A/B HINH HOC VUNG KY LOADING_PLAN — {len(old_rows)} target cham diem, "
          f"{len(gt_ambiguous)} AMBIGUOUS loai bo ===")
    line("OLD x v1", rep["overall"]["OLD"]["v1"])
    line("OLD x ver2", rep["overall"]["OLD"]["ver2"])
    if new_fn is not None:
        line("NEW x v1", rep["overall"]["NEW"]["v1"])
        line("NEW x ver2", rep["overall"]["NEW"]["ver2"])
    else:
        print("  NEW x v1   -- BO QUA (module chua co)")
        print("  NEW x ver2 -- BO QUA (module chua co)")

    print("\n--- BOC TACH THEO ROLE (FP la cho can nhin) ---")
    for role, b in rep["by_role"]["OLD"].items():
        s = f"  {role[:34]:34s} OLD v1 FP={b['v1']['fp']:2d}/n{b['v1']['n']:<3d} ver2 FP={b['ver2']['fp']:2d}"
        if new_fn is not None and role in rep["by_role"]["NEW"]:
            nb = rep["by_role"]["NEW"][role]
            s += f"  |  NEW v1 FP={nb['v1']['fp']:2d}/n{nb['v1']['n']:<3d} ver2 FP={nb['ver2']['fp']:2d}"
        print(s)

    if new_fn is not None:
        nm = sum(len(v) for v in mismatch.values())
        print(f"\n--- LECH ROLE / ZONE: {nm} muc ---")
        for k, v in mismatch.items():
            if v:
                print(f"  !! {k}: {len(v)}")
                for x in v[:20]:
                    print(f"       {x}")
        print(f"\n--- DOI PHAN QUYET OLD -> NEW: {len(flips)} ---")
        for f in flips:
            print(f"  [{f['verdict']}] {f['engine']:4s} {f['target_id']:26s} {f['role'][:30]:30s} "
                  f"exp={f['expected']:7s} old={f['old_detected']} new={f['new_detected']}")
        print(f"  TOT_LEN={sum(1 for f in flips if f['verdict']=='TOT_LEN')}  "
              f"XAU_DI={sum(1 for f in flips if f['verdict']=='XAU_DI')}")

    print(f"\n-> {OUT}")


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] bench_lp_zone_ab.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
