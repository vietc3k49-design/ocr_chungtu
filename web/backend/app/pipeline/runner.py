"""Adapter chạy pipeline KIDO T1 → T2 → T3 → T4 (ver2, LOADING_PLAN) cho MỘT bộ upload.

Nguyên tắc: KHÔNG viết lại logic pipeline — chỉ gọi module trong `tools/` theo đúng chuỗi chính thức
(README §2.B, AGENTS.md §9.13):
  * T1: `stage1_normalizer.process_one` với cấu hình của `tools/run_stage1_on_form_samples.py`.
  * T2: `Stage2DocumentClassifier.classify_document(..., page_meta={upload_group_id, scan_index})`
        rồi `apply_upload_group_voting` — y như `tools/run_full_benchmark_and_save.py`.
  * T3: `stage3_resolver.run_stage3_pipeline` + `build_manifest_data`.
        ⚠️ KHÁC chuỗi chính thức CÓ CHỦ Ý: chỉ chạy trên các trang của MỘT bộ upload (quyết định
        người dùng 27/09), nên không so thẳng được với số 72/0/28 đo trên cả 72 ảnh.
  * T4: chép 1-1 nhánh LOADING_PLAN của Cell 3 `tools/generate_nb4_ver2.py`
        (zone 3b → chính sách required theo kênh → `verify_single_target` ver2 → verdict ver2),
        rồi `evaluate_lp_dossier_verdicts` (Cell 3b). Doc_type khác ⇒ ABSTAIN tường minh.

Dữ liệu tham chiếu mã chuyến (bản demo suy từ GT) mặc định TẮT; `use_reference=True` bật cả
`config/stage2_shipment_reference.json` lẫn `config/stage3_shipment_reference.json`. Chế độ chạy
được ghi vào kết quả (`reference`).
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

_env_root = os.environ.get("KIDO_REPO_ROOT")
REPO_ROOT = Path(_env_root) if _env_root else Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# Các module tools/ đọc config bằng đường dẫn TƯƠNG ĐỐI (vd config/stage2_shipment_reference.json,
# output/form_catalog.json) — phải chạy với cwd = gốc repo.
os.chdir(REPO_ROOT)

import cv2  # noqa: E402

from tools import stage1_normalizer as s1  # noqa: E402
from tools import stage2_classifier as s2mod  # noqa: E402
from tools import stage3_resolver as s3  # noqa: E402
from tools.kido_pipeline import detect_loading_plan_signature_zone  # noqa: E402
from tools.stage4_verifier import detect_document_modality  # noqa: E402
from tools.stage4_verifier_v2 import (  # noqa: E402
    evaluate_document_verdict_v2,
    verify_single_target,
)
from tools.stage4_template_verifier import (  # noqa: E402
    merge_template_dossiers,
    verify_template_page,
)
from tools.stage4_required_policy import (  # noqa: E402
    apply_lp_required_policy,
    evaluate_lp_dossier_verdicts,
    load_lp_required_policy,
    policy_summary,
)

PIPELINE_CONTRACT_VERSION = "web-1.1.0"
# Hai nhánh Tầng 4 khác hẳn nhau về cách LẤY ô ký:
#   * LOADING_PLAN  -> vùng ký ĐỘNG, dò nhãn từng ảnh ở Tầng 3b (bảng hàng hoá co giãn).
#   * Hạng A        -> toạ độ CỨNG trong config/form_signature_templates.json.
LP_DOC_TYPES = ("LOADING_PLAN",)
TEMPLATE_DOC_TYPES = ("LENH_DIEU_XE", "BIEU_DO_NHIET_DO")
IN_SCOPE_DOC_TYPES = LP_DOC_TYPES + TEMPLATE_DOC_TYPES
TARGET_H = 2200

# Cấu hình Tầng 1 của runner chính thức (tools/run_stage1_on_form_samples.py:main).
# ⚠️ Ngưỡng đã NỚI cho ảnh demo trích Excel (~850px, 45–150 DPI). Ghi vào kết quả để truy vết.
STAGE1_CFG_KW = dict(
    batch_mode="folder",
    min_long_edge=500,
    warn_long_edge=800,
    dpi_reject=40.0,
    dpi_warn=70.0,
    blur_reject=25.0,
    blur_warn=70.0,
    save_debug=True,
)

# Bảng tham chiếu Tầng 2 được nạp lúc import module — giữ bản gốc để bật/tắt theo từng job.
_S2_REFERENCE_ORIGINAL = dict(s2mod.SHIPMENT_OCR_CORRECTIONS)
_S2_CLASSIFIER: Optional[s2mod.Stage2DocumentClassifier] = None
_LP_POLICY: Optional[Dict[str, Any]] = None

ProgressCb = Callable[[str, int, int, str], None]


def _noop_progress(stage: str, done: int, total: int, msg: str) -> None:
    pass


def _jsonable(o: Any) -> Any:
    """Chuyển numpy/Path về kiểu JSON; bỏ mask (ảnh nhị phân) khỏi kết quả."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if k != "mask"}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return None
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, Path):
        return str(o)
    return o


