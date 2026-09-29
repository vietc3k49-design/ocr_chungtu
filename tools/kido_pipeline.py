"""
KIDO UNIFIED OCR & STAMP VERIFICATION PIPELINE (E2E)
====================================================
Hợp nhất 4 tầng xử lý chứng từ giao nhận KIDO thành một pipeline duy nhất:
1. Tầng 1: Chuẩn hóa ảnh, nắn A4, cân sáng, bảo toàn màu mộc đỏ & mực xanh, gác cổng chất lượng.
2. Tầng 2: Fast Header OCR, phân loại loại biểu mẫu (doc_type), kênh phân phối/hệ thống, bóc tách trường khóa.
3. Tầng 3: Tra cứu vị trí chữ ký & con dấu quy chuẩn từ danh mục 14 biểu mẫu KIDO.
4. Tầng 4: Kiểm định sự hiện diện của chữ ký và mộc đỏ/xanh/tím.
   - LOADING_PLAN (zone động Tầng 3b): Tầng 4 ver2 (`tools/stage4_verifier_v2.py`, ngưỡng mm)
     + `evaluate_document_verdict_v2` — cùng cách gọi với generate_nb4_ver2.py Cell 3.
   - doc_type preset tĩnh: Tầng 4 v1 (`tools/stage4_verifier.py`, Engine A HSV / Engine B hình thái).
   Kết quả mỗi trang ghi `engine` = "v2" | "v1" | None (không engine nào chạy).

Tác giả: Antigravity Multi-Agent Team (Planner, Coder, Tester, Reviewer)
Phiên bản: 1.0.0
"""

from __future__ import annotations
import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import pytesseract

# Nhập các module lõi từ 4 tầng đã được kiểm chứng
from tools.stage1_normalizer import Stage1Config, process_one, imread_unicode
from tools.stage2_classifier import Stage2Config, Stage2DocumentClassifier
from tools.stage3_resolver import SIGNATURE_PRESET_MAP
from tools.stage4_verifier import (
    detect_document_modality,
    verify_single_target,
    evaluate_document_verdict,
    extract_adaptive_roi,
    get_target_type
)
# Tầng 4 ver2 — engine xác nhận vùng ký ĐỘNG Tầng 3b (chỉ LOADING_PLAN). Chỉ import,
# không chép logic engine: cùng module mà generate_nb4_ver2.py Cell 3 dùng để sinh manifest ver2.
# v1 (import ở trên) giữ cho các doc_type dùng preset tĩnh — ver2 trên hộp tĩnh R 13.33%
# (AGENTS.md mục 8), còn v1 trên zone động LP production TN = 0 (GT v4: 44/0/25/0, 9.11.D).
from tools.stage4_verifier_v2 import (
    verify_single_target as verify_single_target_v2,
    evaluate_document_verdict_v2,
)

# Tên biểu mẫu tiếng Việt thân thiện với người dùng
DOC_TYPE_VI_MAP = {
    "HOA_DON": "Hóa đơn giá trị gia tăng / Bán lẻ",
    "BBBG_HANG_HOA": "Biên bản bàn giao hàng hóa",
    "BBBG_PALLET": "Biên bản giao nhận Pallet",
    "BB_THU_HOI": "Biên bản thu hồi chứng từ / hàng hóa",
    "BB_NO_HANG": "Biên bản nợ hàng",
    "BB_TRA_HANG": "Biên bản trả hàng",
    "PHIEU_GIAO_HANG": "Phiếu giao nhận hàng (PGH)",
    "PHIEU_XUAT_KHO": "Phiếu xuất kho (PXK)",
    "PXKKVCNB": "Phiếu xuất kho kiêm vận chuyển nội bộ",
    "DON_DAT_HANG": "Đơn đặt hàng (PO)",
    "LOADING_PLAN": "Bảng kê xếp hàng (Loading Plan)",
    "LENH_DIEU_XE": "Lệnh điều xe / Lệnh điều động",
    "BANG_KE": "Bảng kê chi tiết mặt hàng",
    "BIEU_DO_NHIET_DO": "Biểu đồ ghi nhiệt độ thùng lạnh (SOP)",
    "PHIEU_NHAP_KHO": "Phiếu nhập kho kiêm tiếp nhận (PNK)"
}


