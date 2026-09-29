"""Benchmark Tầng 2 trên đầu ra Tầng 1 và lưu artifact.

Dùng được theo 2 cách, cùng một logic chấm điểm (nguồn sự thật duy nhất cho notebook Tầng 2):
  * CLI:    .venv/Scripts/python.exe tools/run_full_benchmark_and_save.py [--out-dir DIR]
  * Import: from tools.run_full_benchmark_and_save import run_benchmark

Artifact ghi vào OUT_DIR (mặc định output/stage2_out — đường dẫn CHÍNH THỨC):
  stage2_classified_results.json  <- Tầng 3 (stage3_resolver.DEFAULT_STAGE2_JSON_PATH,
                                     test_stage3_suite.STAGE2_JSON_PATH) và Tầng 4
                                     (generate_nb4_ver2, lp_production_path, build_lp_dynamic_crops) đọc file này.
  stage2_evaluation.csv           <- bảng chấm từng ảnh (chỉ để người đọc).
  stage2_benchmark_report.json    <- chỉ số tổng hợp (AGENTS.md mục 4.D trích từ đây).
Khi phát triển/thử nghiệm: truyền --out-dir ra ngoài output/ để không ghi đè artifact chính thức.

ĐỒNG THUẬN ĐA TRANG (27/09 tối): Tầng 2 KHÔNG còn nhóm trang theo tên file. Nhóm lấy từ metadata đầu vào
tường minh `upload_group_id` + `scan_index` (tools/stage2_classifier.apply_upload_group_voting).
  * Benchmark demo mô phỏng "MỘT SHEET EXCEL = MỘT LẦN UPLOAD": output/stage2_upload_groups.json được
    sinh từ output/form_catalog.json -> sheet_images (nguồn ảnh), bằng --build-upload-groups.
    File này là METADATA ĐẦU VÀO của harness (giống bản ghi upload trên web), khóa nối là tên file ảnh
    do harness đọc; classifier chỉ nhận {upload_group_id, scan_index}, không thấy tên file.
  * --no-upload-groups: mọi trang độc lập (không vote) -> năng lực thật khi không có metadata nhóm.
  * --stage1-dir DIR: đọc đầu ra Tầng 1 từ DIR/{pages,images}/form_samples (mặc định output/stage1_out).
  * --save-raw / --from-raw: lưu / tái dùng kết quả phân loại TRƯỚC vote (bỏ OCR khi so các chế độ vote).
"""
import sys
import os
import json
import time
import argparse
import copy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cv2
import pandas as pd
from tools.stage2_classifier import (
    Stage2Config, Stage2DocumentClassifier,
    apply_upload_group_voting, set_page_meta, normalize_text
)

REPORT_VERSION = "3.5.0"
DEFAULT_UPLOAD_GROUPS_PATH = _ROOT / "output" / "stage2_upload_groups.json"
DEFAULT_CATALOG_PATH = _ROOT / "output" / "form_catalog.json"
UPLOAD_GROUPS_STATUS = "DEMO_SIMULATION_ONE_SHEET_ONE_UPLOAD"


