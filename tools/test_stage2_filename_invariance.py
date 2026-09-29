# -*- coding: utf-8 -*-
"""Kiểm thử BẤT BIẾN TÊN FILE cho Tầng 2 (tương tự Filename Permutation Invariance của Tầng 3, AGENTS 5.A).

Câu hỏi kiểm: kết quả Tầng 2 (phân loại + đồng thuận đa trang) có phụ thuộc tên file không?

Cách làm:
  1. Đổi tên 72 ảnh thành tên ngẫu nhiên `UP_<hex>.png` (không còn "__", không còn gợi ý loại chứng từ),
     copy ảnh gốc + ảnh Tầng 1 + JSON Tầng 1 (sửa các trường tên trong JSON) vào thư mục làm việc (scratch).
  2. Metadata upload giữ theo mapping (cùng nhóm, cùng scan_index), còn upload_group_id cũng được đổi sang
     định danh ngẫu nhiên -> chứng minh không logic nào đọc NỘI DUNG id nhóm.
  3. Phân loại cả bộ tên gốc và bộ tên mới, so từng trang (map ngược tên) sau khi bỏ `file_name`,
     `elapsed_ms` và chuẩn hóa id nhóm: phải DIFF = 0 ở 3 mức — trước vote, vote theo nhóm, không nhóm.
  4. ĐỐI CHỨNG DƯƠNG (test phải có răng): một bộ vote CỐ Ý phụ thuộc tên file (nhóm = tên trước "__",
     đúng như bản cũ) phải cho DIFF > 0. Nếu đối chứng cũng ra 0 thì phép so không phát hiện được gì -> FAIL.
  5. In chỉ số chế độ có nhóm vs không nhóm (năng lực thật khi web không gửi metadata nhóm).

Chạy:
  .venv/Scripts/python.exe tools/test_stage2_filename_invariance.py [--stage1-dir DIR]
        [--work-dir scratch/_nb/t2fix/invariance] [--reuse-original RAW.json] [--seed 20250927]
  --reuse-original: file raw (run_full_benchmark_and_save.py --save-raw) của bộ tên gốc trên CÙNG đầu vào
                    Tầng 1, để khỏi OCR lại bộ tên gốc. Bộ tên mới LUÔN được OCR thật.
Không ghi gì vào output/.
"""
import argparse
import copy
import json
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stage2_classifier import Stage2DocumentClassifier, apply_upload_group_voting, set_page_meta
from tools.run_full_benchmark_and_save import (
    DEFAULT_UPLOAD_GROUPS_PATH, cfg_for_stage1_dir, classify_all, load_upload_groups, score, FIELDS,
)

IGNORE_KEYS = {"file_name", "elapsed_ms"}


def _rename_plan(files, seed):
    rng = random.Random(seed)
    used, plan = set(), {}
    for fn in sorted(files):
        while True:
            new = f"UP_{rng.getrandbits(48):012x}.png"
            if new not in used:
                used.add(new)
                plan[fn] = new
                break
    return plan