# ---------------------------------------------------------------------------
# TANG 3B - VUNG KY DONG
# Hai ham `detect_loading_plan_signature_zone` va `detect_invoice_signature_zone`
# truoc day dinh nghia ngay tai file nay (dong 63 va 177). Tu 27/09 chung da duoc
# tach sang module loi rieng `tools/stage3b_zone_resolver.py` (tra no kien truc
# AGENTS.md muc 6 va 11.2) - `kido_pipeline.py` tro ve dung vai orchestrator E2E.
# Cac ten duoi day duoc RE-EXPORT nguyen ven de moi noi dang
# `from tools.kido_pipeline import ...` khong phai sua gi.
# ---------------------------------------------------------------------------
from tools.stage3b_zone_resolver import (  # noqa: E402,F401
    detect_table_lines,
    detect_loading_plan_signature_zone,
    detect_invoice_signature_zone,
    detect_channel_aware_invoice_zone,
)
# Giai đoạn 5 (27/09): required LOADING_PLAN theo kênh — luật trong config/stage4_lp_required_policy.json
# (nguồn SOP sheet Guideline). Thiếu/hỏng config ⇒ Stage4PolicyError khi xử lý trang LP, không dự phòng.
from tools.stage4_required_policy import apply_lp_required_policy, policy_summary  # noqa: E402



# Action vận hành theo phán quyết Tầng 4 (tên căn theo manifest ver2).
# Trạng thái không có trong bảng -> REVIEW_REQUIRED, không đoán.
_VERDICT_ACTION = {
    "DAT_CHUAN_GOC": "DUYET",
    "DAT_CHUAN_PHOTO": "DUYET",
    "THIEU_MOT_SO_CHU_KY": "CANH_BAO",
    "CHUA_KY_DONG_DAU": "YEU_CAU_KY_LAI",
    "KHONG_YEU_CAU": "HOP_LE",
    "UNMAPPED": "ABSTAIN",
    "LOI_DU_LIEU_ANH": "ABSTAIN",
    # Trạng thái riêng của evaluate_document_verdict_v2 (Tầng 4 ver2, nhánh LOADING_PLAN):
    # - có target bắt buộc mang review_required (ảnh BW `BW_*_UNVALIDATED`, `STAMP_CLASS_UNRESOLVED`)
    "CAN_KIEM_TRA_TAY": "REVIEW_REQUIRED",
    # - zone có target nhưng 0 target bắt buộc (NO_REQUIRED_TARGETS) — không có căn cứ phán ký
    "CHUA_CHUAN_HOA_VUNG_KY": "ABSTAIN",
}


def _v2_stamp_class(target: Dict[str, Any]) -> Optional[str]:
    """Gán stamp_class ĐÚNG như generate_nb4_ver2.py Cell 3 (nguồn sinh manifest ver2).

    Cố ý bám nguyên văn luật của Cell 3 (kể cả suy từ `role.lower()` — nợ AGENTS.md
    mục 8 "Còn dở", chờ quyết định người): E2E phải cho cùng kết quả với manifest
    (test PARITY trong test_pipeline_e2e.py canh việc hai bản trôi lệch nhau).
    Không khớp luật nào ⇒ None (target đi nhánh chữ ký của engine, không đoán loại mộc).
    """
    if "stamp_class" in target:
        return target["stamp_class"]
    role_l = str(target.get("role", "")).lower()
    if target.get("expected_color") == "any_stamp" or "tiếp nhận" in role_l:
        return "SUPERMARKET_SQUARE"
    if target.get("expected_color") == "red_stamp" or "mộc đỏ" in role_l:
        return "COMPANY_ROUND_RED"
    return None


