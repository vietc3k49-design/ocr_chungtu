# -*- coding: utf-8 -*-
"""
Duong nap anh + zone LOADING_PLAN DUNG NHU PRODUCTION (runner ver2).

Vi sao co file nay: GT/bench cu (`build_lp_dynamic_crops.py`, `bench_lp_dynamic.py`,
`bench_lp_new_gt.py`) doc anh goc `output/form_samples` (~850px) KHONG resize, trong khi
production (`generate_nb4_ver2.py` Cell 1+3, va E2E) doc anh Tang 1
`output/stage1_out/images/form_samples/` roi resize H=2200. Hai he quy chieu khac nhau
=> so do cu khong noi gi ve production.

Code runner ver2 nam trong CHUOI cua generator (khong import duoc), nen cac buoc duoi day
la BAN CHEP 1-1 cua Cell 1 (`get_image_path`, nguon Tang 2) va Cell 3 (doc anh, resize,
page_role, goi resolver, modality, gan stamp_class). Vi la ban chep, moi lan dung phai goi
`assert_boxes_match_manifest()` doi chieu voi manifest chinh thuc
`output/stage4_out/stage4_verification_manifest_v2.json`: box phai trung 100%.

Chi doc, khong ghi gi ra dia.
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Cell 1 ver2 import tu kido_pipeline (re-export cua stage3b_zone_resolver) — giu dung duong do.
from tools.kido_pipeline import detect_loading_plan_signature_zone  # noqa: E402
from tools.stage4_verifier import detect_document_modality  # noqa: E402
from tools.stage4_required_policy import apply_lp_required_policy  # noqa: E402  (Cell 3, Giai doan 5)

# ---- Hang so chep tu generate_nb4_ver2.py Cell 1 (tuong doi ROOT thay vi cwd) ----
STAGE1_DIR = ROOT / "output/stage1_out/images/form_samples"
STAGE1_ALT = ROOT / "output/form_samples"
STAGE2_PATH = ROOT / "output/stage2_out/stage2_classified_results.json"
MANIFEST_V2_PATH = ROOT / "output/stage4_out/stage4_verification_manifest_v2.json"
RESOLVER_PATH = ROOT / "tools/stage3b_zone_resolver.py"
TARGET_H = 2200
IN_SCOPE_DOC_TYPES = ("LOADING_PLAN",)


def get_image_path(fn: str) -> Optional[str]:
    """Chep 1-1 Cell 1: uu tien anh Tang 1, fallback anh goc."""
    p1 = STAGE1_DIR / fn
    if p1.exists():
        return str(p1)
    p2 = STAGE1_ALT / fn
    if p2.exists():
        return str(p2)
    return None


def load_stage2_map() -> Dict[str, Dict[str, Any]]:
    data = json.loads(STAGE2_PATH.read_text(encoding="utf-8"))
    return {item["file_name"]: item for item in data}


def list_loading_plan_files(s2_map: Optional[Dict[str, Any]] = None) -> List[str]:
    s2_map = s2_map or load_stage2_map()
    return sorted(fn for fn, r in s2_map.items() if r.get("doc_type", "UNKNOWN") in IN_SCOPE_DOC_TYPES)


def load_production_page(fn: str, s2_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Nap 1 trang DUNG nhu Cell 3 ver2. Tra ve dict:
      file_name, image_path, image (a4 H=2200, None neu loi), page_role, system, zone,
      modality (None neu zone khong co target — Cell 3 khong goi modality khi do), is_color,
      read_error (None | IMAGE_NOT_FOUND | UNREADABLE).
    """
    s2_map = s2_map or load_stage2_map()
    s2 = s2_map[fn]
    page_role = s2.get("page_role", "HEADER")       # Cell 3: KHONG co `or "HEADER"`
    system = s2.get("system", "COMMON")
    img_path = get_image_path(fn)
    raw = cv2.imread(img_path) if img_path else None  # Cell 3 dung cv2.imread
    out = {"file_name": fn, "image_path": img_path, "page_role": page_role, "system": system,
           "doc_type": s2.get("doc_type", "UNKNOWN"), "image": None, "zone": None,
           "modality": None, "is_color": None, "read_error": None}
    if raw is None:
        out["read_error"] = "IMAGE_NOT_FOUND" if not img_path else "UNREADABLE"
        return out
    scale = float(TARGET_H) / raw.shape[0]
    a4 = cv2.resize(raw, (int(raw.shape[1] * scale), TARGET_H))   # Cell 3: interpolation mac dinh
    zone = detect_loading_plan_signature_zone(a4, page_role=page_role)
    out["image"] = a4
    out["zone"] = zone
    has_sig = bool(zone.get("has_signatures", False))
    if zone.get("status") != "PAGE_1_NO_SIGNATURES" and has_sig and (zone.get("targets") or []):
        # Giai doan 5: chep 1-1 Cell 3 — required theo KENH (config/stage4_lp_required_policy.json)
        # ap len targets truoc verify/verdict. Ban resolver goc giu o `targets_raw`.
        zone = dict(zone)
        zone["targets_raw"] = zone["targets"]
        zone["targets"] = apply_lp_required_policy(zone["targets"], system)
        out["zone"] = zone
        mod = detect_document_modality(a4)["modality"]
        out["modality"] = mod
        out["is_color"] = (mod == "TRUE_COLOR")
    return out


