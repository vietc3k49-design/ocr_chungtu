"""Nhãn tiếng Việt + tone hiển thị cho mã trạng thái pipeline (backend quyết định, FE chỉ tô màu theo tone).

Nguyên tắc (SPEC §0):
  * Chỉ `DAT_CHUAN_*` được tone "success". Không mã nào khác — kể cả Tầng 1 `DAT` (chất lượng ảnh) —
    được tô như "đạt" để người dùng không nhầm với phán quyết chữ ký.
  * Mã KHÔNG có trong bảng ⇒ trả nguyên mã + "Cần kiểm tra", tone "neutral", `unknown=True`.
    Không bao giờ map bừa thành đạt.
  * Trang doc_type ngoài `SUPPORTED_DOC_TYPES` ⇒ "Chưa hỗ trợ kiểm chữ ký", tone neutral.

Nguồn mã: `tools/stage4_verifier_v2.py` (doc_status, SIG_EVIDENCE_*), `tools/stage4_required_policy.py`
(DOSSIER_*), `tools/stage3b_zone_resolver.py` (zone status), `app/pipeline/runner.py` (ABSTAIN tường minh),
`tools/stage1_normalizer.py` (status T1). Tên loại chứng từ lấy từ `tools.kido_pipeline.DOC_TYPE_VI_MAP`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.config import get_settings as _get_settings

_get_settings()  # ghim .env theo cwd ban đầu TRƯỚC khi runner os.chdir về gốc repo (env_file tương đối)
from app.pipeline import runner as _runner  # noqa: F401  — đặt sys.path/cwd về gốc repo trước khi import tools
from tools.kido_pipeline import DOC_TYPE_VI_MAP  # noqa: E402

TONE_SUCCESS, TONE_WARNING, TONE_DANGER, TONE_NEUTRAL, TONE_INFO = "success", "warning", "danger", "neutral", "info"
TONES = (TONE_SUCCESS, TONE_WARNING, TONE_DANGER, TONE_NEUTRAL, TONE_INFO)

# Loại chứng từ ĐÃ có bộ kiểm chữ ký. Phải khớp `runner.IN_SCOPE_DOC_TYPES` — lệch nhau thì
# trang được chạy Tầng 4 nhưng lại hiện "Chưa hỗ trợ", hoặc ngược lại.
SUPPORTED_DOC_TYPES = _runner.IN_SCOPE_DOC_TYPES
UNSUPPORTED_LABEL = "Chưa hỗ trợ kiểm chữ ký"
UNKNOWN_SUFFIX = "Cần kiểm tra"

# --- Phán quyết Tầng 4 ver2 (trang) + hồ sơ đa trang -------------------------------------------------
DOC_STATUS_LABELS: Dict[str, tuple] = {
    "DAT_CHUAN_GOC": ("Đạt — đủ chữ ký bắt buộc (bản màu)", TONE_SUCCESS),
    "DAT_CHUAN_PHOTO": ("Đạt — đủ chữ ký bắt buộc (bản photo)", TONE_SUCCESS),
    "THIEU_MOT_SO_CHU_KY": ("Thiếu một số chữ ký bắt buộc", TONE_DANGER),
    "CHUA_KY_DONG_DAU": ("Chưa có chữ ký / con dấu bắt buộc", TONE_DANGER),
    "TRANG_1_CHUA_KY": ("Trang không có khối ký (bảng hàng kéo dài) — xem phán quyết hồ sơ", TONE_INFO),
    "CHUA_CHUAN_HOA_VUNG_KY": ("Không xác định được vùng ký", TONE_WARNING),
    "CAN_KIEM_TRA_TAY": ("Cần kiểm tra tay", TONE_WARNING),
    "LOI_DOC_ANH": ("Lỗi đọc ảnh", TONE_DANGER),
    "KHONG_TIM_THAY_KHOI_KY": ("Không tìm thấy khối ký", TONE_WARNING),
    "KHONG_YEU_CAU": ("Không yêu cầu ký theo SOP", TONE_INFO),
    "UNMAPPED": ("Chưa có mẫu vùng ký", TONE_NEUTRAL),
}

ACTION_LABELS: Dict[str, tuple] = {
    "DUYET": ("Duyệt", TONE_INFO),  # action không tô success — chỉ doc_status DAT_CHUAN_* được success
    "CANH_BAO": ("Cảnh báo", TONE_DANGER),
    "YEU_CAU_KY_LAI": ("Yêu cầu ký lại", TONE_DANGER),
    "HOP_LE": ("Hợp lệ (không cần ký ở trang này)", TONE_INFO),
    "ABSTAIN": ("Không phán quyết", TONE_WARNING),
    "REVIEW_REQUIRED": ("Cần người kiểm tra", TONE_WARNING),
}

# --- Tầng 1 -----------------------------------------------------------------------------------------
S1_STATUS_LABELS: Dict[str, tuple] = {
    "DAT": ("Ảnh đạt chất lượng", TONE_INFO),
    "CANH_BAO": ("Ảnh có cảnh báo chất lượng", TONE_WARNING),
    "CHUP_LAI": ("Cần chụp lại ảnh", TONE_DANGER),
}
S1_ACTION_LABELS: Dict[str, tuple] = {
    "CHUYEN_TANG_2": ("Chuyển phân loại", TONE_INFO),
    "YEU_CAU_CHUP_LAI": ("Yêu cầu chụp lại", TONE_DANGER),
}

# --- Tầng 3b zone_status (LOADING_PLAN) + ABSTAIN tường minh của runner ----------------------------
ZONE_STATUS_LABELS: Dict[str, tuple] = {
    "TABLE_BOTTOM_DETECTED": ("Dò được khối ký dưới đáy bảng", TONE_INFO),
    "TOP_SIGNATURES_DETECTED": ("Dò được khối ký ở đầu trang", TONE_INFO),
    "PAGE_1_NO_SIGNATURES": ("Trang không có khối ký (bảng kéo sang trang sau)", TONE_INFO),
    "TABLE_ANCHOR_NOT_FOUND": ("Không tìm thấy mốc đáy bảng", TONE_WARNING),
    "COLUMN_DETECTION_FAILED": ("Không dò được cột chữ ký", TONE_WARNING),
    "COLUMN_ORDER_VIOLATION": ("Thứ tự cột chữ ký bất thường", TONE_WARNING),
    "COLUMN_PITCH_IMPLAUSIBLE": ("Khoảng cách cột chữ ký bất thường", TONE_WARNING),
    "COLUMN_OCR_UNAVAILABLE": ("Không chạy được OCR nhãn cột", TONE_WARNING),
    "COLUMN_LABELS_UNAVAILABLE": ("Thiếu cấu hình nhãn cột", TONE_WARNING),
    "CHUA_CHUAN_HOA_VUNG_KY": ("Chưa có vùng ký cho loại chứng từ này", TONE_NEUTRAL),
    # Nhánh biểu mẫu hạng A (tools/stage4_template_verifier.py)
    "TEMPLATE_TOA_DO_CUNG": ("Ô ký theo template toạ độ cố định", TONE_INFO),
    "KHONG_CAN_VUNG_KY": ("Biểu mẫu không có ô ký", TONE_INFO),
    "IMAGE_NOT_FOUND": ("Không tìm thấy ảnh", TONE_DANGER),
    "UNREADABLE": ("Không đọc được ảnh", TONE_DANGER),
}

# --- Evidence ô ký (tools/stage4_verifier_v2.py SIG_EVIDENCE_*, REVIEW_REQUIRED_EVIDENCE) -----------
EVIDENCE_LABELS: Dict[str, tuple] = {
    "BLUE_SIGNATURE_DETECTED": ("Thấy chữ ký mực xanh trong ô", TONE_INFO),
    "HANDWRITING_STROKE_DETECTED": ("Thấy nét viết tay (mực tối)", TONE_INFO),
    "NO_SIGNATURE_DETECTED": ("Không thấy chữ ký", TONE_NEUTRAL),
    "BLUE_INK_ONLY_AT_COLUMN_EDGE": ("Chỉ có mực xanh ở mép ô (mực tràn từ cột bên)", TONE_NEUTRAL),
    "BW_STROKE_DETECTED_UNVALIDATED": ("Ảnh đen trắng: thấy nét — engine chưa kiểm chứng", TONE_WARNING),
    "BW_NO_STROKE_UNVALIDATED": ("Ảnh đen trắng: không thấy nét — engine chưa kiểm chứng", TONE_WARNING),
    "STAMP_CLASS_UNRESOLVED": ("Không xác định được loại mộc", TONE_WARNING),
    # Luật ký online của Loading Plan (config/stage4_lp_required_policy.json mục ky_online,
    # đợt 29/09). Thiếu nhãn này từ khi thêm luật ⇒ web đang hiện mã thô "Cần kiểm tra".
    "E_SIGNATURE_PRINTED_NAME": ("Ký online — hệ thống in sẵn họ tên", TONE_INFO),
    # Engine quyền-sở-hữu-nét (tools/sig_stroke_ownership.py)
    "BLUE_SIGNATURE_OWNED": ("Thấy chữ ký mực xanh thuộc về ô này", TONE_INFO),
    "NO_OWNED_INK": ("Không có nét mực nào thuộc về ô này", TONE_NEUTRAL),
    "BW_UNVALIDATED_TEMPLATE": ("Ảnh không phải bản màu — engine chưa đo được", TONE_WARNING),
}

DOSSIER_PAGE_CLASS_LABELS: Dict[str, tuple] = {
    "SIGNATURE_BLOCK": ("Có khối ký", TONE_INFO),
    "PAGE_1_NO_BLOCK": ("Không có khối ký (trang đầu)", TONE_INFO),
    "BLOCK_ABSTAIN": ("Chưa đo được khối ký", TONE_WARNING),
    "MISSING": ("Thiếu kết quả trang", TONE_DANGER),
}

REVIEW_DECISION_LABELS: Dict[str, str] = {
    "SIGNED": "Có chữ ký",
    "NOT_SIGNED": "Không có chữ ký",
    "UNCLEAR": "Không rõ",
}


def _lookup(table: Dict[str, tuple], code: Optional[str], empty_label: str = "Chưa có kết quả") -> Dict[str, Any]:
    if code is None or code == "":
        return {"code": code, "label_vi": empty_label, "tone": TONE_NEUTRAL, "unknown": False}
    hit = table.get(code)
    if hit is None:
        return {"code": code, "label_vi": f"{code} · {UNKNOWN_SUFFIX}", "tone": TONE_NEUTRAL, "unknown": True}
    label, tone = hit
    return {"code": code, "label_vi": label, "tone": tone, "unknown": False}


def doc_status_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(DOC_STATUS_LABELS, code)


def action_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(ACTION_LABELS, code)


def s1_status_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(S1_STATUS_LABELS, code)


def s1_action_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(S1_ACTION_LABELS, code)


def zone_status_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(ZONE_STATUS_LABELS, code)


def evidence_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(EVIDENCE_LABELS, code, empty_label="—")


def page_class_label(code: Optional[str]) -> Dict[str, Any]:
    return _lookup(DOSSIER_PAGE_CLASS_LABELS, code)


def doc_type_vi(doc_type: Optional[str]) -> str:
    if not doc_type:
        return "Chưa phân loại"
    return DOC_TYPE_VI_MAP.get(doc_type, doc_type)


def is_supported(doc_type: Optional[str]) -> bool:
    return doc_type in SUPPORTED_DOC_TYPES


def page_status_label(doc_type: Optional[str], doc_status: Optional[str]) -> Dict[str, Any]:
    """Nhãn trạng thái chữ ký của MỘT trang. Trang ngoài phạm vi ⇒ "Chưa hỗ trợ kiểm chữ ký" (neutral)."""
    if doc_type is not None and not is_supported(doc_type):
        return {"code": doc_status, "label_vi": UNSUPPORTED_LABEL, "tone": TONE_NEUTRAL, "unknown": False}
    if doc_type is None and doc_status is None:
        return {"code": None, "label_vi": "Chưa xử lý", "tone": TONE_NEUTRAL, "unknown": False}
    return doc_status_label(doc_status)
