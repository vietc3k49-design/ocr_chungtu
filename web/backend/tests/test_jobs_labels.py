"""Lớp (a) — app/labels.py: mã lạ KHÔNG thành success; chỉ DAT_CHUAN_* là success; trang ngoài LP ⇒ chưa hỗ trợ."""
from app import labels
from tools.kido_pipeline import DOC_TYPE_VI_MAP


def _all_tables():
    return {
        "doc_status": labels.DOC_STATUS_LABELS, "action": labels.ACTION_LABELS, "s1": labels.S1_STATUS_LABELS,
        "s1_action": labels.S1_ACTION_LABELS, "zone": labels.ZONE_STATUS_LABELS,
        "evidence": labels.EVIDENCE_LABELS, "page_class": labels.DOSSIER_PAGE_CLASS_LABELS,
    }


def test_only_dat_chuan_is_success():
    for name, table in _all_tables().items():
        for code, (lbl, tone) in table.items():
            assert tone in labels.TONES, (name, code, tone)
            if tone == labels.TONE_SUCCESS:
                assert name == "doc_status" and code.startswith("DAT_CHUAN_"), (name, code)
    assert labels.doc_status_label("DAT_CHUAN_GOC")["tone"] == "success"
    assert labels.doc_status_label("DAT_CHUAN_PHOTO")["tone"] == "success"


def test_required_codes_present():
    for code in ("DAT_CHUAN_GOC", "DAT_CHUAN_PHOTO", "THIEU_MOT_SO_CHU_KY", "CHUA_KY_DONG_DAU", "TRANG_1_CHUA_KY",
                 "CHUA_CHUAN_HOA_VUNG_KY", "CAN_KIEM_TRA_TAY", "LOI_DOC_ANH", "KHONG_TIM_THAY_KHOI_KY",
                 "KHONG_YEU_CAU", "UNMAPPED"):
        assert labels.doc_status_label(code)["unknown"] is False, code
    for code in ("DAT", "CANH_BAO", "CHUP_LAI"):
        assert labels.s1_status_label(code)["unknown"] is False
    from tools import stage4_verifier_v2 as v2
    for name in dir(v2):
        if name.startswith("SIG_EVIDENCE_"):
            assert labels.evidence_label(getattr(v2, name))["unknown"] is False, name
    for code in ("TABLE_BOTTOM_DETECTED", "TOP_SIGNATURES_DETECTED", "PAGE_1_NO_SIGNATURES", "TABLE_ANCHOR_NOT_FOUND",
                 "COLUMN_DETECTION_FAILED", "COLUMN_ORDER_VIOLATION", "COLUMN_PITCH_IMPLAUSIBLE",
                 "COLUMN_OCR_UNAVAILABLE", "COLUMN_LABELS_UNAVAILABLE"):
        assert labels.zone_status_label(code)["unknown"] is False, code


def test_unknown_code_is_neutral_and_flagged():
    for fn in (labels.doc_status_label, labels.action_label, labels.s1_status_label, labels.zone_status_label,
               labels.evidence_label):
        r = fn("DAT_CHUAN_MOI_LA_CHUA_CO")  # giống DAT_ nhưng không có trong bảng ⇒ không được đạt
        assert r["tone"] == "neutral" and r["unknown"] is True
        assert "DAT_CHUAN_MOI_LA_CHUA_CO" in r["label_vi"] and "Cần kiểm tra" in r["label_vi"]
    r = labels.page_status_label("LOADING_PLAN", "XYZ")
    assert r["unknown"] and r["tone"] == "neutral"


def test_non_lp_page_not_supported_even_if_status_is_dat():
    for dt in ("HOA_DON", "PHIEU_GIAO_HANG", "UNKNOWN", "SOMETHING_NEW"):
        r = labels.page_status_label(dt, "DAT_CHUAN_GOC")
        assert r["label_vi"] == "Chưa hỗ trợ kiểm chữ ký" and r["tone"] == "neutral"
    assert labels.is_supported("LOADING_PLAN") and not labels.is_supported("HOA_DON")
    assert labels.page_status_label("LOADING_PLAN", "CHUA_CHUAN_HOA_VUNG_KY")["label_vi"] == "Không xác định được vùng ký"
    assert labels.page_status_label(None, None)["tone"] == "neutral"


def test_doc_type_vi_uses_pipeline_map():
    for k, v in DOC_TYPE_VI_MAP.items():
        assert labels.doc_type_vi(k) == v
    assert labels.doc_type_vi("LOAI_MOI") == "LOAI_MOI"
    assert labels.DOC_TYPE_VI_MAP is DOC_TYPE_VI_MAP  # import, không chép