def page_kind(page: Dict[str, Any]) -> str:
    """TARGETS | PAGE_1_NO_SIGNATURES | ZONE_ABSTAIN | READ_ERROR (dung logic re nhanh Cell 3)."""
    if page["read_error"]:
        return "READ_ERROR"
    z = page["zone"]
    if z.get("status") == "PAGE_1_NO_SIGNATURES":
        return "PAGE_1_NO_SIGNATURES"
    if (not z.get("has_signatures", False)) or (not (z.get("targets") or [])):
        return "ZONE_ABSTAIN"
    return "TARGETS"


def prepare_v2_target(t: Dict[str, Any]) -> Dict[str, Any]:
    """Chep 1-1 Cell 3: gan stamp_class theo role/expected_color truoc khi goi ver2."""
    t_copy = dict(t)
    if "stamp_class" not in t_copy:
        if t_copy.get("expected_color") == "any_stamp" or "tiếp nhận" in t_copy.get("role", "").lower():
            t_copy["stamp_class"] = "SUPERMARKET_SQUARE"
        elif t_copy.get("expected_color") == "red_stamp" or "mộc đỏ" in t_copy.get("role", "").lower():
            t_copy["stamp_class"] = "COMPANY_ROUND_RED"
    return t_copy


def prepare_v1_target(t: Dict[str, Any]) -> Dict[str, Any]:
    """Schema target cho v1 — giong cach bench cu goi v1 (box_norm + bbox + description)."""
    return {"role": t["role"], "box_norm": t["box_norm"], "bbox": t["box_norm"],
            "expected_color": t["expected_color"], "required": t["required"],
            "description": t.get("description", t["role"])}


def target_id(fn: str, i: int) -> str:
    return f"{Path(fn).stem}__T{i:02d}"


def page_id(fn: str) -> str:
    return f"{Path(fn).stem}__PAGE"


def load_manifest_v2() -> Dict[str, Any]:
    if not MANIFEST_V2_PATH.exists():
        raise AssertionError(f"Khong tim thay manifest chinh thuc: {MANIFEST_V2_PATH}")
    return json.loads(MANIFEST_V2_PATH.read_text(encoding="utf-8"))


def assert_boxes_match_manifest(pages: List[Dict[str, Any]], manifest: Optional[Dict[str, Any]] = None,
                                tol: float = 1e-9) -> Dict[str, Any]:
    """
    Doi chieu tung trang LOADING_PLAN voi manifest v2 chinh thuc:
    zone_status, so target, role, required, box_norm (manifest round 4 chu so) phai TRUNG 100%.
    Tap file cung phai trung. Nem AssertionError liet ke moi sai lech.
    """
    manifest = manifest or load_manifest_v2()
    mdocs = {d["file_name"]: d for d in manifest["documents"] if d.get("doc_type") in IN_SCOPE_DOC_TYPES}
    errs = []
    ours = {p["file_name"]: p for p in pages}
    if set(ours) != set(mdocs):
        errs.append(f"tap file khac: thieu={sorted(set(mdocs) - set(ours))} thua={sorted(set(ours) - set(mdocs))}")
    n_box = 0
    for fn in sorted(set(ours) & set(mdocs)):
        p, d = ours[fn], mdocs[fn]
        if p["read_error"]:
            if d.get("doc_status") != "LOI_DOC_ANH":
                errs.append(f"{fn}: loi doc anh {p['read_error']} nhung manifest {d.get('doc_status')}")
            continue
        z = p["zone"]
        if z.get("status") != d.get("zone_status"):
            errs.append(f"{fn}: zone_status {z.get('status')} != manifest {d.get('zone_status')}")
        if page_kind(p) == "TARGETS":
            if p["modality"] != d.get("modality"):
                errs.append(f"{fn}: modality {p['modality']} != manifest {d.get('modality')}")
            ts, mts = z["targets"], d.get("targets", [])
        else:
            ts, mts = [], d.get("targets", [])
        if len(ts) != len(mts):
            errs.append(f"{fn}: {len(ts)} target != manifest {len(mts)}")
            continue
        for i, (t, mt) in enumerate(zip(ts, mts)):
            ob = [round(float(v), 4) for v in t["box_norm"]]
            mb = [float(v) for v in mt["box_norm"]]
            if any(abs(a - b) > tol for a, b in zip(ob, mb)):
                errs.append(f"{fn} T{i:02d}: box {ob} != manifest {mb}")
            if t["role"] != mt["role"] or bool(t["required"]) != bool(mt["required"]):
                errs.append(f"{fn} T{i:02d}: role/required khac manifest")
            n_box += 1
    if errs:
        raise AssertionError("BOX KHONG KHOP MANIFEST v2 (%d loi):\n  " % len(errs) + "\n  ".join(errs))
    return {"n_pages": len(ours), "n_boxes_matched": n_box,
            "manifest_resolver_mtime": (manifest.get("stage3b_resolver") or {}).get("mtime")}


def resolver_mtime() -> Optional[str]:
    import datetime as _dt
    if not RESOLVER_PATH.exists():
        return None
    return _dt.datetime.fromtimestamp(os.path.getmtime(RESOLVER_PATH)).isoformat(timespec="seconds")


def load_all_loading_plan_pages() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    s2_map = load_stage2_map()
    pages = [load_production_page(fn, s2_map) for fn in list_loading_plan_files(s2_map)]
    return pages, s2_map


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pages, _ = load_all_loading_plan_pages()
    info = assert_boxes_match_manifest(pages)
    print(f"OK: {info}  (resolver mtime hien tai {resolver_mtime()})")