def build_renamed_workspace(cfg, work_dir, plan):
    """Copy ảnh gốc + đầu ra Tầng 1 sang tên mới. Trả về cfg trỏ vào workspace."""
    work_dir = Path(work_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    samples = work_dir / "samples"
    pages = work_dir / "stage1" / "pages" / "form_samples"
    images = work_dir / "stage1" / "images" / "form_samples"
    for d in (samples, pages, images):
        d.mkdir(parents=True, exist_ok=True)
    for old, new in plan.items():
        shutil.copy2(cfg.samples_dir / old, samples / new)
        if (cfg.stage1_images_dir / old).exists():
            shutil.copy2(cfg.stage1_images_dir / old, images / new)
        jp = cfg.stage1_pages_dir / f"{Path(old).stem}.json"
        if jp.exists():
            m = json.loads(jp.read_text(encoding="utf-8"))
            # Web upload không mang tên cũ: sửa mọi trường tên trong JSON Tầng 1.
            m["file_name"] = new
            if "source_file" in m:
                m["source_file"] = str(samples / new)
            if isinstance(m.get("output"), dict) and m["output"].get("image"):
                m["output"]["image"] = str(images / new)
            (pages / f"{Path(new).stem}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    rcfg = copy.deepcopy(cfg)
    rcfg.samples_dir = samples
    rcfg.stage1_pages_dir = pages
    rcfg.stage1_images_dir = images
    return rcfg


def _canon(rec, gid_back):
    out = {k: v for k, v in rec.items() if k not in IGNORE_KEYS}
    if out.get("upload_group_id") is not None:
        out["upload_group_id"] = gid_back.get(out["upload_group_id"], out["upload_group_id"])
    cid = out.get("voting_cluster_id")
    if cid:
        g, k = cid.rsplit("#", 1)
        out["voting_cluster_id"] = f"{gid_back.get(g, g)}#{k}"
    return out


def diff_results(orig, renamed, plan, gid_back):
    """So từng trang: orig (tên gốc) vs renamed (tên mới, map ngược). Trả về danh sách khác biệt."""
    a = {r["file_name"]: r for r in orig}
    b = {r["file_name"]: r for r in renamed}
    diffs = []
    for old, new in plan.items():
        x, y = a.get(old), b.get(new)
        if x is None or y is None:
            diffs.append((old, "<thiếu bản ghi>", x is not None, y is not None))
            continue
        cx, cy = _canon(x, {}), _canon(y, gid_back)
        for k in sorted(set(cx) | set(cy)):
            if cx.get(k) != cy.get(k):
                diffs.append((old, k, cx.get(k), cy.get(k)))
    return diffs


def voted(raw, meta_by_file):
    res = copy.deepcopy(raw)
    for r in res:
        set_page_meta(r, None if meta_by_file is None else meta_by_file.get(r["file_name"]))
    return apply_upload_group_voting(res)


def _stem_meta(results):
    """ĐỐI CHỨNG DƯƠNG: metadata CỐ Ý suy từ tên file (đúng cơ chế bản cũ). Chỉ dùng để chứng minh
    phép so phát hiện được phụ thuộc tên file; KHÔNG phải cơ chế sản xuất."""
    meta, counters = {}, {}
    for r in sorted(results, key=lambda x: x["file_name"]):
        stem = r["file_name"].split("__")[0]
        idx = counters.get(stem, 0)
        counters[stem] = idx + 1
        meta[r["file_name"]] = {"upload_group_id": "STEM::" + stem, "scan_index": idx}
    return meta


def metrics_row(label, res, gt_map):
    rep, _ = score(res, gt_map, 0.0)
    n = rep["total_documents"]
    row = {"chế độ": label,
           "doc_type": f"{rep['doc_type_accuracy_strict']*100:.2f}",
           "page_role": f"{rep['page_role_accuracy']*100:.2f}",
           "sys strict": f"{rep['system_accuracy']*100:.2f}",
           "sys họ": f"{rep['system_accuracy_family']*100:.2f}",
           "gate": rep["gate_status_distribution"]}
    for f in FIELDS:
        st = rep["field_metrics"][f]
        p = st["exact_match"] / st["pred_present"] * 100 if st["pred_present"] else 0.0
        r_ = st["exact_match"] / st["gt_present"] * 100 if st["gt_present"] else 0.0
        row[f] = f"P{p:.1f}/R{r_:.1f} ({st['exact_match']}/{st['pred_present']}/{st['gt_present']})"
    return row, n


def run(stage1_dir=None, work_dir=None, upload_groups_path=DEFAULT_UPLOAD_GROUPS_PATH,
        reuse_original=None, seed=20250927, verbose=True, raw_original=None):
    cfg = cfg_for_stage1_dir(stage1_dir)
    work_dir = Path(work_dir or ROOT / "scratch" / "_nb" / "t2fix" / "invariance")
    files = sorted(p.name for p in cfg.samples_dir.glob("*.png"))
    plan = _rename_plan(files, seed)
    assert not any("__" in n for n in plan.values())

    groups, ug_info = load_upload_groups(upload_groups_path)
    rng = random.Random(seed + 1)
    gid_fwd = {g: f"G{rng.getrandbits(40):010x}" for g in sorted({m["upload_group_id"] for m in groups.values()})}
    gid_back = {v: k for k, v in gid_fwd.items()}
    groups_renamed = {plan[fn]: {"upload_group_id": gid_fwd[m["upload_group_id"]], "scan_index": m["scan_index"]}
                      for fn, m in groups.items() if fn in plan}

    clf = Stage2DocumentClassifier(cfg)
    if raw_original is not None:
        raw_orig = copy.deepcopy(raw_original)
        print(f"Bộ tên GỐC: dùng kết quả truyền vào ({len(raw_orig)} trang)")
    elif reuse_original:
        blob = json.loads(Path(reuse_original).read_text(encoding="utf-8"))
        if Path(blob["stage1_pages_dir"]).resolve() != Path(cfg.stage1_pages_dir).resolve():
            raise ValueError(f"--reuse-original sinh trên {blob['stage1_pages_dir']}, không phải {cfg.stage1_pages_dir}")
        raw_orig = blob["raw_results"]
        print(f"Bộ tên GỐC: tái dùng {reuse_original} ({len(raw_orig)} trang)")
    else:
        print("Bộ tên GỐC: phân loại...")
        raw_orig, _ = classify_all(cfg, clf, progress=verbose)
    rcfg = build_renamed_workspace(cfg, work_dir, plan)
    print(f"Bộ tên MỚI: {len(plan)} ảnh -> {work_dir} (vd {files[0]} -> {plan[files[0]]}); phân loại...")
    raw_new, sec = classify_all(rcfg, Stage2DocumentClassifier(rcfg), progress=verbose)
    print(f"  xong {sec:.1f}s")

    checks = {}
    d_raw = diff_results(raw_orig, raw_new, plan, gid_back)
    checks["trước vote (classify_document)"] = d_raw
    res_orig_g, res_new_g = voted(raw_orig, groups), voted(raw_new, groups_renamed)
    checks["vote theo upload_group"] = diff_results(res_orig_g, res_new_g, plan, gid_back)
    res_orig_n, res_new_n = voted(raw_orig, None), voted(raw_new, None)
    checks["không nhóm (không vote)"] = diff_results(res_orig_n, res_new_n, plan, gid_back)
    # Đối chứng dương: vote phụ thuộc tên file -> phải lệch.
    ctl_o = voted(raw_orig, _stem_meta(raw_orig))
    ctl_n = voted(raw_new, _stem_meta(raw_new))
    ctl = diff_results(ctl_o, ctl_n, plan, gid_back)
    business_keys = {"doc_type", "system", "form_id", "page_role", "key_fields", "status", "action"}
    ctl_pages = len({d[0] for d in ctl if d[1] in business_keys})

    print("\n=== BẤT BIẾN TÊN FILE ===")
    ok = True
    for k, d in checks.items():
        pages = len({x[0] for x in d})
        print(f"  [{'PASS' if not d else 'FAIL'}] {k:<32}: DIFF = {len(d)} ({pages} trang)")
        for x in d[:10]:
            print(f"       {x}")
        ok &= not d
    print(f"  [{'PASS' if ctl_pages > 0 else 'FAIL'}] đối chứng dương (vote theo tên)  : "
          f"{ctl_pages} trang đổi KẾT QUẢ NGHIỆP VỤ khi đổi tên (phải > 0)")
    ok &= ctl_pages > 0

    gt_map = {g["file_name"]: g for g in json.loads(Path(cfg.gt_path).read_text(encoding="utf-8"))}
    print("\n=== CHỈ SỐ (tên gốc) — có nhóm upload vs không nhóm ===")
    rows = []
    for label, res in (("upload_group", res_orig_g), ("không nhóm", res_orig_n)):
        row, n = metrics_row(label, res, gt_map)
        rows.append(row)
    for row in rows:
        print("  " + " | ".join(f"{k}={v}" for k, v in row.items()))
    print(f"\nKẾT LUẬN: {'ĐẠT' if ok else 'KHÔNG ĐẠT'} (upload groups: {ug_info['status']}, {ug_info['n_groups']} nhóm)")
    return ok, {"checks": {k: len(v) for k, v in checks.items()}, "positive_control_pages": ctl_pages, "metrics": rows}


def main(argv=None):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage1-dir", default=None)
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--upload-groups", default=str(DEFAULT_UPLOAD_GROUPS_PATH))
    ap.add_argument("--reuse-original", default=None)
    ap.add_argument("--seed", type=int, default=20250927)
    ap.add_argument("--json-out", default=None, help="Ghi tóm tắt kết quả ra JSON (tùy chọn).")
    a = ap.parse_args(argv)
    ok, summary = run(a.stage1_dir, a.work_dir, a.upload_groups, a.reuse_original, a.seed)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"ok": ok, **summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
