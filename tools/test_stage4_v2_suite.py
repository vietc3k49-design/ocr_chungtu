"""
BENCHMARK TẦNG 4 VER 2 vs GROUND TRUTH ĐỘC LẬP v2
==================================================

Mục tiêu: trả lời câu hỏi CHƯA AI ĐO ĐƯỢC — engine ver2 (cổng hình học) tốt hơn
hay kém hơn engine v1 (`tools/stage4_verifier.py`) về accuracy?

Nguồn GT: `output/stage4_gt_independent_v2.json` (185 targets, 123 PRESENT /
62 ABSENT, 147 required / 38 optional).

QUY ƯỚC ĐO (đọc kỹ trước khi trích dẫn số):

1. GT được gán nhãn theo `box_norm` của **preset tĩnh Tầng 3**. Đây cũng chính
   là bộ hộp mà v1 đã dùng khi sinh manifest được benchmark. Vì vậy phép so
   sánh CÔNG BẰNG duy nhất là: chạy **cùng 185 hộp GT** qua hai engine, giữ
   nguyên cách nạp ảnh của từng engine theo contract của nó.
     - v1  : ảnh gốc `output/form_samples/<file>` KHÔNG resize,
             modality đo trên chính ảnh đó (BUG-T4-04), margin 0.15.
     - ver2: ảnh resize về H=2200 (contract Tầng 3b), modality đo trên ảnh đã
             resize, ROI clamp SAFE_X/SAFE_Y, margin 0.08 (mộc) / 0.12 (ký).
   KHÔNG dùng zone động Tầng 3b ở đây, vì zone động sinh ra bộ target KHÁC
   (5 vai trò cho LOADING_PLAN thay vì 3) nên không tồn tại ánh xạ 1-1 với
   `target_id` của GT ⇒ không thể tính TP/FN. Đây là giới hạn của phép đo,
   đã ghi rõ thay vì che giấu.

2. Bảng (a) — TOÀN BỘ 185 targets, quy ước "ABSTAIN = not detected".
   Đây đúng là quy ước mà `test_stage4_suite.py:332` đã dùng cho v1
   (`s4_targets.get(tid, False)`): target không có phán quyết bị tính như
   không phát hiện. Với ver2, 80 targets thuộc doc_type ngoài phạm vi
   (PO/PXK/PGH/BBBG/...) bị ABSTAIN nên mặc nhiên detected=False.
   Hệ quả: mọi target PRESENT ngoài phạm vi thành FN, mọi target ABSENT ngoài
   phạm vi thành TN. Bảng này KHÔNG phản ánh chất lượng detector, nó phản ánh
   ĐỘ PHỦ. Đọc nó như một chỉ số phủ, không phải chỉ số nhận dạng.

3. Bảng (b) — CHỈ các target thuộc `LOADING_PLAN`.
   Đây là bảng KẾT LUẬN: cùng ảnh, cùng hộp, cùng nhãn, khác engine.

Chạy:  .venv/Scripts/python.exe tools/test_stage4_v2_suite.py
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import cv2

from tools import stage4_verifier as v1
from tools import stage4_verifier_v2 as v2

GT_PATH = "output/stage4_gt_independent_v2.json"
SAMPLE_DIRS = ["output/form_samples", "output/stage1_out/images/form_samples"]
# 27/09: pham vi ver2 thu hep ve CHI LOADING_PLAN. HOA_DON da bi go —
# moi chi nhanh / kenh MT-GT la mot bieu mau khac, phai tach template rieng.
IN_SCOPE_DOC_TYPES = ("LOADING_PLAN",)


def find_image(fn):
    for d in SAMPLE_DIRS:
        p = os.path.join(d, fn)
        if os.path.exists(p):
            return p
    return None


def metrics(tp, tn, fp, fn):
    p = tp / max(1, tp + fp)
    r = tp / max(1, tp + fn)
    f1 = 2 * p * r / max(1e-9, p + r)
    acc = (tp + tn) / max(1, tp + tn + fp + fn)
    return p, r, f1, acc


def confusion(rows):
    tp = tn = fp = fn = 0
    for exp, det in rows:
        if exp == "PRESENT":
            if det:
                tp += 1
            else:
                fn += 1
        elif exp == "ABSENT":
            if det:
                fp += 1
            else:
                tn += 1
    return tp, tn, fp, fn


def print_table(title, tp, tn, fp, fn):
    p, r, f1, acc = metrics(tp, tn, fp, fn)
    print(f"\n{title}")
    print(f"  TP={tp}  TN={tn}  FP={fp}  FN={fn}   (N={tp+tn+fp+fn})")
    print(f"  Precision={p*100:.2f}%  Recall={r*100:.2f}%  F1={f1*100:.2f}%  Accuracy={acc*100:.2f}%")
    return p, r, f1, acc


def infer_stamp_class_like_runner(item):
    """Sao lại đúng cách Cell 3 của notebook ver2 gán stamp_class (role.lower()).

    GHI NHẬN NỢ: cách suy này bị plan coi là sai chỗ (đáng lẽ zone resolver gán),
    nhưng ở đây phải giữ y hệt runner để bảng đo phản ánh ver2 THẬT.
    """
    role = (item.get("role") or "").lower()
    if item.get("expected_color") == "any_stamp" or "tiếp nhận" in role:
        return "SUPERMARKET_SQUARE"
    if item.get("expected_color") == "red_stamp" or "mộc đỏ" in role:
        return "COMPANY_ROUND_RED"
    return None


def run():
    gt = json.load(io.open(GT_PATH, encoding="utf-8"))
    targets = gt["targets"]

    # Cache ảnh: v1 dùng ảnh gốc, ver2 dùng ảnh resize H=2200
    cache_v1, cache_v2 = {}, {}

    def get_v1(fn):
        if fn not in cache_v1:
            p = find_image(fn)
            img = cv2.imread(p) if p else None
            mod = v1.detect_document_modality(img)["modality"] if img is not None else "UNKNOWN"
            cache_v1[fn] = (img, mod == "TRUE_COLOR")
        return cache_v1[fn]

    def get_v2(fn):
        if fn not in cache_v2:
            p = find_image(fn)
            raw = cv2.imread(p) if p else None
            if raw is None:
                cache_v2[fn] = (None, False)
            else:
                scale = 2200.0 / raw.shape[0]
                a4 = cv2.resize(raw, (int(raw.shape[1] * scale), 2200))
                mod = v1.detect_document_modality(a4)["modality"]
                cache_v2[fn] = (a4, mod == "TRUE_COLOR")
        return cache_v2[fn]

    rows_all_v1, rows_all_v2 = [], []
    rows_sub_v1, rows_sub_v2 = [], []
    per_target = []
    n_abstain_v2 = 0
    n_review_required = 0

    for item in targets:
        fn = item["file_name"]
        exp = item["expected_presence"]
        in_scope = item["doc_type"] in IN_SCOPE_DOC_TYPES

        # ---- v1 ----
        img1, color1 = get_v1(fn)
        t1 = {
            "role": item["role"],
            "expected_color": item["expected_color"],
            "required": item["required"],
            "box_norm": item["box_norm"],
            "target_type": item["target_type"],
        }
        r1 = v1.verify_single_target(img1, t1, is_color=color1)
        det1 = bool(r1["detected"])

        # ---- ver2 ----
        img2, color2 = get_v2(fn)
        t2 = dict(t1)
        sc = infer_stamp_class_like_runner(item)
        if sc:
            t2["stamp_class"] = sc
        if in_scope and img2 is not None:
            r2 = v2.verify_single_target(img2, t2, is_color=color2)
            det2 = bool(r2["detected"])
            if r2.get("evidence") == v2.REVIEW_REQUIRED_EVIDENCE:
                n_review_required += 1
            ev2 = r2.get("evidence")
        else:
            # ABSTAIN (ngoài phạm vi ver2) -> not detected, theo quy ước mục 2
            det2 = False
            ev2 = "ABSTAIN_OUT_OF_SCOPE"
            n_abstain_v2 += 1

        rows_all_v1.append((exp, det1))
        rows_all_v2.append((exp, det2))
        if in_scope:
            rows_sub_v1.append((exp, det1))
            rows_sub_v2.append((exp, det2))

        per_target.append({
            "target_id": item["target_id"],
            "file_name": fn,
            "doc_type": item["doc_type"],
            "in_scope": in_scope,
            "required": item["required"],
            "target_type": item["target_type"],
            "expected": exp,
            "v1_detected": det1,
            "v2_detected": det2,
            "v2_evidence": ev2,
        })

    print("=" * 100)
    print("BENCHMARK TẦNG 4 VER 2 vs GROUND TRUTH ĐỘC LẬP v2 (output/stage4_gt_independent_v2.json)")
    print("=" * 100)
    print(f"Tổng targets: {len(targets)} | ver2 ABSTAIN (ngoài scope/không đọc được ảnh): {n_abstain_v2}")
    print(f"ver2 REVIEW_REQUIRED (không xác định được lớp mộc, FIX-C): {n_review_required}")

    print("\n" + "-" * 100)
    print("BẢNG (a) — TOÀN BỘ 185 TARGETS | quy ước: ABSTAIN = not detected")
    print("           (đây là chỉ số ĐỘ PHỦ, không phải chỉ số nhận dạng)")
    print("-" * 100)
    a1 = print_table("v1  (stage4_verifier.py, Detector Core v1.1.0)", *confusion(rows_all_v1))
    a2 = print_table("ver2 (stage4_verifier_v2.py, cổng hình học)", *confusion(rows_all_v2))

    print("\n" + "-" * 100)
    print(f"BẢNG (b) — CHỈ LOADING_PLAN ({len(rows_sub_v1)} targets) | TÁO-VỚI-TÁO")
    print("-" * 100)
    b1 = print_table("v1  (stage4_verifier.py, Detector Core v1.1.0)", *confusion(rows_sub_v1))
    b2 = print_table("ver2 (stage4_verifier_v2.py, cổng hình học)", *confusion(rows_sub_v2))

    print("\n" + "-" * 100)
    print("KẾT LUẬN TRÊN TẬP CON CHUNG (bảng b)")
    print("-" * 100)
    for name, i in (("Precision", 0), ("Recall", 1), ("F1", 2), ("Accuracy", 3)):
        d = (b2[i] - b1[i]) * 100
        arrow = "▲" if d > 0.005 else ("▼" if d < -0.005 else "=")
        print(f"  {name:<10}: v1={b1[i]*100:6.2f}%  ver2={b2[i]*100:6.2f}%   {arrow} {d:+.2f} điểm")

    # Danh sách target đổi phán quyết giữa 2 engine (trong scope)
    flips = [x for x in per_target if x["in_scope"] and x["v1_detected"] != x["v2_detected"]]
    print(f"\nSố target ĐỔI phán quyết giữa v1 và ver2 (trong scope): {len(flips)}")
    for x in flips:
        kind = "ver2 THÊM detect" if x["v2_detected"] else "ver2 BỎ detect"
        verdict = "tốt lên" if ((x["expected"] == "PRESENT") == x["v2_detected"]) else "xấu đi"
        print(f"  - {x['target_id']:<14} {x['file_name']:<24} GT={x['expected']:<8} {kind:<18} => {verdict}  [{x['v2_evidence']}]")

    out = "output/stage4_out/stage4_v2_benchmark_report.json"
    os.makedirs("output/stage4_out", exist_ok=True)
    report = {
        "gt_source": GT_PATH,
        "n_targets": len(targets),
        "convention_full_set": "ABSTAIN counted as not-detected (same as test_stage4_suite.py:332 for v1)",
        "convention_subset": "targets with doc_type in LOADING_PLAN only",
        "table_a_full_185": {
            "v1": dict(zip(("tp", "tn", "fp", "fn"), confusion(rows_all_v1))),
            "v2": dict(zip(("tp", "tn", "fp", "fn"), confusion(rows_all_v2))),
        },
        "table_b_in_scope": {
            "n": len(rows_sub_v1),
            "v1": dict(zip(("tp", "tn", "fp", "fn"), confusion(rows_sub_v1))),
            "v2": dict(zip(("tp", "tn", "fp", "fn"), confusion(rows_sub_v2))),
        },
        "per_target": per_target,
    }
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nĐã ghi báo cáo chi tiết: {out}")


if __name__ == "__main__":
    run()