# ---------------------------------------------------------------------------
# Tầng 1
# ---------------------------------------------------------------------------
def _stage1_one(args) -> Dict[str, Any]:
    """Chạy trong tiến trình con. Trả bản ghi T1 (đã ghi ảnh chuẩn hóa nếu có)."""
    src_path, idx, group_id, out_img_path = args
    cfg = s1.Stage1Config(**STAGE1_CFG_KW)
    try:
        rec, norm_img = s1.process_one(src_path, cfg, batch_id=group_id, page_index=idx, save=False)
        out_rec = rec.get("output") or {}
        if norm_img is not None:
            Path(out_img_path).parent.mkdir(parents=True, exist_ok=True)
            s1.imwrite_unicode(out_img_path, norm_img, cfg.jpeg_quality)
            out_rec["image"] = out_img_path
        else:
            out_rec["image"] = None
        rec["output"] = out_rec
        return _jsonable(rec)
    except Exception as e:  # giống runner chính thức: lỗi ⇒ CHUP_LAI tường minh
        return {"source_file": src_path, "file_name": os.path.basename(src_path),
                "status": "CHUP_LAI", "action": "YEU_CAU_CHUP_LAI", "error": f"{type(e).__name__}: {e}"}


def run_stage1(pages: List[Dict[str, Any]], group_id: str, work_dir: Path,
               max_workers: int, progress: ProgressCb) -> Dict[str, Dict[str, Any]]:
    out_dir = work_dir / "stage1"
    tasks = [(p["path"], p["scan_index"], group_id, str(out_dir / p["file_name"])) for p in pages]
    results: Dict[str, Dict[str, Any]] = {}
    total = len(tasks)
    progress("T1", 0, total, "Chuẩn hóa ảnh")
    if max_workers <= 1 or total == 1:
        for i, t in enumerate(tasks):
            rec = _stage1_one(t)
            results[pages[i]["file_name"]] = rec
            progress("T1", i + 1, total, rec.get("file_name", ""))
    else:
        with ProcessPoolExecutor(max_workers=min(max_workers, total)) as ex:
            for i, rec in enumerate(ex.map(_stage1_one, tasks)):
                results[pages[i]["file_name"]] = rec
                progress("T1", i + 1, total, rec.get("file_name", ""))
    return results


# ---------------------------------------------------------------------------
# Tầng 2
# ---------------------------------------------------------------------------
def _classifier() -> s2mod.Stage2DocumentClassifier:
    global _S2_CLASSIFIER
    if _S2_CLASSIFIER is None:
        _S2_CLASSIFIER = s2mod.Stage2DocumentClassifier(s2mod.Stage2Config())
    return _S2_CLASSIFIER


def run_stage2(pages: List[Dict[str, Any]], s1_recs: Dict[str, Dict[str, Any]], group_id: str,
               use_reference: bool, progress: ProgressCb) -> List[Dict[str, Any]]:
    s2mod.SHIPMENT_OCR_CORRECTIONS = dict(_S2_REFERENCE_ORIGINAL) if use_reference else {}
    clf = _classifier()
    out = []
    total = len(pages)
    progress("T2", 0, total, "Phân loại chứng từ")
    for i, p in enumerate(pages):
        fn = p["file_name"]
        meta_s1 = s1_recs.get(fn)
        s1_img = ((meta_s1 or {}).get("output") or {}).get("image")
        # Như classify_all: ảnh T1 nếu có, không thì ảnh gốc (T2 tự chặn trang YEU_CAU_CHUP_LAI).
        img = cv2.imread(s1_img) if s1_img and Path(s1_img).exists() else cv2.imread(p["path"])
        res = clf.classify_document(img, meta_stage1=meta_s1, file_name=fn,
                                    page_meta={"upload_group_id": group_id, "scan_index": p["scan_index"]})
        out.append(res)
        progress("T2", i + 1, total, fn)
    s2mod.apply_upload_group_voting(out)
    return [_jsonable(r) for r in out]


