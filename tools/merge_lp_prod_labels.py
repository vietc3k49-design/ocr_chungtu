# -*- coding: utf-8 -*-
"""
Hop nhat nhan GT v3 (duong production) — output/stage4_dynamic_gt_v3/labels_<annotator>.json
-> output/stage4_dynamic_gt_v3/gt_labeled.json

Kiem tra nghiem ngat, KHONG tu dien nhan:
 - moi annotator phai co DUNG 1 nhan cho MOI target trong skeleton va MOI trang needs_page_label
 - thieu / trung / target_id (page_id) la / gia tri khong hop le  -> in loi, exit 1
 - so annotator < --min-annotators                                -> exit 1
 - `own_signature` (nhan CHAM DIEM CHINH) bat buoc voi moi target  -> thieu la exit 1
Nhan cuoi = da so tuyet doi (> n/2). Khong co da so:
 - own_signature / presence / has_signature_block -> AMBIGUOUS
 - frame_quality / overflow / sig_cut -> null + ghi vao `disagreements`
Kem thong ke dong thuan: % nhat tri, dong thuan cap doi trung binh, Fleiss kappa.

Chay:  .venv/Scripts/python.exe tools/merge_lp_prod_labels.py [--dir DIR] [--min-annotators 3]
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "output/stage4_dynamic_gt_v3"

T_FIELDS = {
    # own_signature = CHINH vai tro nay da ky/ghi ten tay (muc tran tu cot hang xom KHONG tinh;
    # chu ky cua vai tro lech ra ngoai khung van YES). Day la nhan CHAM DIEM CHINH cua bench.
    "own_signature": {"YES", "NO", "AMBIGUOUS"},
    "presence": {"PRESENT", "ABSENT", "AMBIGUOUS"},   # phu: chi do "co muc tay trong khung"
    "frame_quality": {"GOOD", "PARTIAL", "WRONG_PLACE"},
    "overflow": {"NONE", "FROM_LEFT", "FROM_RIGHT", "BOTH"},
    "sig_cut": {"YES", "NO"},
}
P_FIELDS = {"has_signature_block": {"YES", "NO", "AMBIGUOUS"}}
AMBIG_FALLBACK = {"own_signature", "presence", "has_signature_block"}   # khong co da so -> AMBIGUOUS


def fleiss_kappa(items, categories):
    """items: list cac list nhan (moi item cung so nguoi n). Tra None neu khong tinh duoc."""
    items = [it for it in items if it]
    if not items:
        return None
    n = len(items[0])
    if n < 2 or any(len(it) != n for it in items):
        return None
    N = len(items)
    cats = sorted(categories)
    counts = [[Counter(it)[c] for c in cats] for it in items]
    p_j = [sum(row[j] for row in counts) / (N * n) for j in range(len(cats))]
    P_i = [(sum(x * x for x in row) - n) / (n * (n - 1)) for row in counts]
    P_bar = sum(P_i) / N
    P_e = sum(p * p for p in p_j)
    if abs(1 - P_e) < 1e-12:
        return None   # moi nguoi cung mot nhan duy nhat tren toan tap: kappa khong xac dinh
    return round((P_bar - P_e) / (1 - P_e), 4)


def agreement_stats(items, categories):
    if not items:
        return {"n_items": 0}
    n = len(items[0])
    unanimous = sum(1 for it in items if len(set(it)) == 1)
    pair_tot = pair_ok = 0
    for it in items:
        for a in range(n):
            for b in range(a + 1, n):
                pair_tot += 1
                pair_ok += it[a] == it[b]
    majority = sum(1 for it in items if Counter(it).most_common(1)[0][1] * 2 > n)
    return {
        "n_items": len(items), "n_annotators": n,
        "pct_unanimous": round(unanimous / len(items) * 100, 2),
        "pct_has_majority": round(majority / len(items) * 100, 2),
        "mean_pairwise_agreement": round(pair_ok / pair_tot * 100, 2) if pair_tot else None,
        "fleiss_kappa": fleiss_kappa(items, categories),
    }


def majority(votes):
    c = Counter(votes).most_common()
    if c and c[0][1] * 2 > len(votes):
        return c[0][0]
    return None


def load_annotator(f, tids, pids, errs):
    name = re.fullmatch(r"labels_([A-Za-z0-9_]+)\.json", f.name).group(1)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        errs.append(f"[{name}] khong doc duoc JSON: {e}")
        return name, {}, {}
    tl, pl = {}, {}
    for kind, arr, key, ids, fields, store in (
            ("target", d.get("targets", []), "target_id", tids, T_FIELDS, tl),
            ("page", d.get("pages", []), "page_id", pids, P_FIELDS, pl)):
        for L in arr:
            i = L.get(key)
            if i not in ids:
                errs.append(f"[{name}] {kind} la: {i!r}")
                continue
            if i in store:
                errs.append(f"[{name}] {kind} trung: {i}")
                continue
            for fld, allowed in fields.items():
                if fld not in L:
                    errs.append(f"[{name}] {i} THIEU truong bat buoc `{fld}`")
                elif L.get(fld) not in allowed:
                    errs.append(f"[{name}] {i}.{fld}={L.get(fld)!r} khong thuoc {sorted(allowed)}")
            store[i] = L
        miss = [i for i in ids if i not in store]
        if miss:
            errs.append(f"[{name}] THIEU {len(miss)} {kind}: {miss[:8]}{' ...' if len(miss) > 8 else ''}")
    return name, tl, pl


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--min-annotators", type=int, default=3)
    ap.add_argument("--out", default=None, help="mac dinh <dir>/gt_labeled.json")
    a = ap.parse_args()
    D = Path(a.dir)
    skel = json.loads((D / "skeleton.json").read_text(encoding="utf-8"))
    tids = [t["target_id"] for t in skel["targets"]]
    pids = [p["page_id"] for p in skel["pages"] if p.get("needs_page_label")]
    if len(set(tids)) != len(tids):
        sys.exit("SKELETON LOI: target_id trung")

    files = sorted(f for f in D.glob("labels_*.json") if re.fullmatch(r"labels_[A-Za-z0-9_]+\.json", f.name))
    errs = []
    if len(files) < a.min_annotators:
        errs.append(f"CHI CO {len(files)} file nhan (can >= {a.min_annotators}): {[f.name for f in files]}")
    ann = [load_annotator(f, tids, pids, errs) for f in files]
    if errs:
        for e in errs:
            print("!! " + e)
        sys.exit(1)
    names = [n for n, _, _ in ann]
    print(f"Annotator: {names}")

    disagreements = []
    out_t, out_p = [], []
    for t in skel["targets"]:
        tid = t["target_id"]
        rec = dict(t)
        votes = {}
        for fld in T_FIELDS:
            vs = [tl[tid][fld] for _, tl, _ in ann]
            votes[fld] = dict(zip(names, vs))
            m = majority(vs)
            if m is None:
                disagreements.append({"id": tid, "field": fld, "votes": votes[fld]})
                m = "AMBIGUOUS" if fld in AMBIG_FALLBACK else None
            rec[fld] = m
        rec["votes"] = votes
        rec["notes"] = {n: tl[tid].get("note") for n, tl, _ in ann if tl[tid].get("note")}
        out_t.append(rec)
    for p in skel["pages"]:
        rec = dict(p)
        if p.get("needs_page_label"):
            vs = [pl[p["page_id"]]["has_signature_block"] for _, _, pl in ann]
            m = majority(vs)
            if m is None:
                disagreements.append({"id": p["page_id"], "field": "has_signature_block", "votes": dict(zip(names, vs))})
                m = "AMBIGUOUS"
            rec["has_signature_block"] = m
            rec["votes"] = {"has_signature_block": dict(zip(names, vs))}
            rec["notes"] = {n: pl[p["page_id"]].get("note") for n, _, pl in ann if pl[p["page_id"]].get("note")}
        out_p.append(rec)

    agreement = {fld: agreement_stats([[tl[tid][fld] for _, tl, _ in ann] for tid in tids], allowed)
                 for fld, allowed in T_FIELDS.items()}
    agreement["has_signature_block"] = agreement_stats(
        [[pl[pid]["has_signature_block"] for _, _, pl in ann] for pid in pids], P_FIELDS["has_signature_block"])

    gt = {k: v for k, v in skel.items() if k not in ("targets", "pages")}
    gt.update({
        "version": "3.0.0",
        "annotation_method": (f"DIRECT_IMAGE_REVIEW — {len(names)} annotator doc lap, moi nguoi gan TOAN BO; "
                              "khong chay detector, khong doc manifest/benchmark/GT cu; nhan = da so tuyet doi"),
        "annotators": names,
        "primary_label": "own_signature",
        "own_signature_distribution": dict(Counter(t["own_signature"] for t in out_t)),
        "label_distribution": dict(Counter(t["presence"] for t in out_t)),
        "overflow_only_count": sum(1 for t in out_t if t["presence"] == "PRESENT" and t["own_signature"] == "NO"),
        "frame_quality_distribution": dict(Counter(str(t["frame_quality"]) for t in out_t)),
        "overflow_distribution": dict(Counter(str(t["overflow"]) for t in out_t)),
        "sig_cut_distribution": dict(Counter(str(t["sig_cut"]) for t in out_t)),
        "page_label_distribution": dict(Counter(p["has_signature_block"] for p in out_p if p.get("needs_page_label"))),
        "agreement": agreement,
        "disagreements": disagreements,
        "pages": out_p,
        "targets": out_t,
    })
    out = Path(a.out) if a.out else D / "gt_labeled.json"
    out.write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"TONG {len(out_t)} target, {len(pids)} trang can xac nhan")
    print("own_signature (CHINH):", gt["own_signature_distribution"])
    print("presence (phu):", gt["label_distribution"])
    print("o chi co muc tran (presence=PRESENT & own_signature=NO):", gt["overflow_only_count"])
    print("trang:", gt["page_label_distribution"])
    for fld, s in agreement.items():
        print(f"  dong thuan {fld:20s} nhat_tri={s.get('pct_unanimous')}% cap_doi={s.get('mean_pairwise_agreement')}% "
              f"kappa={s.get('fleiss_kappa')}")
    print(f"  bat dong: {len(disagreements)} truong")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