def build_upload_groups(catalog_path=DEFAULT_CATALOG_PATH, out_path=DEFAULT_UPLOAD_GROUPS_PATH):
    """Sinh metadata upload mô phỏng từ nguồn ảnh: mỗi sheet Excel = một lần upload.

    upload_group_id là định danh MỜ (UG_001...), không chứa tên sheet/tên file để không ai "phân tích" nó.
    scan_index = vị trí ảnh trong danh sách ảnh của sheet (thứ tự trích từ Excel).
    Tên sheet chỉ lưu ở trường "sheet" để truy vết, classifier không đọc.
    """
    cat = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    sheet_images = cat.get("sheet_images")
    if not isinstance(sheet_images, dict) or not sheet_images:
        raise ValueError(f"{catalog_path}: thiếu 'sheet_images' (sheet -> danh sách ảnh).")
    pages, groups = {}, []
    for gi, (sheet, paths) in enumerate(sheet_images.items(), start=1):
        gid = f"UG_{gi:03d}"
        names = [Path(str(pp).replace("\\", "/")).name for pp in paths]
        groups.append({"upload_group_id": gid, "sheet": sheet, "n_pages": len(names)})
        for idx, fn in enumerate(names):
            if fn in pages:
                raise ValueError(f"Ảnh {fn} xuất hiện ở hơn một sheet ({pages[fn]['sheet']}, {sheet}).")
            pages[fn] = {"upload_group_id": gid, "scan_index": idx, "sheet": sheet}
    data = {
        "_status": UPLOAD_GROUPS_STATUS,
        "_note": ("MÔ PHỎNG cho benchmark demo: một sheet Excel = một lần upload. Trên web, upload_group_id và "
                  "scan_index do hệ thống tiếp nhận cấp theo lần upload / hồ sơ, KHÔNG suy từ tên file."),
        "_source": str(Path(catalog_path).as_posix()),
        "n_groups": len(groups),
        "n_pages": len(pages),
        "groups": groups,
        "pages": pages,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def load_upload_groups(path):
    """Nạp metadata upload -> {tên file ảnh: {"upload_group_id", "scan_index"}}. Thiếu/hỏng -> lỗi tường minh."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Không có metadata upload {path}. Sinh bằng --build-upload-groups, "
            f"hoặc chạy tường minh --no-upload-groups (không vote).")
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = data.get("pages")
    if not isinstance(pages, dict) or not pages:
        raise ValueError(f"{path}: thiếu 'pages'.")
    out = {}
    for fn, m in pages.items():
        out[fn] = {"upload_group_id": m["upload_group_id"], "scan_index": m["scan_index"]}
        set_page_meta({}, out[fn])  # kiểm định dạng, sai -> ValueError
    return out, {"path": str(path), "status": data.get("_status"), "n_groups": data.get("n_groups"),
                 "n_pages": len(out)}
FIELDS = ("shipment_id", "invoice_no", "po_no", "pxk_no", "transfer_order_no")


def _sys_family(s):
    # Độ chính xác Trục 2 ở cấp HỌ: gộp INTERNAL_* về một họ chuyển kho. Chỉ để so sánh liên tục
    # với các bản trước khi tách kho thuê/kho nội bộ; chỉ số chính thức vẫn là system_accuracy (strict).
    return "INTERNAL" if s and str(s).startswith("INTERNAL_") else s


def attach_upload_groups(results, upload_groups):
    """Gắn (lại) metadata upload cho kết quả phân loại. upload_groups=None -> mọi trang không nhóm.
    Trang không có trong metadata -> không nhóm (tường minh, được đếm trong report), không đoán."""
    missing = []
    for r in results:
        meta = None if upload_groups is None else upload_groups.get(r["file_name"])
        if upload_groups is not None and meta is None:
            missing.append(r["file_name"])
        set_page_meta(r, meta)
    return missing


def classify_all(cfg, classifier, progress=True):
    """Phân loại TOÀN BỘ ảnh trong cfg.samples_dir trên đầu ra Tầng 1 (CHƯA vote, chưa gắn nhóm upload).
    Trả về (raw_results, total_sec)."""
    all_files = sorted([p.name for p in cfg.samples_dir.glob("*.png")])
    if progress:
        print(f"Bắt đầu benchmark trên {len(all_files)} file...")
    raw_results = []
    t0 = time.time()
    for idx, fn in enumerate(all_files):
        stem = Path(fn).stem
        meta_s1 = None
        s1_json_p = cfg.stage1_pages_dir / f"{stem}.json"
        if s1_json_p.exists():
            with open(s1_json_p, "r", encoding="utf-8") as f:
                meta_s1 = json.load(f)

        s1_img_p = cfg.stage1_images_dir / fn
        if s1_img_p.exists():
            img = cv2.imread(str(s1_img_p))
        else:
            img = cv2.imread(str(cfg.samples_dir / fn))

        res = classifier.classify_document(img, meta_stage1=meta_s1, file_name=fn)
        raw_results.append(res)
        if progress and ((idx + 1) % 10 == 0 or idx == len(all_files) - 1):
            print(f"  Đã xử lý [{idx+1:02d}/{len(all_files)}] ({time.time()-t0:.1f}s)", flush=True)
    return raw_results, round(time.time() - t0, 2)


def score(batched_results, gt_map, total_sec):
    """Chấm điểm so với GT. Trả về (report_dict, eval_df)."""
    doc_correct_strict = doc_correct_lenient = role_correct = 0
    system_correct = system_family_correct = 0
    field_stats = {f: {"gt_present": 0, "pred_present": 0, "exact_match": 0} for f in FIELDS}

    eval_rows = []
    for res in batched_results:
        fn = res["file_name"]
        gt = gt_map.get(fn, {})
        exp_doc = gt.get("doc_type", "UNKNOWN")
        pred_doc = res["doc_type"]

        is_strict = (pred_doc == exp_doc)
        # Lenient: coi BB_NO_HANG & BB_TRA_HANG là tương đương
        is_lenient = is_strict or (exp_doc in ["BB_NO_HANG", "BB_TRA_HANG"] and pred_doc in ["BB_NO_HANG", "BB_TRA_HANG"])
        doc_correct_strict += is_strict
        doc_correct_lenient += is_lenient

        exp_role = gt.get("page_role", "HEADER")
        pred_role = res["page_role"]
        role_correct += (pred_role == exp_role)

        exp_sys = gt.get("system", "COMMON")
        pred_sys = res.get("system", "COMMON")
        is_sys_match = (pred_sys == exp_sys)
        system_correct += is_sys_match
        system_family_correct += (_sys_family(pred_sys) == _sys_family(exp_sys))

        exp_fields = gt.get("expected_fields", {})
        pred_fields = res["key_fields"]
        for fld in field_stats:
            exp_val = exp_fields.get(fld)
            pred_val = pred_fields.get(fld)
            if exp_val is not None:
                field_stats[fld]["gt_present"] += 1
            if pred_val is not None:
                field_stats[fld]["pred_present"] += 1
            if exp_val is not None and pred_val is not None and str(exp_val).strip() == str(pred_val).strip():
                field_stats[fld]["exact_match"] += 1

        eval_rows.append({
            "File": fn,
            "Sheet_Goc": gt.get("sheet_origin", ""),
            "Expected_Doc": exp_doc,
            "Pred_Doc": pred_doc,
            "Strict_Match": "✅" if is_strict else "❌",
            "Expected_System": exp_sys,
            "Pred_System": pred_sys,
            "System_Match": "✅" if is_sys_match else "❌",
            "Expected_Role": exp_role,
            "Pred_Role": pred_role,
            "Status": res["status"],
            "Action": res["action"],
            "Confidence": res["confidence"],
            "Margin": res["doc_margin"],
            "Zone2_Scanned": "Có" if res["zone2_scanned"] else "-",
            "Zone2_Filled": "Có" if res["zone2_filled_field"] else "-",
            "Shipment_ID": pred_fields.get("shipment_id") or "-",
            "Exp_Shipment": exp_fields.get("shipment_id") or "-",
            "Invoice_No": pred_fields.get("invoice_no") or "-",
            "Exp_Invoice": exp_fields.get("invoice_no") or "-",
            "PO_No": pred_fields.get("po_no") or "-",
            "Exp_PO": exp_fields.get("po_no") or "-",
            "PXK_No": pred_fields.get("pxk_no") or "-",
            "Exp_PXK": exp_fields.get("pxk_no") or "-",
            "Transfer_Order": pred_fields.get("transfer_order_no") or "-",
            "Exp_Transfer": exp_fields.get("transfer_order_no") or "-"
        })

    total_docs = len(batched_results)
    gate_dist = {k: int(v) for k, v in pd.Series([r["status"] for r in batched_results]).value_counts().items()}
    report = {
        "version": REPORT_VERSION,
        "benchmark_time_sec": total_sec,
        "total_documents": total_docs,
        "doc_type_accuracy_strict": round(doc_correct_strict / total_docs, 4),
        "doc_type_accuracy_lenient": round(doc_correct_lenient / total_docs, 4),
        "page_role_accuracy": round(role_correct / total_docs, 4),
        "system_accuracy": round(system_correct / total_docs, 4),
        "system_accuracy_family": round(system_family_correct / total_docs, 4),
        "field_metrics": field_stats,
        "gate_status_distribution": gate_dist,
        "zone2_scanned_count": sum(1 for r in batched_results if r["zone2_scanned"]),
        "zone2_filled_count": sum(1 for r in batched_results if r["zone2_filled_field"]),
    }
    return report, pd.DataFrame(eval_rows)


def save_artifacts(out_dir, batched_results, eval_df, report):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "stage2_classified_results.json", "w", encoding="utf-8") as f:
        json.dump(batched_results, f, indent=2, ensure_ascii=False)
    eval_df.to_csv(out_dir / "stage2_evaluation.csv", index=False, encoding="utf-8-sig")
    with open(out_dir / "stage2_benchmark_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def print_report(report, eval_df):
    n = report["total_documents"]
    fm = report["field_metrics"]
    pct = lambda k: report[k] * 100
    print(f"\n=== KẾT QUẢ BENCHMARK v{report['version']} ===")
    print(f"Thời gian chạy       : {report['benchmark_time_sec']:.2f}s ({report['benchmark_time_sec']/n:.2f}s/trang)")
    print(f"Độ chính xác STRICT  : {round(report['doc_type_accuracy_strict']*n)}/{n} ({pct('doc_type_accuracy_strict'):.2f}%)")
    print(f"Độ chính xác LENIENT : {round(report['doc_type_accuracy_lenient']*n)}/{n} ({pct('doc_type_accuracy_lenient'):.2f}%)")
    print(f"Độ chính xác Vai trò : {round(report['page_role_accuracy']*n)}/{n} ({pct('page_role_accuracy'):.2f}%)")
    print(f"Độ chính xác Hệ thống: {round(report['system_accuracy']*n)}/{n} ({pct('system_accuracy'):.2f}%)")
    print(f"  (cấp họ, gộp INTERNAL_*): {round(report['system_accuracy_family']*n)}/{n} ({pct('system_accuracy_family'):.2f}%)")
    print(f"Gác cổng trạng thái  : {report['gate_status_distribution']}")
    v = report.get("voting") or {}
    if v:
        print(f"Đồng thuận đa trang  : mode={v['mode']} ({(v.get('upload_groups') or {}).get('status')}) · "
              f"cụm >1 trang: {v['multi_page_clusters']} · trang bị vote sửa: {v['pages_changed_by_voting']} · "
              f"trang không nhóm: {v['pages_without_group']}")
    print(f"Quét Zone 2          : {report['zone2_scanned_count']}/{n} "
          f"({report['zone2_scanned_count']/n*100:.1f}%), cứu {report['zone2_filled_count']} trường")
    print("\n--- FIELD METRICS ---")
    for fld, stat in fm.items():
        p = (stat["exact_match"] / stat["pred_present"] * 100) if stat["pred_present"] > 0 else 0.0
        r = (stat["exact_match"] / stat["gt_present"] * 100) if stat["gt_present"] > 0 else 0.0
        print(f"  {fld:<18}: GT={stat['gt_present']:<2} Pred={stat['pred_present']:<2} Exact={stat['exact_match']:<2} | P={p:5.1f}% | R={r:5.1f}%")
    if (eval_df["Strict_Match"] == "❌").any():
        print("\n--- CÁC TỜ STRICT CHƯA KHỚP ---")
        for _, r in eval_df[eval_df["Strict_Match"] == "❌"].iterrows():
            print(f"  * {r['File']:<25} | Pred: {r['Pred_Doc']:<15} | GT: {r['Expected_Doc']:<18} | Status: {r['Status']}")
    if (eval_df["System_Match"] == "❌").any():
        print("\n--- CÁC TỜ HỆ THỐNG CHƯA KHỚP ---")
        for _, r in eval_df[eval_df["System_Match"] == "❌"].iterrows():
            print(f"  * {r['File']:<25} | Pred Sys: {r['Pred_System']:<15} | GT Sys: {r['Expected_System']:<18}")


def run_benchmark(out_dir=None, cfg=None, classifier=None, save=True, progress=True, verbose=True,
                  upload_groups_path=DEFAULT_UPLOAD_GROUPS_PATH, raw_results=None, total_sec=None):
    """Chạy đủ chuỗi: phân loại -> gắn nhóm upload -> vote theo nhóm -> chấm GT -> (ghi artifact).

    out_dir=None            -> cfg.output_dir (mặc định output/stage2_out, artifact CHÍNH THỨC).
    upload_groups_path=None -> KHÔNG có metadata nhóm: không vote (năng lực từng trang độc lập).
    raw_results             -> tái dùng kết quả phân loại trước vote (bỏ OCR); được deepcopy, không bị sửa.
    Trả về dict {report, results, raw_results, eval_df, out_dir}.
    """
    cfg = cfg or Stage2Config()
    out_dir = Path(out_dir) if out_dir is not None else Path(cfg.output_dir)

    with open(cfg.gt_path, "r", encoding="utf-8") as f:
        gt_map = {it["file_name"]: it for it in json.load(f)}

    if upload_groups_path is not None:
        upload_groups, ug_info = load_upload_groups(upload_groups_path)
    else:
        upload_groups, ug_info = None, {"path": None, "status": "NO_UPLOAD_GROUPS", "n_groups": 0, "n_pages": 0}

    if raw_results is None:
        classifier = classifier or Stage2DocumentClassifier(cfg)
        raw_results, total_sec = classify_all(cfg, classifier, progress=progress)
    batched_results = copy.deepcopy(raw_results)
    missing = attach_upload_groups(batched_results, upload_groups)
    if missing and verbose:
        print(f"[CẢNH BÁO] {len(missing)} trang không có trong metadata upload -> không vote: {missing}")
    batched_results = apply_upload_group_voting(batched_results)
    report, eval_df = score(batched_results, gt_map, total_sec if total_sec is not None else 0.0)
    report["voting"] = {
        "mode": "upload_group" if upload_groups is not None else "none",
        "upload_groups": ug_info,
        "pages_without_group": len([r for r in batched_results if r["voting_group_source"] == "none"]),
        "pages_missing_in_metadata": missing,
        "multi_page_clusters": len({r["voting_cluster_id"] for r in batched_results if r["voting_cluster_size"] > 1}),
        "pages_changed_by_voting": sum(1 for r in batched_results if r["voting_changes"]),
        "split_reasons": {k: int(v) for k, v in pd.Series(
            [r["voting_split_reason"].split("(")[0] for r in batched_results]).value_counts().items()},
        "stage1_pages_dir": str(cfg.stage1_pages_dir),
    }
    if save:
        save_artifacts(out_dir, batched_results, eval_df, report)
    if verbose:
        print_report(report, eval_df)
        if save:
            print(f"\n[OK] Đã ghi 3 artifact vào: {out_dir}")
    return {"report": report, "results": batched_results, "raw_results": raw_results,
            "eval_df": eval_df, "out_dir": out_dir}


def cfg_for_stage1_dir(stage1_dir=None, cfg=None):
    cfg = cfg or Stage2Config()
    if stage1_dir is not None:
        d = Path(stage1_dir)
        cfg.stage1_pages_dir = d / "pages" / "form_samples"
        cfg.stage1_images_dir = d / "images" / "form_samples"
        for p in (cfg.stage1_pages_dir, cfg.stage1_images_dir):
            if not p.is_dir():
                raise FileNotFoundError(f"--stage1-dir: không có {p}")
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(description="Benchmark Tầng 2 và lưu artifact.")
    ap.add_argument("--out-dir", default=None,
                    help="Thư mục ghi artifact (mặc định: Stage2Config.output_dir = output/stage2_out).")
    ap.add_argument("--stage1-dir", default=None, help="Đầu ra Tầng 1 (mặc định output/stage1_out).")
    ap.add_argument("--upload-groups", default=str(DEFAULT_UPLOAD_GROUPS_PATH),
                    help="Metadata upload {file: upload_group_id, scan_index} (mặc định output/stage2_upload_groups.json).")
    ap.add_argument("--no-upload-groups", action="store_true", help="Không metadata nhóm -> không vote.")
    ap.add_argument("--build-upload-groups", action="store_true",
                    help="Sinh --upload-groups từ output/form_catalog.json (1 sheet = 1 upload) rồi thoát.")
    ap.add_argument("--save-raw", default=None, help="Lưu kết quả phân loại TRƯỚC vote ra file JSON.")
    ap.add_argument("--from-raw", default=None, help="Tái dùng kết quả trước vote (bỏ OCR).")
    args = ap.parse_args(argv)
    if args.build_upload_groups:
        d = build_upload_groups(DEFAULT_CATALOG_PATH, args.upload_groups)
        print(f"[OK] {args.upload_groups}: {d['n_groups']} nhóm upload / {d['n_pages']} trang ({d['_status']})")
        return
    cfg = cfg_for_stage1_dir(args.stage1_dir)
    raw, total_sec = None, None
    if args.from_raw:
        blob = json.loads(Path(args.from_raw).read_text(encoding="utf-8"))
        raw, total_sec = blob["raw_results"], blob.get("benchmark_time_sec")
    bench = run_benchmark(out_dir=args.out_dir, cfg=cfg,
                          upload_groups_path=None if args.no_upload_groups else args.upload_groups,
                          raw_results=raw, total_sec=total_sec)
    if args.save_raw:
        Path(args.save_raw).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save_raw).write_text(json.dumps(
            {"stage1_pages_dir": str(cfg.stage1_pages_dir), "benchmark_time_sec": bench["report"]["benchmark_time_sec"],
             "raw_results": bench["raw_results"]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] raw -> {args.save_raw}")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