# ---------------------------------------------------------------------------
# Tầng 3
# ---------------------------------------------------------------------------
def run_stage3(s2_records: List[Dict[str, Any]], use_reference: bool) -> Dict[str, Any]:
    with open(s3.DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        business_config = json.load(f)
    ref, ref_info = s3.load_shipment_reference(s3.DEFAULT_REFERENCE_PATH if use_reference else None)
    business_config = s3.apply_shipment_reference(business_config, ref, ref_info)
    with open(s3.DEFAULT_CATALOG_JSON_PATH, "r", encoding="utf-8") as f:
        form_catalog = json.load(f)
    records = sorted(copy.deepcopy(s2_records), key=lambda r: r["scan_index"])
    result = s3.run_stage3_pipeline(records, business_config, form_catalog)
    return _jsonable(s3.build_manifest_data(result))


# ---------------------------------------------------------------------------
# Tầng 4 (ver2, LOADING_PLAN) — chép 1-1 Cell 3 + Cell 3b của tools/generate_nb4_ver2.py
# ---------------------------------------------------------------------------
def _policy() -> Dict[str, Any]:
    global _LP_POLICY
    if _LP_POLICY is None:
        _LP_POLICY = load_lp_required_policy()
    return _LP_POLICY


def _abstain_page(fn, doc_type, system, batch_id, page_role, zone_status, doc_status, reason):
    return {"file_name": fn, "doc_type": doc_type, "system": system, "batch_id": batch_id,
            "page_role": page_role, "modality": "UNKNOWN", "zone_status": zone_status, "anchor_y": None,
            "doc_status": doc_status, "action": "ABSTAIN", "reason": reason,
            "required_targets": 0, "detected_required_targets": 0, "targets": []}


def run_stage4_page(fn: str, s2: Dict[str, Any], image_path: Optional[str], batch_id: str) -> Dict[str, Any]:
    pol = _policy()
    doc_type = s2.get("doc_type", "UNKNOWN")
    system = s2.get("system", "COMMON")
    page_role = s2.get("page_role", "HEADER")
    if doc_type not in IN_SCOPE_DOC_TYPES:
        return _abstain_page(fn, doc_type, system, batch_id, page_role, "CHUA_CHUAN_HOA_VUNG_KY",
                             "CHUA_CHUAN_HOA_VUNG_KY",
                             ("HOA_DON: HOÃN — cần template Tầng 3b riêng theo từng chi nhánh/kênh, không chạy Tầng 4"
                              if doc_type == "HOA_DON" else
                              "Loại chứng từ này chưa có template ô ký — không chạy Tầng 4"))
    raw = cv2.imread(image_path) if image_path else None
    if raw is None:
        err = "IMAGE_NOT_FOUND" if not image_path else "UNREADABLE"
        return _abstain_page(fn, doc_type, system, batch_id, page_role, err, "LOI_DOC_ANH",
                             f"Không đọc được ảnh đầu vào ({err}): {image_path or fn}")
    scale = float(TARGET_H) / raw.shape[0]
    a4 = cv2.resize(raw, (int(raw.shape[1] * scale), TARGET_H))

    # --- Nhánh biểu mẫu hạng A: ô ký lấy thẳng từ template toạ độ cứng, không qua Tầng 3b ---
    if doc_type in TEMPLATE_DOC_TYPES:
        r = verify_template_page(a4, doc_type)
        r.update({"file_name": fn, "doc_type": doc_type, "system": system,
                  "batch_id": batch_id, "page_role": page_role,
                  "zone_has_signatures": bool(r.get("targets")),
                  "zone_description": f"Template hạng A — {len(r.get('targets') or [])} ô khai báo sẵn",
                  "anchor_y": None, "required_policy": None})
        return r

    zone = detect_loading_plan_signature_zone(a4, page_role=page_role)
    zone_status = zone.get("status")
    zone_has_sig = bool(zone.get("has_signatures", False))
    zone_targets = zone.get("targets") or []
    verified_targets: List[Dict[str, Any]] = []
    if zone_status == "PAGE_1_NO_SIGNATURES":
        doc_status, action = "TRANG_1_CHUA_KY", "HOP_LE"
        reason = "Trang 1/2: Bảng hàng hóa dài phủ kín trang, khối ký nằm ở Trang 2"
        modality = "N/A"
    elif (not zone_has_sig) or (not zone_targets):
        doc_status, action = "CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"
        why = "has_signatures=False" if not zone_has_sig else "targets rỗng"
        reason = (f"Tầng 3b không dựng được vùng ký [{zone_status}] ({why}): "
                  f"{zone.get('description', '')} — không chạy Tầng 4")
        modality = "N/A"
    else:
        modality = detect_document_modality(a4)["modality"]
        is_color = modality == "TRUE_COLOR"
        targets = apply_lp_required_policy(zone_targets, system)
        for t in targets:
            t_copy = dict(t)
            if "stamp_class" not in t_copy:
                if t_copy.get("expected_color") == "any_stamp" or "tiếp nhận" in t_copy.get("role", "").lower():
                    t_copy["stamp_class"] = "SUPERMARKET_SQUARE"
                elif t_copy.get("expected_color") == "red_stamp" or "mộc đỏ" in t_copy.get("role", "").lower():
                    t_copy["stamp_class"] = "COMPANY_ROUND_RED"
            res = verify_single_target(a4, t_copy, is_color=is_color)
            verified_targets.append({
                "role": t_copy.get("role"),
                "stamp_class": t_copy.get("stamp_class"),
                "expected_color": t_copy.get("expected_color"),
                "required": t_copy.get("required", True),
                "required_original": t_copy.get("required_original"),
                "required_source": t_copy.get("required_source"),
                "policy_channel": t_copy.get("policy_channel"),
                "policy_channel_unresolved": t_copy.get("policy_channel_unresolved"),
                "box_norm": t_copy.get("box_norm"),
                "bbox_px": res.get("bbox_px"),
                "detected": res.get("detected"),
                "confidence": round(res.get("confidence", 0.0), 3),
                "ink_type": res.get("ink_type"),
                "reason": res.get("reason"),
                "evidence": res.get("evidence"),
                "review_required": bool(res.get("review_required", False)),
                "blue_own_mm2": res.get("blue_own_mm2"),
                "blue_edge_mm2": res.get("blue_edge_mm2"),
                "px_per_mm": res.get("px_per_mm"),
                "mask": res.get("mask"),
            })
        doc_status, action, reason = evaluate_document_verdict_v2(verified_targets, is_color=is_color)
    return {
        "file_name": fn, "doc_type": doc_type, "system": system, "batch_id": batch_id,
        "page_role": page_role, "modality": modality, "zone_status": zone_status,
        "zone_has_signatures": zone_has_sig, "zone_description": zone.get("description"),
        "anchor_y": zone.get("anchor_y"), "doc_status": doc_status, "action": action, "reason": reason,
        "required_policy": policy_summary(system, pol),
        "required_targets": len([v for v in verified_targets if v.get("required", True)]),
        "detected_required_targets": len([v for v in verified_targets
                                          if v.get("required", True) and v.get("detected")]),
        "targets": verified_targets,
        # Kích thước ảnh A4 mà box_norm quy chiếu tới (để frontend vẽ đúng tỉ lệ).
        "a4_size": [int(a4.shape[1]), int(a4.shape[0])],
    }


def run_stage4(s2_records: List[Dict[str, Any]], s1_recs: Dict[str, Dict[str, Any]],
               pages: List[Dict[str, Any]], manifest: Dict[str, Any], progress: ProgressCb):
    doc_batch_map: Dict[str, str] = {}
    for b in manifest.get("batches", []):
        for d in b.get("documents", []):
            if d.get("file_name"):
                doc_batch_map[d["file_name"]] = b.get("batch_id", "UNKNOWN_BATCH")
            for pf in d.get("page_files", []) or []:
                doc_batch_map[Path(pf).name] = b.get("batch_id", "UNKNOWN_BATCH")
    raw_path = {p["file_name"]: p["path"] for p in pages}
    page_results = []
    total = len(s2_records)
    progress("T4", 0, total, "Kiểm chữ ký (Loading Plan + biểu mẫu hạng A)")
    for i, s2 in enumerate(sorted(s2_records, key=lambda r: r["scan_index"])):
        fn = s2["file_name"]
        s1_img = ((s1_recs.get(fn) or {}).get("output") or {}).get("image")
        # Như Cell 3 get_image_path: ảnh T1 nếu có, không thì ảnh gốc.
        img_path = s1_img if s1_img and Path(s1_img).exists() else raw_path.get(fn)
        page_results.append(run_stage4_page(fn, s2, img_path, doc_batch_map.get(fn, "BATCH_ISOLATED")))
        progress("T4", i + 1, total, fn)
    dossiers = evaluate_lp_dossier_verdicts(page_results, manifest, evaluate_document_verdict_v2, _policy())
    # Trang hạng A bị `evaluate_lp_dossier_verdicts` bỏ qua (nó lọc doc_type == LOADING_PLAN)
    # ⇒ phải gộp hồ sơ một-trang của chúng vào, nếu không bộ có Lệnh điều xe thiếu chữ ký
    # vẫn cho tóm tắt hồ sơ "sạch" (PASS lỏng).
    dossiers = merge_template_dossiers(dossiers, page_results)
    return [_jsonable(r) for r in page_results], _jsonable(dossiers)


# ---------------------------------------------------------------------------
# Toàn chuỗi
# ---------------------------------------------------------------------------
def run_upload_group(pages: List[Dict[str, Any]], group_id: str, work_dir: Path,
                     use_reference: bool = False, stage1_workers: int = 4,
                     progress: Optional[ProgressCb] = None) -> Dict[str, Any]:
    """pages: [{"path": ảnh gốc, "file_name": tên duy nhất trong bộ, "scan_index": int>=0}].

    Trả dict JSON-serializable: stage1 / stage2 / stage3_manifest / stage4_pages / stage4_dossiers /
    timings / reference / contract.
    """
    progress = progress or _noop_progress
    if not pages:
        raise ValueError("Bộ upload rỗng")
    idxs = [p["scan_index"] for p in pages]
    if len(set(idxs)) != len(idxs):
        raise ValueError(f"scan_index trùng lặp: {idxs}")
    names = [p["file_name"] for p in pages]
    if len(set(names)) != len(names):
        raise ValueError("file_name trùng lặp trong bộ upload")
    pages = sorted(pages, key=lambda p: p["scan_index"])
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    timings: Dict[str, float] = {}

    t = time.time()
    s1_recs = run_stage1(pages, group_id, work_dir, stage1_workers, progress)
    timings["T1"] = round(time.time() - t, 2)

    t = time.time()
    s2_records = run_stage2(pages, s1_recs, group_id, use_reference, progress)
    timings["T2"] = round(time.time() - t, 2)

    t = time.time()
    progress("T3", 0, 1, "Gom lô trong bộ upload")
    manifest = run_stage3(s2_records, use_reference)
    progress("T3", 1, 1, f"{manifest['metadata']['total_batches']} lô")
    timings["T3"] = round(time.time() - t, 2)

    t = time.time()
    s4_pages, s4_dossiers = run_stage4(s2_records, s1_recs, pages, manifest, progress)
    timings["T4"] = round(time.time() - t, 2)

    return {
        "contract": PIPELINE_CONTRACT_VERSION,
        "group_id": group_id,
        "reference": {
            "enabled": bool(use_reference),
            "stage2_reference_entries": len(_S2_REFERENCE_ORIGINAL) if use_reference else 0,
            "stage3_reference": manifest.get("metadata", {}).get("reference"),
            "status": "DEMO_DERIVED_FROM_GROUND_TRUTH" if use_reference else "DISABLED",
        },
        "stage3_scope": "UPLOAD_GROUP",
        "stage1_config": STAGE1_CFG_KW,
        "stage1": [s1_recs[p["file_name"]] for p in pages],
        "stage2": s2_records,
        "stage3_manifest": manifest,
        "stage4_pages": s4_pages,
        "stage4_dossiers": s4_dossiers,
        "timings": timings,
    }