def verify_lp_targets_v2(
    a4_image: np.ndarray,
    targets: List[Dict[str, Any]],
    is_color: bool,
    modality: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Verify các ô ký zone động LOADING_PLAN bằng Tầng 4 ver2 + verdict ver2.

    Chuẩn bị target và gọi engine theo đúng Cell 3 của generate_nb4_ver2.py:
    `verify_single_target_v2(a4, t, is_color=...)` với `is_color = modality == TRUE_COLOR`
    (modality đo bằng `detect_document_modality` của v1, như Cell 3), rồi
    `evaluate_document_verdict_v2(verified, is_color=...)`; cờ `review_required` của engine
    được chuyển nguyên vào verdict.

    `targets` phải ĐÃ áp chính sách required theo kênh (apply_lp_required_policy).
    Trả (target_results, verdict) — verdict cùng khóa với nhánh v1, cộng `verdict_reason`
    và `v2_action` (action do chính ver2 trả, để đối chiếu với `_VERDICT_ACTION`).
    """
    target_results: List[Dict[str, Any]] = []
    for t in targets:
        t_copy = dict(t)
        sc = _v2_stamp_class(t_copy)
        if sc is not None:
            t_copy["stamp_class"] = sc
        res = verify_single_target_v2(a4_image, t_copy, is_color=is_color)
        is_stamp = (t_copy.get("expected_color") in ("red_stamp", "any_stamp")
                    or t_copy.get("stamp_class") is not None)
        target_results.append({
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
            # draw_visual_inspection đọc khóa `bbox` (y1, x1, y2, x2) — cùng định dạng bbox_px.
            "bbox": res.get("bbox_px"),
            "detected": bool(res.get("detected")),
            "confidence": round(float(res.get("confidence", 0.0)), 3),
            "ink_type": res.get("ink_type"),
            "reason": res.get("reason"),
            "evidence": res.get("evidence"),
            "review_required": bool(res.get("review_required", False)),
            "blue_own_mm2": res.get("blue_own_mm2"),
            "blue_edge_mm2": res.get("blue_edge_mm2"),
            "px_per_mm": res.get("px_per_mm"),
            "mask": res.get("mask"),
            "modality": modality,
            "verifier": "v2",
            "engine": "V2_STAMP_GEOMETRY" if is_stamp else "V2_SIGNATURE_MM",
        })

    doc_status, v2_action, reason = evaluate_document_verdict_v2(target_results, is_color=is_color)
    req = [r for r in target_results if r.get("required", True)]
    opt = [r for r in target_results if not r.get("required", True)]
    verdict = {
        "doc_status": doc_status,
        # ver2 không có mã semantic riêng: tiền tố V2_ + doc_status; lý do đầy đủ ở verdict_reason.
        "semantic_verdict": "V2_" + doc_status,
        "verdict_reason": reason,
        "v2_action": v2_action,
        "required_targets": len(req),
        "detected_required_targets": sum(1 for r in req if r.get("detected")),
        "optional_targets": len(opt),
        "detected_optional_targets": sum(1 for r in opt if r.get("detected")),
    }
    return target_results, verdict


class KidoPipelineConfig:
    """Cấu hình tích hợp cho toàn bộ Pipeline 4 Tầng."""
    def __init__(
        self,
        min_long_edge: int = 500,
        warn_long_edge: int = 800,
        dpi_reject: float = 40.0,
        dpi_warn: float = 70.0,
        blur_reject: float = 25.0,
        blur_warn: float = 70.0,
        confidence_threshold: float = 0.55
    ):
        self.stage1_cfg = Stage1Config(
            min_long_edge=min_long_edge,
            warn_long_edge=warn_long_edge,
            dpi_reject=dpi_reject,
            dpi_warn=dpi_warn,
            blur_reject=blur_reject,
            blur_warn=blur_warn,
            save_debug=False
        )
        self.stage2_cfg = Stage2Config()
        self.confidence_threshold = confidence_threshold


class KidoDocumentPipeline:
    """
    Bộ điều phối hợp nhất (Orchestrator) 4 tầng xử lý.
    Nhận 1 ảnh duy nhất và trả về đối tượng kết quả phân tích toàn diện.
    """
    def __init__(self, config: Optional[KidoPipelineConfig] = None):
        self.cfg = config or KidoPipelineConfig()
        self.classifier = Stage2DocumentClassifier(self.cfg.stage2_cfg)
        self.signature_catalog = SIGNATURE_PRESET_MAP

    def process_document(
        self,
        image_input: Union[str, Path, np.ndarray],
        file_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Thực hiện toàn bộ quy trình 4 tầng trên 1 ảnh:
        1. Chuẩn hóa & Gác cổng (Stage 1)
        2. Phân loại biểu mẫu & Bóc trường số (Stage 2)
        3. Ánh xạ vùng chữ ký & mộc đỏ chuẩn (Stage 3)
        4. Soi chiếu & Phán quyết chữ ký / con dấu (Stage 4)
        """
        t_start = time.time()
        
        # Xác định tên file định danh
        if file_name is None:
            if isinstance(image_input, (str, Path)):
                file_name = Path(image_input).name
            else:
                file_name = f"doc_input_{int(time.time()*1000)}.png"

        # --- TẦNG 1: CHUẨN HÓA ẢNH & GÁC CỔNG CHẤT LƯỢNG ---
        temp_file_created = False
        temp_path = None
        
        if isinstance(image_input, (str, Path)):
            input_path = str(image_input)
        elif isinstance(image_input, np.ndarray):
            # Lưu tạm buffer vào scratch nếu đầu vào là numpy array để tái sử dụng module Stage 1
            scratch_dir = Path("scratch")
            scratch_dir.mkdir(exist_ok=True)
            temp_path = str(scratch_dir / f"temp_{int(time.time()*1000)}.png")
            cv2.imwrite(temp_path, image_input)
            input_path = temp_path
            temp_file_created = True
        else:
            raise ValueError(f"Định dạng đầu vào không hợp lệ: {type(image_input)}")

        try:
            meta_s1, a4_image = process_one(input_path, self.cfg.stage1_cfg, save=False)
        finally:
            if temp_file_created and temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

        # Gác cổng Tầng 1: Nếu ảnh trắng/hỏng hoặc từ chối chụp lại -> Dừng sớm an toàn (Fail-Safe ABSTAIN)
        if meta_s1.get("status") == "CHUP_LAI" or a4_image is None:
            elapsed = time.time() - t_start
            return {
                "file_name": file_name,
                "elapsed_sec": round(elapsed, 3),
                "status": "YEU_CAU_CHUP_LAI",
                "engine": None,
                "stage1": {
                    "status": "CHUP_LAI",
                    "action": "YEU_CAU_CHUP_LAI",
                    "rejects": meta_s1.get("rejects", []),
                    "warns": meta_s1.get("warns", []),
                    "quality": meta_s1.get("quality_input")
                },
                "stage2": {
                    "doc_type": "UNKNOWN",
                    "doc_type_vi": "Không xác định",
                    "system": "UNKNOWN",
                    "confidence": 0.0,
                    "key_fields": {}
                },
                "stage3": {
                    "mapping_status": "UNMAPPED",
                    "total_targets": 0,
                    "required_targets": 0,
                    "targets": []
                },
                "stage4": {
                    "overall_verdict": "YEU_CAU_CHUP_LAI",
                    "semantic_verdict": "INPUT_ERROR",
                    "engine": None,
                    "action": "YEU_CAU_CHUP_LAI",
                    "abstain_reason": "Tầng 1 từ chối ảnh",
                    "verdict_title": "YÊU CẦU CHỤP LẠI",
                    "verdict_message": "Ảnh không đạt tiêu chuẩn kỹ thuật (quá mờ, mất góc hoặc kích thước quá nhỏ). Vui lòng chụp lại trọn vẹn 4 góc.",
                    "target_results": []
                },
                "images": {
                    "original": None,
                    "normalized_a4": None
                }
            }

        # --- TẦNG 2: PHÂN LOẠI CHỨNG TỪ & BÓC TÁCH TRƯỜNG KHÓA ---
        res_s2 = self.classifier.classify_document(
            a4_image,
            meta_stage1=meta_s1,
            file_name=file_name
        )
        doc_type = res_s2.get("doc_type", "UNKNOWN")
        doc_type_vi = DOC_TYPE_VI_MAP.get(doc_type, doc_type)
        system = res_s2.get("system", "COMMON")
        key_fields = res_s2.get("key_fields", {})

        # --- TẦNG 3: ÁNH XẠ VỊ TRÍ CHỮ KÝ & CON DẤU QUY CHUẨN ---
        # zone_gate != None nghĩa là Tầng 3b/nghiệp vụ đã ra phán quyết KHÔNG CHO
        # Tầng 4 chạy: khi đó bỏ qua evaluate_document_verdict (hàm đó coi
        # "0 target bắt buộc + MAPPED" là KHONG_YEU_CAU - chính là PASS giả cũ).
        zone_gate: Optional[Dict[str, Any]] = None
        zone_status: Optional[str] = None
        required_policy: Optional[Dict[str, Any]] = None
        page_role = res_s2.get("page_role", "HEADER")
        if doc_type == "BIEU_DO_NHIET_DO":
            targets = []
            mapping_status = "MAPPED"
        elif doc_type == "LOADING_PLAN":
            # Dynamic Table Bottom Detection & Dossier Lifecycle hiệu chuẩn cho Template 01.
            # [SỬA 27/09] Tiêu thụ ĐÚNG hợp đồng của resolver: status + has_signatures.
            # Trước đây gán cứng MAPPED và bỏ qua status -> resolver ABSTAIN (COLUMN_*,
            # targets=[]) bị Tầng 4 chấm KHONG_YEU_CAU ("không cần ký") = PASS giả.
            zone_info = detect_loading_plan_signature_zone(a4_image, page_role=page_role)
            # Kênh từ `system` Tầng 2 (UNRESOLVED ⇒ nghiêm nhất + cờ) — ghi cả khi zone ABSTAIN.
            required_policy = policy_summary(system)
            zone_status = zone_info.get("status")
            targets = list(zone_info.get("targets") or [])
            has_sig = bool(zone_info.get("has_signatures"))
            if zone_status == "PAGE_1_NO_SIGNATURES" and not targets:
                # Trang 1 hồ sơ đa trang: khối ký nằm ở trang sau. HỢP LỆ chờ trang sau,
                # KHÔNG phải "không yêu cầu ký" (căn theo ver2: TRANG_1_CHUA_KY / HOP_LE).
                mapping_status = "MAPPED"
                zone_gate = {
                    "doc_status": "TRANG_1_CHUA_KY",
                    "semantic_verdict": "PAGE_1_SIGNATURES_ON_NEXT_PAGE",
                    "action": "HOP_LE",
                    "reason": zone_info.get("description")
                              or "Trang 1 hồ sơ đa trang, khối ký nằm ở trang sau",
                }
                targets = []
            elif (not has_sig) or (not targets):
                # Mọi trường hợp resolver không dựng được vùng ký (COLUMN_* hoặc status lạ):
                # ABSTAIN tường minh, không chạy detector, không dùng hộp mặc định.
                mapping_status = "ZONE_ABSTAIN"
                zone_gate = {
                    "doc_status": "CHUA_CHUAN_HOA_VUNG_KY",
                    "semantic_verdict": "ZONE_RESOLVER_ABSTAIN",
                    "action": "ABSTAIN",
                    "reason": "Tầng 3b không dựng được vùng ký (zone_status={}): {}".format(
                        zone_status, zone_info.get("description", "")),
                }
                targets = []
            else:
                mapping_status = "MAPPED"
                # required theo KÊNH (SOP) thay cho cờ required tĩnh của config nhãn 3b; áp TRƯỚC verify/verdict.
                targets = apply_lp_required_policy(targets, system)
        elif doc_type == "HOA_DON":
            # [SỬA 27/09] KHÔNG gọi detect_invoice_signature_zone nữa: vùng ký hóa đơn
            # dùng tọa độ cứng chưa nghiệm thu (không có GT động), và nghiệp vụ đã HOÃN
            # vì mỗi chi nhánh/kênh cần template riêng. Cũng KHÔNG fallback về preset tĩnh
            # SIGNATURE_PRESET_MAP['HOA_DON'] (đó cũng là một bộ tọa độ chung cho mọi kênh).
            # -> UNMAPPED tường minh. Hàm vẫn được re-export ở đầu file cho các import khác.
            targets = []
            mapping_status = "UNMAPPED"
            zone_status = "HOA_DON_ZONE_DEFERRED"
            zone_gate = {
                "doc_status": "UNMAPPED",
                "semantic_verdict": "UNMAPPED_TARGETS",
                "action": "ABSTAIN",
                "reason": "HOA_DON zone hoãn — cần template theo chi nhánh/kênh (system={})".format(system),
            }
        elif doc_type in self.signature_catalog:
            targets = self.signature_catalog[doc_type]
            mapping_status = "MAPPED"
        else:
            targets = []
            mapping_status = "UNMAPPED"

        # --- TẦNG 4: KIỂM TRA CHỮ KÝ & CON DẤU MỘC ĐỎ/XANH/TÍM ---
        mod_info = detect_document_modality(a4_image)
        is_color = (mod_info["modality"] == "TRUE_COLOR")

        # Engine Tầng 4 theo doc_type (ghi vào kết quả mỗi trang):
        #   LOADING_PLAN            -> "v2" (zone động Tầng 3b; trang zone_gate thì không ô nào được verify)
        #   doc_type có preset tĩnh -> "v1"
        #   còn lại (UNMAPPED, HOA_DON hoãn) -> None: không engine nào chạy.
        if doc_type == "LOADING_PLAN":
            engine = "v2"
        elif zone_gate is None and mapping_status == "MAPPED":
            engine = "v1"
        else:
            engine = None

        target_results = []
        v2_verdict: Optional[Dict[str, Any]] = None
        if engine == "v2":
            if zone_gate is None:
                target_results, v2_verdict = verify_lp_targets_v2(
                    a4_image, targets, is_color=is_color, modality=mod_info["modality"])
        else:
            for target in targets:
                t_res = verify_single_target(a4_image, target, is_color=is_color)
                # Bảo đảm modality được lưu trữ phục vụ phán quyết cấp tài liệu
                t_res["modality"] = mod_info["modality"]
                t_res["verifier"] = "v1"
                target_results.append(t_res)

        if zone_gate is not None:
            # Không có target nào được verify (targets=[] ở trên) -> đếm 0 là số THẬT.
            verdict = {
                "doc_status": zone_gate["doc_status"],
                "semantic_verdict": zone_gate["semantic_verdict"],
                "required_targets": 0,
                "detected_required_targets": 0,
                "optional_targets": 0,
                "detected_optional_targets": 0,
            }
        elif v2_verdict is not None:
            verdict = v2_verdict
        else:
            verdict = evaluate_document_verdict(
                target_results,
                mapping_status=mapping_status,
                doc_type=doc_type
            )
        overall_verdict = verdict["doc_status"]
        semantic_verdict = verdict["semantic_verdict"]
        det_req = verdict["detected_required_targets"]
        tot_req = verdict["required_targets"]
        if zone_gate is not None:
            action = zone_gate["action"]
            abstain_reason = zone_gate["reason"]
        else:
            action = _VERDICT_ACTION.get(overall_verdict)
            if action is None:
                # Không đoán action cho trạng thái lạ.
                action = "REVIEW_REQUIRED"
            abstain_reason = None
            if v2_verdict is not None:
                if v2_verdict["v2_action"] != action:
                    # Bảng action E2E và ver2 lệch nhau = lỗi contract: không chọn bên nào,
                    # chuyển người kiểm tra và ghi rõ cả hai.
                    abstain_reason = "ACTION_CONTRACT_MISMATCH: _VERDICT_ACTION[{}]={} != ver2 {}".format(
                        overall_verdict, action, v2_verdict["v2_action"])
                    action = "REVIEW_REQUIRED"
                elif action in ("ABSTAIN", "REVIEW_REQUIRED"):
                    abstain_reason = v2_verdict["verdict_reason"]

        # Xây dựng thông điệp phán quyết trực quan thân thiện cho vận hành
        if overall_verdict == "DAT_CHUAN_GOC":
            verdict_title = "ĐẠT CHUẨN (BẢN GỐC CÓ MÀU)"
            verdict_message = f"Chứng từ có đầy đủ {det_req}/{tot_req} vị trí chữ ký & con dấu mộc đỏ/xanh chuẩn màu thực tế."
        elif overall_verdict == "DAT_CHUAN_PHOTO":
            verdict_title = "ĐẠT CHUẨN (BẢN PHOTO ĐEN TRẮNG)"
            verdict_message = f"Chứng từ photo đã ký & đóng dấu đầy đủ {det_req}/{tot_req} vị trí (xác thực qua viền dấu & nét bút)."
        elif overall_verdict == "THIEU_MOT_SO_CHU_KY":
            verdict_title = "CẢNH BÁO: THIẾU CHỮ KÝ / DẤU MỘC"
            missing_roles = [r["role"] for r in target_results if r.get("required") and not r.get("detected")]
            verdict_message = f"Mới phát hiện {det_req}/{tot_req} vị trí bắt buộc. Còn thiếu: {', '.join(missing_roles)}."
        elif overall_verdict == "CHUA_KY_DONG_DAU":
            verdict_title = "CHƯA KÝ ĐÓNG DẤU"
            verdict_message = f"Biểu mẫu còn nguyên trạng từ hệ thống ERP, chưa có bất kỳ chữ ký hoặc con dấu nào (0/{tot_req})."
        elif overall_verdict == "KHONG_YEU_CAU":
            verdict_title = "KHÔNG YÊU CẦU KÝ ĐÓNG DẤU"
            verdict_message = "Biểu mẫu này theo quy chuẩn SOP KIDO không bắt buộc phải có chữ ký hay con dấu."
        elif overall_verdict == "TRANG_1_CHUA_KY":
            verdict_title = "TRANG 1 — KHỐI KÝ Ở TRANG SAU (HỢP LỆ)"
            verdict_message = "Trang 1 của hồ sơ nhiều trang: bảng hàng hóa phủ kín trang, chữ ký được kiểm ở trang tiếp theo."
        elif overall_verdict == "CHUA_CHUAN_HOA_VUNG_KY":
            verdict_title = "CHƯA XÁC ĐỊNH ĐƯỢC VÙNG KÝ (ABSTAIN)"
            verdict_message = f"Hệ thống không tự kết luận — cần người kiểm tra. {abstain_reason}"
        elif overall_verdict == "CAN_KIEM_TRA_TAY":
            verdict_title = "CẦN KIỂM TRA TAY (REVIEW_REQUIRED)"
            verdict_message = f"Engine chưa được kiểm chứng cho ít nhất 1 vị trí bắt buộc — không phán ký/chưa ký. {abstain_reason}"
        elif overall_verdict == "UNMAPPED" and zone_gate is not None:
            verdict_title = "CHƯA CÓ CẤU HÌNH VỊ TRÍ (UNMAPPED)"
            verdict_message = f"Không kết luận chữ ký/mộc: {abstain_reason}"
        else:
            verdict_title = "CHƯA CÓ CẤU HÌNH VỊ TRÍ (UNMAPPED)"
            verdict_message = f"Biểu mẫu '{doc_type}' chưa được cấu hình danh mục vị trí ký mộc chuẩn."

        elapsed = time.time() - t_start

        return {
            "file_name": file_name,
            "elapsed_sec": round(elapsed, 3),
            "status": "THANH_CONG",
            "engine": engine,
            "stage1": {
                "status": meta_s1.get("status", "DAT"),
                "source_type": meta_s1.get("source_type", "photo"),
                "rotation_deg": meta_s1.get("orientation", {}).get("deg", 0),
                "dpi_est": meta_s1.get("quality_input", {}).get("dpi", 150),
                "resolution": (a4_image.shape[1], a4_image.shape[0])
            },
            "stage2": {
                "doc_type": doc_type,
                "doc_type_vi": doc_type_vi,
                "system": system,
                "confidence": res_s2.get("confidence", 1.0),
                "page_role": res_s2.get("page_role", "HEADER"),
                "key_fields": key_fields
            },
            "stage3": {
                "mapping_status": mapping_status,
                "zone_status": zone_status,
                "required_policy": required_policy,
                "total_targets": len(targets),
                "required_targets": tot_req,
                "targets": targets
            },
            "stage4": {
                "overall_verdict": overall_verdict,
                "semantic_verdict": semantic_verdict,
                "engine": engine,
                "verdict_reason": verdict.get("verdict_reason"),
                "action": action,
                "abstain_reason": abstain_reason,
                "verdict_title": verdict_title,
                "verdict_message": verdict_message,
                "document_modality": mod_info["modality"],
                "detected_required_targets": det_req,
                "total_required_targets": tot_req,
                "detected_optional_targets": verdict["detected_optional_targets"],
                "total_optional_targets": verdict["optional_targets"],
                "target_results": target_results
            },
            "images": {
                "normalized_a4": a4_image
            }
        }


def draw_visual_inspection(
    result: Dict[str, Any],
    max_display_height: int = 1200
) -> Tuple[np.ndarray, List[Tuple[str, np.ndarray, Dict[str, Any]]]]:
    """
    Vẽ trực quan Bounding Box màu sắc lên ảnh chuẩn A4 và trích xuất danh sách Crop từng ô ký/mộc:
    - Màu xanh lá (#10B981): Vị trí ĐÃ KÝ / ĐÃ ĐÓNG DẤU
    - Màu đỏ (#EF4444): Vị trí BẮT BUỘC nhưng THIẾU
    - Màu vàng cam (#F59E0B): Vị trí TÙY CHỌN (Optional)
    """
    a4_img = result.get("images", {}).get("normalized_a4")
    if a4_img is None:
        return np.zeros((300, 500, 3), dtype=np.uint8), []

    annotated = a4_img.copy()
    h, w = annotated.shape[:2]
    crops_list = []

    for t_res in result.get("stage4", {}).get("target_results", []):
        detected = t_res.get("detected", False)
        required = t_res.get("required", True)
        role = t_res.get("role", "Chữ ký / Con dấu")
        expected_color = t_res.get("expected_color", "blue_ink")
        
        # Xác định màu sắc bounding box
        if detected:
            box_color = (0, 200, 0)      # Xanh lá (BGR)
            status_text = "✓ ĐÃ CÓ"
        elif required:
            box_color = (0, 0, 230)      # Đỏ (BGR)
            status_text = "✗ THIẾU"
        else:
            box_color = (0, 180, 230)    # Vàng cam (BGR)
            status_text = "○ TÙY CHỌN"

        bbox = t_res.get("bbox")
        if bbox and len(bbox) == 4 and bbox != (0, 0, 0, 0):
            y1, x1, y2, x2 = bbox
            thickness = 4 if required else 2
            
            # Vẽ hình chữ nhật
            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, thickness)
            
            # Vẽ nhãn mô tả
            label = f"{role}: {status_text}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.8
            (lw, lh), baseline = cv2.getTextSize(label, font, scale, 2)
            lbl_y = max(y1 - 10, lh + 10)
            cv2.rectangle(annotated, (x1, lbl_y - lh - 6), (x1 + lw + 10, lbl_y + 4), box_color, -1)
            cv2.putText(annotated, label, (x1 + 5, lbl_y - 2), font, scale, (255, 255, 255), 2, cv2.LINE_AA)

            # Cắt crop zoom cận cảnh
            pad_y, pad_x = int((y2 - y1) * 0.1), int((x2 - x1) * 0.1)
            cy1, cy2 = max(0, y1 - pad_y), min(h, y2 + pad_y)
            cx1, cx2 = max(0, x1 - pad_x), min(w, x2 + pad_x)
            crop = a4_img[cy1:cy2, cx1:cx2].copy()
            crops_list.append((role, crop, t_res))

    # Giới hạn kích thước hiển thị nếu cần
    if annotated.shape[0] > max_display_height:
        scale_ratio = max_display_height / float(annotated.shape[0])
        new_w = int(annotated.shape[1] * scale_ratio)
        annotated = cv2.resize(annotated, (new_w, max_display_height), interpolation=cv2.INTER_AREA)

    return annotated, crops_list
