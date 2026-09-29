"""Đối chiếu adapter web (runner.run_upload_group) với artifact chính thức của chuỗi notebook.

Chạy 72 ảnh demo theo đúng 52 nhóm upload mô phỏng (output/stage2_upload_groups.json), mỗi nhóm
một lần run_upload_group (như web), rồi so:
  T1  : status / action / source_type / warns / rejects từng trang  vs output/stage1_out/pages/form_samples/*.json
  T2  : doc_type / system / page_role / status / key_fields          vs output/stage2_out/stage2_classified_results.json
  T4  : doc_status + detected từng ô (trang LOADING_PLAN)            vs output/stage4_out/stage4_verification_manifest_v2.json
  T3  : KHÔNG so thẳng (web gom trong 1 bộ upload, notebook gom trên 72 ảnh) — chỉ in thống kê.
  Hồ sơ LP: so doc_status theo tập trang.

Tham chiếu mã chuyến: --reference bật (như chuỗi chính thức). Mặc định bật để so parity;
web mặc định TẮT.

    python web/backend/scripts/parity_check.py --out <dir> [--no-reference] [--workers 4]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))  # web/backend
from app.pipeline import runner  # noqa: E402  (runner tự chdir về gốc repo)

ROOT = runner.REPO_ROOT


def load(p):
    return json.loads((ROOT / p).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-reference", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-groups", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    use_ref = not a.no_reference

    ug = load("output/stage2_upload_groups.json")
    groups = {}
    for fn, m in ug["pages"].items():
        groups.setdefault(m["upload_group_id"], []).append({"file_name": fn, "scan_index": m["scan_index"],
                                                           "path": str(ROOT / "output/form_samples" / fn)})
    gids = sorted(groups)
    if a.limit_groups:
        gids = gids[:a.limit_groups]

    t0 = time.time()
    results = {}
    for k, gid in enumerate(gids):
        res = runner.run_upload_group(groups[gid], gid, out / "work" / gid, use_reference=use_ref,
                                      stage1_workers=a.workers)
        results[gid] = res
        print(f"[{k+1:02d}/{len(gids)}] {gid} {len(groups[gid])} trang {res['timings']} "
              f"({time.time()-t0:.0f}s)", flush=True)
    total_sec = round(time.time() - t0, 1)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- so sánh ----
    rep = {"reference": use_ref, "total_sec": total_sec, "n_groups": len(gids)}
    s1_off = {}
    for p in (ROOT / "output/stage1_out/pages/form_samples").glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        s1_off[r["file_name"]] = r
    s2_off = {r["file_name"]: r for r in load("output/stage2_out/stage2_classified_results.json")}
    v2_off = {d["file_name"]: d for d in load("output/stage4_out/stage4_verification_manifest_v2.json")["documents"]}

    diffs = {"T1": [], "T2": [], "T4": []}
    n = Counter()
    s4_web_status = Counter()
    for gid, res in results.items():
        for r in res["stage1"]:
            fn = r["file_name"]; o = s1_off.get(fn, {}); n["T1"] += 1
            for k in ("status", "action", "source_type", "warns", "rejects"):
                if r.get(k) != o.get(k):
                    diffs["T1"].append({"file": fn, "field": k, "web": r.get(k), "official": o.get(k)})
        for r in res["stage2"]:
            fn = r["file_name"]; o = s2_off.get(fn, {}); n["T2"] += 1
            for k in ("doc_type", "system", "page_role", "status", "key_fields"):
                if r.get(k) != o.get(k):
                    diffs["T2"].append({"file": fn, "field": k, "web": r.get(k), "official": o.get(k)})
        for r in res["stage4_pages"]:
            fn = r["file_name"]; s4_web_status[r["doc_status"]] += 1
            if r["doc_type"] != "LOADING_PLAN" and v2_off.get(fn, {}).get("doc_type") != "LOADING_PLAN":
                continue
            o = v2_off.get(fn, {}); n["T4"] += 1
            if r["doc_status"] != o.get("doc_status"):
                diffs["T4"].append({"file": fn, "field": "doc_status", "web": r["doc_status"],
                                    "official": o.get("doc_status")})
            wt = [(t["role"], t["detected"], t["required"]) for t in r["targets"]]
            ot = [(t["role"], t["detected"], t["required"]) for t in o.get("targets", [])]
            if wt != ot:
                diffs["T4"].append({"file": fn, "field": "targets(role,detected,required)", "web": wt, "official": ot})
    rep["n_compared"] = dict(n)
    rep["n_diffs"] = {k: len(v) for k, v in diffs.items()}
    rep["files_with_diff"] = {k: sorted({d["file"] for d in v}) for k, v in diffs.items()}
    rep["diffs"] = diffs
    rep["web_stage4_page_status"] = dict(s4_web_status)
    dos = Counter()
    for res in results.values():
        for d in res["stage4_dossiers"]["dossiers"]:
            dos[d["doc_status"]] += 1
    rep["web_lp_dossier_status"] = dict(dos)
    rep["official_lp_dossier_status"] = load("output/stage4_out/stage4_verification_manifest_v2.json") \
        .get("dossier_verdicts", {}).get("summary")
    rep["web_stage3_batches_total"] = sum(r["stage3_manifest"]["metadata"]["total_batches"] for r in results.values())
    rep["timings_sum"] = {k: round(sum(r["timings"][k] for r in results.values()), 1) for k in ("T1", "T2", "T3", "T4")}
    (out / "parity_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in rep if k != "diffs"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
