# -*- coding: utf-8 -*-
"""
Benchmark Tang 4 (v1 vs ver2) tren DUNG DUONG PRODUCTION cho LOADING_PLAN:
anh Tang 1 resize H=2200 + box Tang 3b (tools/lp_production_path.py), cham bang GT v3
(output/stage4_dynamic_gt_v3/gt_labeled.json do tools/merge_lp_prod_labels.py sinh).

NHAN CHAM DIEM CHINH = `own_signature` (CHINH vai tro nay da ky chua; muc tran tu cot hang xom
KHONG tinh): YES = positive, NO = negative, AMBIGUOUS bi loai khoi mau so (bao so bi loai).
Bao PHU: cham theo `presence` ("co muc tay trong khung"). Cham theo presence se cho detector
"dung" tren dung cac o chi co muc tran — vi vay no chi la bao phu, khong phai ket luan.
Bang rieng: o CHI CO MUC TRAN (presence=PRESENT & own_signature=NO) — detector noi gi.

ASSERT that (khong phai nguong "pass theo diem"):
 - box production khop 100% manifest v2 chinh thuc
 - ver2 tren duong nay tai lap dung `detected` trong manifest v2 (xac nhan cung duong)
 - so target production > 0
 - GT phu >= 95% target production, box GT trung box production, khong co target GT la
In CANH BAO noi bat neu TN=0 theo nhan CHINH (hoac GT khong co own_signature=NO nao => TN khong the do).

GT v4 (output/stage4_dynamic_gt_v4/gt_labeled.json, tools/build_lp_prod_gt_v4.py): own_signature theo vai tro ghep
vao box production moi; presence/overflow/sig_cut/frame_quality la nhan tren box CU va mang co `box_changed`.
Khi GT co truong `box_changed`: CHINH cham tren moi o; moi thong ke dua tren nhan phu thuoc box (PHU presence,
o chi co muc tran, theo overflow/frame_quality/sig_cut) CHI tinh tren o box_changed=false — ghi ro trong report.

Chay:  .venv/Scripts/python.exe tools/bench_lp_prod.py [--gt PATH] [--out PATH]
Ghi:   output/stage4_out/stage4_lp_prod_benchmark.json
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import lp_production_path as lpp  # noqa: E402
from tools.stage4_verifier import verify_single_target as v1_verify  # noqa: E402
from tools.stage4_verifier_v2 import verify_single_target as v2_verify  # noqa: E402

DEFAULT_GT = ROOT / "output/stage4_dynamic_gt_v4/gt_labeled.json"  # v3 lech box resolver tu 16:07 (GD4)
DEFAULT_OUT = ROOT / "output/stage4_out/stage4_lp_prod_benchmark.json"
MIN_GT_COVERAGE = 0.95


PRIMARY = ("own_signature", "YES", "NO")      # (truong, gia tri positive, gia tri negative)
SECONDARY = ("presence", "PRESENT", "ABSENT")


def metrics(rows, key, label=PRIMARY):
    fld, pos, _ = label
    tp = tn = fp = fn = 0
    for r in rows:
        e, d = r[fld] == pos, r[key]
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
            "precision": round(P * 100, 2) if P is not None else None,
            "recall": round(R * 100, 2) if R is not None else None,
            "f1": round(F * 100, 2) if F is not None else None,
            "accuracy": round((tp + tn) / len(rows) * 100, 2) if rows else None}


def both(rows, label=PRIMARY):
    return {"v1": metrics(rows, "v1_detected", label), "v2": metrics(rows, "v2_detected", label)}


def group(rows, key, label=PRIMARY):
    return {str(k): both([r for r in rows if r[key] == k], label) for k in sorted({r[key] for r in rows}, key=str)}


def scorable(rows, label):
    fld, pos, neg = label
    return [r for r in rows if r[fld] in (pos, neg)]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default=str(DEFAULT_GT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    t0 = time.time()

    # 1. Duong production + doi chieu manifest
    pages, _ = lpp.load_all_loading_plan_pages()
    manifest = lpp.load_manifest_v2()
    box_check = lpp.assert_boxes_match_manifest(pages, manifest)
    prod = {}   # target_id -> (page, target)
    for p in pages:
        if lpp.page_kind(p) == "TARGETS":
            for i, t in enumerate(p["zone"]["targets"]):
                prod[lpp.target_id(p["file_name"], i)] = (p, t)
    assert len(prod) > 0, "KHONG CO TARGET NAO tren duong production — khong co gi de cham"

    # 2. GT
    gt_path = Path(a.gt)
    assert gt_path.exists(), f"Khong tim thay GT: {gt_path} (chay merge_lp_prod_labels.py truoc)"
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    gtt = {t["target_id"]: t for t in gt["targets"]}
    unknown = sorted(set(gtt) - set(prod))
    assert not unknown, f"GT co {len(unknown)} target KHONG ton tai tren duong production (GT loi thoi?): {unknown[:8]}"
    stale = [tid for tid, t in gtt.items()
             if [round(float(v), 4) for v in t["box_norm"]] != [round(float(v), 4) for v in prod[tid][1]["box_norm"]]]
    assert not stale, f"{len(stale)} target GT co box KHAC box production (resolver da doi sau khi gan nhan): {stale[:8]}"
    bad = [tid for tid, t in gtt.items() if t.get("presence") not in ("PRESENT", "ABSENT", "AMBIGUOUS")]
    assert not bad, f"{len(bad)} target GT khong co presence hop le: {bad[:8]}"
    bad = [tid for tid, t in gtt.items() if t.get("own_signature") not in ("YES", "NO", "AMBIGUOUS")]
    assert not bad, f"{len(bad)} target GT khong co own_signature hop le (GT sinh tu merge cu?): {bad[:8]}"
    coverage = len(set(gtt) & set(prod)) / len(prod)
    assert coverage >= MIN_GT_COVERAGE, (
        f"GT chi phu {coverage:.1%} target production (< {MIN_GT_COVERAGE:.0%}): "
        f"thieu {sorted(set(prod) - set(gtt))[:8]}")

    # 3. Cham diem
    mdet = {}
    for d in manifest["documents"]:
        for i, mt in enumerate(d.get("targets", [])):
            mdet[lpp.target_id(d["file_name"], i)] = bool(mt["detected"])
    all_rows, v2_mismatch = [], []
    for tid in sorted(set(gtt) & set(prod)):
        g = gtt[tid]
        p, t = prod[tid]
        r1 = v1_verify(p["image"], lpp.prepare_v1_target(t), is_color=p["is_color"])
        r2 = v2_verify(p["image"], lpp.prepare_v2_target(t), is_color=p["is_color"])
        if tid in mdet and bool(r2["detected"]) != mdet[tid]:
            v2_mismatch.append(tid)
        all_rows.append({
            "target_id": tid, "file_name": p["file_name"], "role": t["role"], "role_index": g.get("role_index"),
            "required": bool(t["required"]), "own_signature": g["own_signature"], "presence": g["presence"],
            "overflow": g.get("overflow"), "frame_quality": g.get("frame_quality"), "sig_cut": g.get("sig_cut"),
            "is_color": p["is_color"], "box_changed": g.get("box_changed"),
            "box_dependent_labels_from": g.get("box_dependent_labels_from"),
            "v1_detected": bool(r1["detected"]), "v1_evidence": r1.get("evidence_type"), "v1_engine": r1.get("engine"),
            "v2_detected": bool(r2["detected"]), "v2_evidence": r2.get("evidence"),
        })
    assert not v2_mismatch, (f"ver2 tren duong nay KHAC manifest v2 o {len(v2_mismatch)} target — "
                             f"khong phai cung duong production: {v2_mismatch[:8]}")
    rows = scorable(all_rows, PRIMARY)                       # cham CHINH (moi o — own_signature doc lap box)
    amb = [r["target_id"] for r in all_rows if r["own_signature"] == "AMBIGUOUS"]
    # Nhan phu thuoc box chi dung duoc tren o ma box nhan == box production.
    has_box_flag = any("box_changed" in t for t in gt["targets"])
    if has_box_flag:
        bad = [tid for tid, t in gtt.items() if not isinstance(t.get("box_changed"), bool)]
        assert not bad, f"{len(bad)} target GT thieu co box_changed hop le: {bad[:8]}"
    box_rows = [r for r in all_rows if r["box_changed"] is not True]
    n_box_changed = len(all_rows) - len(box_rows)
    rows_box = scorable(box_rows, PRIMARY)                   # cho thong ke theo nhan phu thuoc box
    rows_pres = scorable(box_rows, SECONDARY)                # cham PHU
    amb_pres = [r["target_id"] for r in box_rows if r["presence"] == "AMBIGUOUS"]
    ovf_only = [r for r in box_rows if r["presence"] == "PRESENT" and r["own_signature"] == "NO"]
    overflow_only = {
        "definition": "presence=PRESENT & own_signature=NO (trong khung chi co muc tran tu cot hang xom)",
        "scope": ("chi o box_changed=false (presence gan tren box cu)" if has_box_flag else "moi o"),
        "n_box_changed_excluded": n_box_changed if has_box_flag else 0,
        "n": len(ovf_only),
        "v1_detected": sum(r["v1_detected"] for r in ovf_only),
        "v2_detected": sum(r["v2_detected"] for r in ovf_only),
        "note": "detected=True o day la FP theo nhan CHINH nhung la TP theo presence (PASS gia neu cham theo presence)",
        "rows": [{k: r[k] for k in ("target_id", "role", "overflow", "v1_detected", "v1_evidence",
                                    "v2_detected", "v2_evidence")} for r in ovf_only],
    }

    # 4. Muc trang
    gpages = {pg["page_id"]: pg for pg in gt.get("pages", [])}
    page_rows = []
    for p in pages:
        kind = lpp.page_kind(p)
        if kind not in ("PAGE_1_NO_SIGNATURES", "ZONE_ABSTAIN"):
            continue
        lab = (gpages.get(lpp.page_id(p["file_name"])) or {}).get("has_signature_block")
        verdict = {("PAGE_1_NO_SIGNATURES", "NO"): "CORRECT_NO_BLOCK",
                   ("PAGE_1_NO_SIGNATURES", "YES"): "MISSED_BLOCK_EXEMPTED",
                   ("ZONE_ABSTAIN", "YES"): "ABSTAIN_ON_REAL_BLOCK",
                   ("ZONE_ABSTAIN", "NO"): "ABSTAIN_NO_BLOCK"}.get((kind, lab), f"UNSCORED({lab})")
        page_rows.append({"file_name": p["file_name"], "page_kind": kind,
                          "zone_status": (p["zone"] or {}).get("status"), "has_signature_block": lab,
                          "result": verdict})

    rep = {
        "benchmark": "Tang 4 v1 vs ver2 tren DUONG PRODUCTION LOADING_PLAN (anh Tang 1 H=2200 + zone Tang 3b)",
        "gt_source": str(gt_path.resolve().relative_to(ROOT) if gt_path.resolve().is_relative_to(ROOT) else gt_path).replace("\\", "/"),
        "gt_version": gt.get("version"), "gt_sources": gt.get("sources"), "gt_built_by": gt.get("built_by"),
        "gt_stage3b_resolver_mtime": gt.get("stage3b_resolver_mtime"),
        "gt_method": gt.get("annotation_method"), "gt_annotators": gt.get("annotators"),
        "gt_agreement": gt.get("agreement"),
        "stage3b_resolver_mtime": lpp.resolver_mtime(),
        "manifest_box_check": box_check,
        "v2_reproduces_manifest": True,
        "gt_coverage": round(coverage * 100, 2),
        "n_production_targets": len(prod), "primary_label": "own_signature",
        "n_scored": len(rows), "n_ambiguous_excluded": len(amb), "ambiguous": amb,
        "elapsed_sec": None,
        "overall": both(rows),
        "by_required": group(rows, "required"),
        "by_role": group(rows, "role"),
        "box_dependent_scope": ({"note": "by_overflow/by_frame_quality/by_sig_cut/secondary_presence/overflow_only "
                                          "CHI tren o box_changed=false: cac nhan nay gan tren box cu",
                                  "n_box_changed_excluded": n_box_changed, "n_box_unchanged": len(box_rows),
                                  "n_scored_primary_box_unchanged": len(rows_box)}
                                 if has_box_flag else {"note": "GT khong co box_changed — moi o"}),
        "by_box_changed": group(rows, "box_changed") if has_box_flag else None,
        "by_overflow": group(rows_box, "overflow"),
        "by_frame_quality": group(rows_box, "frame_quality"),
        "by_sig_cut": group(rows_box, "sig_cut"),
        "secondary_presence": {
            "note": "PHU — cham theo presence (co muc tay trong khung, tinh ca muc tran). Khong dung de ket luan."
                    + (" CHI o box_changed=false." if has_box_flag else ""),
            "n_scored": len(rows_pres), "n_ambiguous_excluded": len(amb_pres), "ambiguous": amb_pres,
            "overall": both(rows_pres, SECONDARY),
            "by_required": group(rows_pres, "required", SECONDARY),
            "by_role": group(rows_pres, "role", SECONDARY),
        },
        "overflow_only": overflow_only,
        "page_level": {"rows": page_rows, "summary": dict(Counter(r["result"] for r in page_rows))},
        "warnings": [],
        "per_target": all_rows,
    }
    n_absent = sum(1 for r in rows if r["own_signature"] == "NO")
    if n_absent == 0:
        rep["warnings"].append("GT KHONG CO O own_signature=NO NAO — TN/Precision (nhan CHINH) khong the do duoc")
    for eng in ("v1", "v2"):
        m = rep["overall"][eng]
        if n_absent and m["tn"] == 0:
            rep["warnings"].append(f"TN=0 (nhan CHINH own_signature) o engine {eng}: moi o chua ky ({n_absent}) "
                                   f"deu bi cham co ky — engine KHONG phan biet duoc o chua ky tren duong production")
    rep["elapsed_sec"] = round(time.time() - t0, 2)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    def line(nm, m):
        print(f"  {nm:5s} n={m['n']:3d} TP={m['tp']:3d} TN={m['tn']:3d} FP={m['fp']:3d} FN={m['fn']:3d} "
              f"P={m['precision']}% R={m['recall']}% F1={m['f1']}% Acc={m['accuracy']}%")
    print(f"Box khop manifest: {box_check['n_boxes_matched']} box | ver2 tai lap manifest: OK | "
          f"GT phu {coverage:.1%}")
    print(f"== CHINH (own_signature): cham {len(rows)}, AMBIGUOUS loai {len(amb)}")
    line("v1", rep["overall"]["v1"])
    line("ver2", rep["overall"]["v2"])
    if has_box_flag:
        print(f"  (nhan phu thuoc box: chi {len(box_rows)} o box_changed=false; loai {n_box_changed} o box_changed=true)")
    for title, key in (("vai tro", "by_role"), ("required", "by_required"), ("box_changed", "by_box_changed"),
                       ("overflow [box_changed=false]", "by_overflow")):
        if rep[key] is None:
            continue
        print(f"  -- theo {title}:")
        for k, m in rep[key].items():
            print(f"     {k[:30]:30s} n={m['v1']['n']:2d}  v1 TN/FP={m['v1']['tn']}/{m['v1']['fp']}  "
                  f"ver2 TN/FP={m['v2']['tn']}/{m['v2']['fp']}  FN v1/ver2={m['v1']['fn']}/{m['v2']['fn']}")
    sp = rep["secondary_presence"]
    print(f"== PHU (presence, tinh ca muc tran): cham {sp['n_scored']}, AMBIGUOUS loai {sp['n_ambiguous_excluded']}")
    line("v1", sp["overall"]["v1"])
    line("ver2", sp["overall"]["v2"])
    print(f"== O CHI CO MUC TRAN (presence=PRESENT & own_signature=NO): n={overflow_only['n']}  "
          f"v1 bao co ky={overflow_only['v1_detected']}  ver2 bao co ky={overflow_only['v2_detected']}")
    for r in overflow_only["rows"]:
        print(f"     {r['target_id']:28s} {str(r['role'])[:24]:24s} overflow={r['overflow']}  "
              f"v1={r['v1_detected']} ver2={r['v2_detected']}")
    print(f"  -- muc trang: {rep['page_level']['summary']}")
    for w in rep["warnings"]:
        print("\n" + "!" * 100 + f"\n!!! CANH BAO: {w}\n" + "!" * 100)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
