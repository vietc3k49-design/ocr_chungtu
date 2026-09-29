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
Hop nhat labels_batch1..4.json vao gt_labeled.json.
Kiem tra nghiem ngat, KHONG tu dien nhan thieu:
 - moi target trong skeleton phai co dung 1 nhan
 - nhan thua / trung / sai target_id  -> bao loi va dung
 - target chua gan nhan               -> bao loi va dung
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "output/stage4_dynamic_gt"
SKEL = D / "gt_skeleton.json"
OUT = D / "gt_labeled.json"

VALID = {"PRESENT", "ABSENT", "AMBIGUOUS", "NO_SIGNATURE_BLOCK", "HAS_SIGNATURE_BLOCK_MISSED"}
VALID_BP = {"GOOD", "PARTIAL", "WRONG_PLACE", "NA", None}


def main():
    skel = json.loads(SKEL.read_text(encoding="utf-8"))
    by_id = {t["target_id"]: t for t in skel["targets"]}

    labels = {}
    dup, unknown, badval = [], [], []
    for i in (1, 2, 3, 4):
        f = D / f"labels_batch{i}.json"
        if not f.exists():
            sys.exit(f"THIEU FILE: {f}")
        arr = json.loads(f.read_text(encoding="utf-8"))
        for L in arr:
            tid = L.get("target_id")
            if tid not in by_id:
                unknown.append((i, tid))
                continue
            if tid in labels:
                dup.append(tid)
                continue
            if L.get("expected_presence") not in VALID:
                badval.append((tid, L.get("expected_presence")))
            if L.get("box_placement") not in VALID_BP:
                badval.append((tid, L.get("box_placement")))
            L["_batch"] = i
            labels[tid] = L
        print(f"  batch{i}: {len(arr)} nhan")

    missing = [t for t in by_id if t not in labels]
    errs = []
    if missing:
        errs.append(f"CHUA GAN NHAN ({len(missing)}): {missing}")
    if dup:
        errs.append(f"NHAN TRUNG: {dup}")
    if unknown:
        errs.append(f"TARGET_ID LA: {unknown}")
    if badval:
        errs.append(f"GIA TRI KHONG HOP LE: {badval}")
    if errs:
        for e in errs:
            print("!! " + e)
        sys.exit(1)

    for t in skel["targets"]:
        L = labels[t["target_id"]]
        t["expected_presence"] = L["expected_presence"]
        t["box_placement"] = L.get("box_placement")
        t["note"] = L.get("note")
        t["annotator"] = f"agent_batch{L['_batch']}"

    skel["version"] = "1.0.0"
    skel["annotation_method"] = (
        "DIRECT_IMAGE_REVIEW — 4 annotator doc lap nhin crop phong to, "
        "khong chay detector, khong doc manifest"
    )
    c = Counter(t["expected_presence"] for t in skel["targets"])
    cbp = Counter(t.get("box_placement") or "NA" for t in skel["targets"])
    skel["label_distribution"] = dict(c)
    skel["box_placement_distribution"] = dict(cbp)
    OUT.write_text(json.dumps(skel, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nTONG {len(skel['targets'])} target")
    for k, v in c.most_common():
        print(f"  {k:28s} {v}")
    print("box_placement:", dict(cbp))
    print(f"-> {OUT}")


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] merge_lp_dynamic_labels.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
