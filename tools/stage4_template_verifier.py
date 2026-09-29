# -*- coding: utf-8 -*-
"""Tầng 4 cho biểu mẫu HẠNG A — ô ký lấy từ template toạ độ cố định.

Vì sao có file này: `stage4_verifier_v2` + Tầng 3b dựng vùng ký ĐỘNG, chỉ dùng được cho
LOADING_PLAN (bảng hàng hoá co giãn, y trôi 0.54). Biểu mẫu hạng A có bố cục cứng nên
toạ độ ô ký nằm sẵn trong `config/form_signature_templates.json` — không cần dò nhãn.

File này KHÔNG viết lại phép đo: nó chỉ
  1. đọc `targets` của doc_type trong config,
  2. gọi `tools.sig_stroke_ownership.do_theo_quyen_so_huu` (engine đo theo quyền sở hữu nét),
  3. quy ra `doc_status` / `action` cùng BỘ MÃ với `stage4_verifier_v2` để web dùng lại
     nguyên bảng nhãn và nguyên component hiển thị.

Giới hạn đã biết — đọc trước khi tin số:
  * Engine chỉ đo MỰC XANH. Ảnh photo đen trắng sẽ ra "không ô nào có mực" ⇒ ở đây trả
    ABSTAIN (`CAN_KIEM_TRA_TAY`), KHÔNG kết luận "thiếu chữ ký". Sai điều kiện chỉ được
    dẫn tới ABSTAIN, không được dẫn tới phán quyết sai.
  * Toạ độ template LENH_DIEU_XE mới soát trên ĐÚNG 1 tờ (`L_nh_i_u_xe__0`, 11/11 ô).
    Chưa có bằng chứng về độ ổn định giữa nhiều tờ.

Chạy thử một ảnh:
    python tools/stage4_template_verifier.py LENH_DIEU_XE <duong_dan_anh>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config" / "form_signature_templates.json"
if str(ROOT) not in sys.path:          # chạy thẳng `python tools/...` vẫn import được `tools.*`
    sys.path.insert(0, str(ROOT))

# Mã zone_status riêng của nhánh template (web/backend/app/labels.py phải có nhãn tương ứng).
ZONE_TEMPLATE = "TEMPLATE_TOA_DO_CUNG"
ZONE_KHONG_CAN = "KHONG_CAN_VUNG_KY"

_CFG: Optional[Dict[str, Any]] = None


def load_form_templates(force: bool = False) -> Dict[str, Any]:
    """Nạp config template. Thiếu file ⇒ lỗi tường minh, KHÔNG có dự phòng hardcode."""
    global _CFG
    if _CFG is None or force:
        if not CFG_PATH.exists():
            raise FileNotFoundError(f"Thiếu {CFG_PATH} — Tầng 4 template không chạy được")
        _CFG = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    return _CFG


def template_doc_types(chi_chot: bool = True) -> tuple:
    """doc_type có template dùng được. `chi_chot=True` ⇒ chỉ lấy trạng thái DA_CHOT."""
    tpls = load_form_templates().get("templates", {})
    return tuple(k for k, v in tpls.items()
                 if (not chi_chot) or v.get("trang_thai") == "DA_CHOT")


def get_template(doc_type: str) -> Optional[Dict[str, Any]]:
    return load_form_templates().get("templates", {}).get(doc_type)


def _verdict(targets: List[Dict[str, Any]], is_color: bool) -> tuple:
    """Quy ô ký đã đo ra (doc_status, action, reason). Dùng đúng bộ mã của ver2."""
    bat_buoc = [t for t in targets if t.get("required", True)]
    da_ky = [t for t in bat_buoc if t.get("detected")]
    n_bb, n_ky = len(bat_buoc), len(da_ky)
    if n_bb == 0:
        return ("KHONG_YEU_CAU", "HOP_LE",
                "Template không khai báo ô ký bắt buộc nào")
    if n_ky == n_bb:
        status = "DAT_CHUAN_GOC" if is_color else "DAT_CHUAN_PHOTO"
        return (status, "DUYET", f"Đủ {n_ky}/{n_bb} ô ký bắt buộc")
    thieu = [t.get("role") for t in bat_buoc if not t.get("detected")]
    if n_ky == 0:
        return ("CHUA_KY_DONG_DAU", "YEU_CAU_KY_LAI",
                f"Không ô bắt buộc nào có chữ ký (0/{n_bb}). Thiếu: " + "; ".join(thieu))
    return ("THIEU_MOT_SO_CHU_KY", "YEU_CAU_KY_LAI",
            f"Mới ký {n_ky}/{n_bb} ô bắt buộc. Thiếu: " + "; ".join(thieu))


def verify_template_page(img_bgr, doc_type: str) -> Dict[str, Any]:
    """Kiểm chữ ký MỘT trang bằng template toạ độ cứng.

    Trả dict có cùng các khoá mà `web/backend/app/pipeline/runner.py` sinh ra cho
    LOADING_PLAN (zone_status / doc_status / action / reason / targets / a4_size...),
    để frontend dùng lại y nguyên.
    """
    from tools.sig_stroke_ownership import do_theo_quyen_so_huu
    from tools.stage4_verifier import detect_document_modality

    T = get_template(doc_type)
    if T is None:
        raise KeyError(f"Chưa có template cho doc_type={doc_type}")

    H, W = img_bgr.shape[:2]
    chung = {
        "zone_status": ZONE_TEMPLATE,
        "template_version": load_form_templates().get("version"),
        "template_engine": "sig_stroke_ownership",
        "template_trang_thai": T.get("trang_thai"),
        "template_canh_bao": T.get("canh_bao"),
        "yeu_cau_chu_ky": bool(T.get("yeu_cau_chu_ky", True)),
        "yeu_cau_moc": T.get("yeu_cau_moc"),
        "a4_size": [int(W), int(H)],
    }

    # --- Biểu mẫu khai báo tường minh là KHÔNG có ô ký (vd Biểu đồ nhiệt độ) ---
    # Không dựng bộ kiểm ⇒ không thể báo thiếu oan.
    if not T.get("yeu_cau_chu_ky", True):
        chung.update({
            "zone_status": ZONE_KHONG_CAN,
            "modality": "N/A",
            "doc_status": "KHONG_YEU_CAU",
            "action": "HOP_LE",
            "reason": T.get("ly_do_khong_kiem")
                      or "Biểu mẫu không có ô ký / chỗ đóng dấu — SOP không yêu cầu",
            "required_targets": 0,
            "detected_required_targets": 0,
            "targets": [],
        })
        return chung

    targets_cfg = T.get("targets") or []
    if not targets_cfg:
        chung.update({
            "modality": "N/A",
            "doc_status": "CHUA_CHUAN_HOA_VUNG_KY", "action": "ABSTAIN",
            "reason": f"Template {doc_type} khai báo yêu cầu chữ ký nhưng chưa có ô ký nào",
            "required_targets": 0, "detected_required_targets": 0, "targets": [],
        })
        return chung

    mod = detect_document_modality(img_bgr)
    modality = mod["modality"]
    chung["modality"] = modality
    chung["modality_do"] = {k: mod[k] for k in ("p99_sat", "color_pixels", "blue_count", "red_count")}

    # Engine chỉ đo mực xanh. Ảnh không phải bản màu ⇒ mọi ô sẽ ra 0 mm² và ta sẽ
    # kết luận "thiếu chữ ký" một cách sai. ABSTAIN là hành vi đúng.
    if modality != "TRUE_COLOR":
        chung.update({
            "doc_status": "CAN_KIEM_TRA_TAY", "action": "ABSTAIN",
            "reason": (f"Ảnh {modality}: engine quyền-sở-hữu-nét chỉ đo được mực XANH "
                       f"(blue_count={mod['blue_count']}) — không đủ căn cứ kết luận, chuyển kiểm tay"),
            "required_targets": len([t for t in targets_cfg if t.get("required", True)]),
            "detected_required_targets": 0,
            "targets": [{
                "role": t.get("role"), "required": t.get("required", True),
                "expected_color": t.get("expected_color"),
                "box_norm": [t["box_norm"][1], t["box_norm"][0], t["box_norm"][3], t["box_norm"][2]],
                "box_norm_config": t["box_norm"], "box_norm_order": "y0,x0,y1,x1",
                "detected": None, "confidence": 0.0,
                "evidence": "BW_UNVALIDATED_TEMPLATE",
                "reason": "Ảnh không phải bản màu — không đo được mực xanh",
                "review_required": True, "ghi_chu": t.get("ghi_chu"),
            } for t in targets_cfg],
        })
        return chung

    kq, meta = do_theo_quyen_so_huu(img_bgr, targets_cfg)

    out: List[Dict[str, Any]] = []
    for t_cfg, r in zip(targets_cfg, kq):
        x0, y0, x1, y1 = t_cfg["box_norm"]
        out.append({
            "role": r["role"],
            "required": r["required"],
            "expected_color": t_cfg.get("expected_color"),
            # ⚠️ ĐỔI THỨ TỰ CÓ CHỦ Ý. Trong config template, box_norm là (x0,y0,x1,y1)
            # — đó là thứ tự mà `sig_stroke_ownership` và `ve_o_bat_buoc` đọc, và là
            # thứ tự ĐÚNG: đo thử trên L_nh_i_u_xe__0 cho 11/14 ô có mực, còn hoán vị
            # chỉ 5/14 (scratch/_demo_3template/chay_thu/thu_doi_thu_tu.py).
            # Nhưng Tầng 3b của LOADING_PLAN xuất (y0,x0,y1,x1) (stage3b_zone_resolver.py:786)
            # và frontend đọc theo thứ tự đó (web/frontend/src/lib/targets.ts:42).
            # ⇒ quy về MỘT quy ước trên đường truyền: (y0,x0,y1,x1).
            "box_norm": [y0, x0, y1, x1],
            "box_norm_config": t_cfg["box_norm"],
            "box_norm_order": "y0,x0,y1,x1",
            # Cùng quy ước (y1, x1, y2, x2) mà artifact Tầng 4 đang dùng — xem
            # ghi chú ở tools/kido_pipeline.py:170.
            "bbox_px": [int(y0 * H), int(x0 * W), int(y1 * H), int(x1 * W)],
            "detected": r["detected"],
            "confidence": r["confidence"],
            "evidence": r["evidence"],
            "muc_so_huu_mm2": r["muc_so_huu_mm2"],
            "so_cum": r["so_cum"],
            "ink_type": "blue_ink" if r["detected"] else None,
            "reason": (f"Mực thuộc ô {r['muc_so_huu_mm2']} mm² "
                       f"({'≥' if r['detected'] else '<'} ngưỡng 2.0 mm²), {r['so_cum']} cụm nét"),
            "review_required": False,
            "ghi_chu": t_cfg.get("ghi_chu"),
        })

    doc_status, action, reason = _verdict(out, is_color=True)
    chung.update({
        "doc_status": doc_status, "action": action, "reason": reason,
        "required_targets": len([t for t in out if t["required"]]),
        "detected_required_targets": len([t for t in out if t["required"] and t["detected"]]),
        "targets": out,
        "do_luong": {"n_cum_toan_trang": meta["n_cum"], "px_per_mm": meta["px_per_mm"],
                     "n_cum_vo_chu": len(meta["cum_vo_chu"]), "cum_vo_chu": meta["cum_vo_chu"]},
    })
    return chung


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        print(f"Template đã chốt: {', '.join(template_doc_types())}")
        return 2
    doc_type, anh = sys.argv[1], Path(sys.argv[2])
    img = cv2.imread(str(anh))
    if img is None:
        print(f"Không đọc được ảnh: {anh}")
        return 2
    r = verify_template_page(img, doc_type)
    print(f"{anh.name} | {doc_type} | {r['zone_status']} | {r['modality']}")
    print(f"  => {r['doc_status']} / {r['action']}")
    print(f"     {r['reason']}")
    print(f"  ô bắt buộc đã ký: {r['detected_required_targets']}/{r['required_targets']}")
    for i, t in enumerate(r["targets"], 1):
        dau = "KY " if t["detected"] else ("?? " if t["detected"] is None else "-- ")
        bb = "[BB]" if t["required"] else "[--]"
        print(f"  {i:2d}. {dau}{bb} {str(t.get('muc_so_huu_mm2')):>8} mm²  {t['role']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# Hồ sơ (dossier) cho biểu mẫu hạng A
# ---------------------------------------------------------------------------
# Vì sao cần: `evaluate_lp_dossier_verdicts` lọc `doc_type == "LOADING_PLAN"`
# (tools/stage4_required_policy.py:262) nên trang hạng A bị BỎ QUA IM LẶNG — không sinh
# hồ sơ, không vào `orphan_pages`, không được tính là thiếu. Hệ quả: một bộ có Lệnh điều
# xe THIẾU chữ ký vẫn cho tóm tắt hồ sơ "sạch" ⇒ PASS lỏng. Ở đây sinh hồ sơ tường minh.
#
# Biểu mẫu hạng A là chứng từ MỘT TRANG (bố cục cứng, khối ký nằm trong cùng tờ) nên
# 1 trang = 1 hồ sơ, phán quyết hồ sơ CHÍNH LÀ phán quyết trang — không gộp gì thêm.
# KHÔNG dùng policy vai trò của LOADING_PLAN: vai trò hai bên khác hẳn nhau.

def build_template_dossiers(page_results) -> List[Dict[str, Any]]:
    """Sinh bản ghi hồ sơ cho các trang doc_type hạng A, cùng khuôn với `_one_dossier`."""
    out = []
    for r in page_results:
        dt = r.get("doc_type")
        if dt not in template_doc_types() or dt == "LOADING_PLAN":
            continue
        fn = r.get("file_name")
        targets = r.get("targets") or []
        out.append({
            "dossier_id": f"TPL:{fn}",
            "batch_id": r.get("batch_id"),
            "source": "TEMPLATE_ONE_PAGE",
            "stage3_is_multi_page": False,
            "pages": [fn],
            "page_classes": {fn: ("SIGNATURE_BLOCK" if targets else "PAGE_NO_SIGNATURE_BOX")},
            "page_verdicts": {fn: r.get("doc_status")},
            "systems": [str(r.get("system"))],
            # Biểu mẫu hạng A không phân kênh SOP — ô bắt buộc cố định trong template.
            "policy_channel": None,
            "policy_channel_unresolved": False,
            "policy_channel_reason": "TEMPLATE_FIXED_REQUIRED",
            "required_roles": [t.get("role") for t in targets if t.get("required")],
            "role_evidence": {
                (t.get("role") or f"O_{i}"): {
                    "role": t.get("role"), "required": bool(t.get("required")),
                    "required_source": "TEMPLATE", "detected": bool(t.get("detected")),
                    "review_required": bool(t.get("review_required")),
                    "evidence": t.get("evidence"),
                    "pages_detected": [fn] if t.get("detected") else [],
                    "pages_measured": [fn],
                } for i, t in enumerate(targets)
            },
            "contract_errors": [],
            "doc_status": r.get("doc_status"),
            "action": r.get("action"),
            "reason": r.get("reason"),
            "doc_type": dt,
        })
    return out


def merge_template_dossiers(lp_result: Dict[str, Any], page_results) -> Dict[str, Any]:
    """Gộp hồ sơ hạng A vào kết quả của `evaluate_lp_dossier_verdicts` (tính lại summary)."""
    extra = build_template_dossiers(page_results)
    if not extra:
        return lp_result
    out = dict(lp_result or {})
    ds = list(out.get("dossiers") or []) + extra
    summary: Dict[str, int] = {}
    for d in ds:
        summary[d["doc_status"]] = summary.get(d["doc_status"], 0) + 1
    out["dossiers"] = ds
    out["n_dossiers"] = len(ds)
    out["summary"] = summary
    return out
