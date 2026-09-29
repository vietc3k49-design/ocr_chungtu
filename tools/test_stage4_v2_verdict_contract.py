"""
Test hợp đồng phán quyết Tầng 4 ver2 (Giai đoạn 1a, 27/09).

Kiểm:
  1. evaluate_document_verdict_v2: 0 target required (rỗng / toàn optional) ⇒ ABSTAIN,
     không bao giờ CHUA_KY_DONG_DAU. Giữ hành vi các ca có required.
  2. Logic dispatch zone -> phán quyết của runner Cell 3 (trích NGUYÊN VĂN từ
     generate_nb4_ver2.py, không chép lại) trên zone_info giả lập cho từng status
     ABSTAIN của Tầng 3b, status lạ chưa từng thấy, PAGE_1_NO_SIGNATURES, targets rỗng.

Không cần ảnh thật: verify_single_target / detect_document_modality được thay bằng stub
trả kết quả định sẵn, để test chỉ đo HỢP ĐỒNG, không đo detector.

Chạy: .venv/Scripts/python.exe tools/test_stage4_v2_verdict_contract.py
"""
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from tools.stage4_verifier_v2 import evaluate_document_verdict_v2  # noqa: E402
from tools.stage4_required_policy import (  # noqa: E402
    Stage4PolicyError, load_lp_required_policy, resolve_lp_channel, apply_lp_required_policy,
    evaluate_lp_dossier_verdicts,
)

ABSTAIN_ZONE_STATUSES = [
    "COLUMN_DETECTION_FAILED",
    "COLUMN_ORDER_VIOLATION",
    "COLUMN_PITCH_IMPLAUSIBLE",
    "COLUMN_OCR_UNAVAILABLE",
    "COLUMN_LABELS_UNAVAILABLE",
    "DEFAULT_SINGLE_PAGE",            # nếu agent khác chuyển sang ABSTAIN
    "SOME_FUTURE_STATUS_NEVER_SEEN",  # status lạ — phải tự đi đường ABSTAIN
]

results = []


def case(name, fn):
    try:
        fn()
        results.append((name, True, ""))
    except AssertionError as e:
        results.append((name, False, f"AssertionError: {e}"))
    except Exception as e:  # lỗi runtime cũng là FAIL, không nuốt
        results.append((name, False, f"{type(e).__name__}: {e}"))


def T(role, required=True, detected=False, review=False):
    t = {"role": role, "required": required, "detected": detected}
    if review:
        t.update({"review_required": True, "evidence": "BW_NO_STROKE_UNVALIDATED"})
    return t


# ---------------------------------------------------------------------------
# Phần 1 — evaluate_document_verdict_v2
# ---------------------------------------------------------------------------
def v_empty():
    for is_color in (True, False):
        st, act, _ = evaluate_document_verdict_v2([], is_color=is_color)
        assert (st, act) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"), (st, act)


def v_all_optional():
    for det in (True, False):
        st, act, reason = evaluate_document_verdict_v2([T("a", False, det), T("b", False, det)])
        assert (st, act) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"), (st, act)
        assert "NO_REQUIRED_TARGETS" in reason


def v_one_required_detected():
    st, act, _ = evaluate_document_verdict_v2([T("a", True, True)], is_color=True)
    assert (st, act) == ("DAT_CHUAN_GOC", "DUYET"), (st, act)
    st, act, _ = evaluate_document_verdict_v2([T("a", True, True)], is_color=False)
    assert (st, act) == ("DAT_CHUAN_PHOTO", "DUYET"), (st, act)


def v_required_not_detected():
    st, act, _ = evaluate_document_verdict_v2([T("a", True, False)])
    assert not st.startswith("DAT"), st
    assert (st, act) == ("CHUA_KY_DONG_DAU", "YEU_CAU_KY_LAI"), (st, act)


def v_partial():
    st, act, reason = evaluate_document_verdict_v2([T("a", True, True), T("b", True, False)])
    assert (st, act) == ("THIEU_MOT_SO_CHU_KY", "CANH_BAO"), (st, act)
    assert "b" in reason


def v_optional_miss_not_downgrade():
    st, _, _ = evaluate_document_verdict_v2([T("a", True, True), T("opt", False, False)])
    assert st == "DAT_CHUAN_GOC", st


def v_review_not_detected():
    # Giai đoạn 4: nhánh BW trả review_required=True -> KHÔNG được thành CHUA_KY / YEU_CAU_KY_LAI
    for is_color in (True, False):
        st, act, reason = evaluate_document_verdict_v2([T("a", True, False, review=True)], is_color=is_color)
        assert (st, act) == ("CAN_KIEM_TRA_TAY", "REVIEW_REQUIRED"), (st, act)
        assert "REVIEW_REQUIRED_TARGETS" in reason and "BW_NO_STROKE_UNVALIDATED" in reason, reason


def v_review_mixed():
    # 1 required review (không detected) + 1 required detected bình thường -> vẫn review, không THIEU/CHUA_KY
    st, act, _ = evaluate_document_verdict_v2([T("a", True, True), T("b", True, False, review=True)], is_color=False)
    assert (st, act) == ("CAN_KIEM_TRA_TAY", "REVIEW_REQUIRED"), (st, act)
    # toàn bộ required detected nhưng từ engine chưa kiểm chứng -> không được DAT
    st, act, _ = evaluate_document_verdict_v2([T("a", True, True, review=True)], is_color=False)
    assert (st, act) == ("CAN_KIEM_TRA_TAY", "REVIEW_REQUIRED"), (st, act)
    assert not st.startswith("DAT") and st != "CHUA_KY_DONG_DAU"


def v_review_optional_only():
    # cờ review chỉ trên ô optional -> không ảnh hưởng verdict required
    st, act, _ = evaluate_document_verdict_v2([T("a", True, True), T("opt", False, False, review=True)])
    assert (st, act) == ("DAT_CHUAN_GOC", "DUYET"), (st, act)
    st, act, _ = evaluate_document_verdict_v2([T("a", True, False), T("opt", False, False, review=True)])
    assert (st, act) == ("CHUA_KY_DONG_DAU", "YEU_CAU_KY_LAI"), (st, act)


def v_review_zero_required():
    # 0 required vẫn ABSTAIN kể cả khi có cờ review (nhánh ABSTAIN đi trước)
    st, act, _ = evaluate_document_verdict_v2([T("opt", False, False, review=True)])
    assert (st, act) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"), (st, act)


for n, f in [
    ("V1 targets rỗng -> ABSTAIN (màu & photo)", v_empty),
    ("V2 toàn optional -> ABSTAIN", v_all_optional),
    ("V3 1 required detected -> DAT_CHUAN_GOC/PHOTO", v_one_required_detected),
    ("V4 required không detected -> không DAT", v_required_not_detected),
    ("V5 thiếu 1/2 required -> THIEU_MOT_SO_CHU_KY", v_partial),
    ("V6 optional miss không hạ DAT", v_optional_miss_not_downgrade),
    ("V7 required review_required không detected -> CAN_KIEM_TRA_TAY (không CHUA_KY)", v_review_not_detected),
    ("V8 required review_required lẫn/đủ detected -> CAN_KIEM_TRA_TAY (không THIEU/DAT)", v_review_mixed),
    ("V9 review_required chỉ ở optional -> không đổi verdict", v_review_optional_only),
    ("V10 0 required + review -> vẫn ABSTAIN", v_review_zero_required),
]:
    case(n, f)


# ---------------------------------------------------------------------------
# Phần 2 — dispatch của runner Cell 3, trích nguyên văn từ generator
# ---------------------------------------------------------------------------
GEN_PATH = os.path.join(ROOT, "tools", "generate_nb4_ver2.py")


def _extract_dispatch_block():
    """Lấy đoạn từ `zone_status = zone.get("status")` tới hết khối if/elif/else
    (trước `results_list.append({` kế tiếp) trong code_cell_3 và bỏ thụt 4 khoảng."""
    src = open(GEN_PATH, encoding="utf-8").read()
    m3 = re.search(r'code_cell_3 = """(.*?)"""', src, re.S)
    assert m3, "không tìm thấy code_cell_3 trong generator"
    cell = m3.group(1)
    start = cell.index('    zone_status = zone.get("status")')
    end = cell.index("    results_list.append({", start)
    block = cell[start:end]
    lines = [ln[4:] if ln.startswith("    ") else ln for ln in block.split("\n")]
    return "\n".join(lines)


DISPATCH = None


def run_dispatch(zone, stub_results=None, modality="TRUE_COLOR", stub_review=False, system="MT_COOP"):
    """Chạy khối dispatch thật với stub detector. stub_results: list detected theo thứ tự target."""
    calls = {"verify": 0}
    stub_results = list(stub_results or [])

    def stub_verify(img, t, is_color=True):
        det = stub_results[calls["verify"]] if calls["verify"] < len(stub_results) else False
        calls["verify"] += 1
        res = {"detected": det, "confidence": 0.9 if det else 0.0, "ink_type": "stub",
               "reason": "stub", "evidence": "STUB", "bbox_px": (0, 0, 1, 1), "mask": None}
        if stub_review:  # giả lập nhánh BW của engine Giai đoạn 4
            res.update({"review_required": True, "evidence": "BW_NO_STROKE_UNVALIDATED",
                        "px_per_mm": 7.4074})
        return res

    ns = {
        "zone": zone,
        "system": system,
        "apply_lp_required_policy": apply_lp_required_policy,
        "a4": np.zeros((10, 10, 3), dtype=np.uint8),
        "summary_counts": __import__("collections").defaultdict(int),
        "detect_document_modality": lambda img: {"modality": modality},
        "verify_single_target": stub_verify,
        "evaluate_document_verdict_v2": evaluate_document_verdict_v2,
    }
    exec(DISPATCH, ns)  # noqa: S102 — mã nguồn của chính dự án
    return ns, calls["verify"]


def d_extract():
    global DISPATCH
    DISPATCH = _extract_dispatch_block()
    assert "PAGE_1_NO_SIGNATURES" in DISPATCH and "ABSTAIN" in DISPATCH


case("D0 trích được khối dispatch Cell 3 từ generator", d_extract)


def _mk_abstain_case(status):
    def f():
        assert DISPATCH, "dispatch chưa trích được"
        zone = {"has_signatures": False, "anchor_y": 0.3, "status": status,
                "description": f"giả lập {status}", "targets": []}
        ns, n_verify = run_dispatch(zone)
        assert (ns["doc_status"], ns["action"]) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"), \
            (ns["doc_status"], ns["action"])
        assert ns["zone_status"] == status, "zone_status bị ghi đè"
        assert status in ns["reason"], "lý do không giữ status Tầng 3b"
        assert n_verify == 0, "không được gọi verifier khi zone ABSTAIN"
        assert ns["verified_targets"] == []
    return f


for st in ABSTAIN_ZONE_STATUSES:
    case(f"D1 zone {st} -> ABSTAIN", _mk_abstain_case(st))


def d_has_sig_but_empty_targets():
    zone = {"has_signatures": True, "anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED", "targets": []}
    ns, n_verify = run_dispatch(zone)
    assert (ns["doc_status"], ns["action"]) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"), (ns["doc_status"], ns["action"])
    assert n_verify == 0


def d_has_sig_missing_key():
    # resolver quên khóa has_signatures -> coi như False, ABSTAIN (không đoán là có vùng ký)
    zone = {"anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED",
            "targets": [{"role": "x", "box_norm": [0.1, 0.1, 0.2, 0.2], "required": True, "expected_color": "blue_ink"}]}
    ns, _ = run_dispatch(zone, [True])
    assert ns["action"] == "ABSTAIN", ns["action"]


def d_page1():
    zone = {"has_signatures": False, "anchor_y": None, "status": "PAGE_1_NO_SIGNATURES", "targets": []}
    ns, n_verify = run_dispatch(zone)
    assert (ns["doc_status"], ns["action"]) == ("TRANG_1_CHUA_KY", "HOP_LE"), (ns["doc_status"], ns["action"])
    assert n_verify == 0


# Giai đoạn 5: `required` do CHÍNH SÁCH KÊNH quyết (config SOP), cờ required đầu vào bị ghi đè.
# Với system mặc định MT_COOP: "Tài xế" = required, "Người lập phiếu" = optional (mọi kênh).
ROLE_REQ_MT = "Tài xế (Lái xe nhận hàng)"
ROLE_OPT = "Người lập phiếu"


def _tg(req=True):
    return {"role": ROLE_REQ_MT if req else ROLE_OPT, "box_norm": [0.3, 0.1, 0.45, 0.25], "required": req,
            "expected_color": "blue_ink"}


def d_all_optional():
    zone = {"has_signatures": True, "anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED",
            "targets": [_tg(False), _tg(False)]}
    ns, n_verify = run_dispatch(zone, [True, True])
    assert (ns["doc_status"], ns["action"]) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN"), (ns["doc_status"], ns["action"])


def d_required_detected():
    zone = {"has_signatures": True, "anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED", "targets": [_tg(True)]}
    ns, n_verify = run_dispatch(zone, [True])
    assert n_verify == 1
    assert (ns["doc_status"], ns["action"]) == ("DAT_CHUAN_GOC", "DUYET"), (ns["doc_status"], ns["action"])
    ns, _ = run_dispatch(zone, [True], modality="PHOTOCOPY_BW")
    assert ns["doc_status"] == "DAT_CHUAN_PHOTO", ns["doc_status"]


def d_required_not_detected():
    zone = {"has_signatures": True, "anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED", "targets": [_tg(True)]}
    ns, _ = run_dispatch(zone, [False])
    assert not ns["doc_status"].startswith("DAT"), ns["doc_status"]
    assert ns["doc_status"] == "CHUA_KY_DONG_DAU", ns["doc_status"]


def d_bw_review_wired():
    # Cell 3 phải CHÉP cờ review_required của engine vào verified_targets, rồi verdict đọc nó:
    # ảnh BW, ô required không thấy nét -> CAN_KIEM_TRA_TAY/REVIEW_REQUIRED, không YEU_CAU_KY_LAI.
    zone = {"has_signatures": True, "anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED", "targets": [_tg(True), _tg(True)]}
    ns, n_verify = run_dispatch(zone, [False, False], modality="PHOTOCOPY_BW", stub_review=True)
    assert n_verify == 2
    assert all(vt.get("review_required") is True for vt in ns["verified_targets"]),         "Cell 3 không chép cờ review_required vào verified_targets"
    assert all("px_per_mm" in vt for vt in ns["verified_targets"]), "Cell 3 không chép px_per_mm"
    assert (ns["doc_status"], ns["action"]) == ("CAN_KIEM_TRA_TAY", "REVIEW_REQUIRED"), (ns["doc_status"], ns["action"])
    ns, _ = run_dispatch(zone, [True, True], modality="PHOTOCOPY_BW", stub_review=True)
    assert ns["doc_status"] == "CAN_KIEM_TRA_TAY", ns["doc_status"]


for n, f in [
    ("D2 has_signatures=True nhưng targets rỗng -> ABSTAIN", d_has_sig_but_empty_targets),
    ("D3 thiếu khóa has_signatures -> ABSTAIN", d_has_sig_missing_key),
    ("D4 PAGE_1_NO_SIGNATURES -> TRANG_1_CHUA_KY/HOP_LE", d_page1),
    ("D5 zone toàn optional -> ABSTAIN", d_all_optional),
    ("D6 1 required detected -> DAT", d_required_detected),
    ("D7 required không detected -> không DAT", d_required_not_detected),
    ("D8 BW review_required được Cell 3 chép & verdict đọc -> CAN_KIEM_TRA_TAY", d_bw_review_wired),
]:
    case(n, f)


# ---------------------------------------------------------------------------
# Phần 3 — chính sách required theo kênh (Giai đoạn 5, config SOP)
# ---------------------------------------------------------------------------
LP_ROLES = ["Người lập phiếu", "Trưởng BP Kho / Nhóm trưởng", "Tài xế (Lái xe nhận hàng)",
            "Người nhận hàng", "Người giao / Thủ kho xuất"]
TX, NN, NG = LP_ROLES[2], LP_ROLES[3], LP_ROLES[4]


def _lp_targets(detected=(True, True, True, True, True)):
    return [{"role": r, "box_norm": [0.6, 0.1 + 0.15 * i, 0.8, 0.2 + 0.15 * i], "required": True,
             "expected_color": "blue_ink", "detected": d} for i, (r, d) in enumerate(zip(LP_ROLES, detected))]


def _req_set(system):
    return {t["role"] for t in apply_lp_required_policy(_lp_targets(), system) if t["required"]}


def p_channel_map():
    exp = {"MT_COOP": ("MT", False), "MT_WINMART": ("MT", False), "GT": ("NPP", False),
           "INTERNAL_KHO_THUE": ("KHO_THUE", False), "INTERNAL_KHO_NOIBO": ("KHO_NOIBO", False),
           "COMMON": ("UNRESOLVED", True), "UNKNOWN": ("UNRESOLVED", True), "INTERNAL_TRANSFER": ("UNRESOLVED", True),
           "KHO_CHUA_RO": ("UNRESOLVED", True), "": ("UNRESOLVED", True), None: ("UNRESOLVED", True),
           "HE_THONG_LA": ("UNRESOLVED", True)}
    for sysv, (ch, unres) in exp.items():
        got = resolve_lp_channel(sysv)
        assert got[:2] == (ch, unres), (sysv, got)


def p_required_sets():
    assert _req_set("MT_AEON") == {TX, NG}, _req_set("MT_AEON")
    assert _req_set("GT") == {TX, NG, NN}, _req_set("GT")
    assert _req_set("INTERNAL_KHO_THUE") == {TX, NG}, _req_set("INTERNAL_KHO_THUE")
    assert _req_set("INTERNAL_KHO_NOIBO") == {TX, NG, NN}, _req_set("INTERNAL_KHO_NOIBO")


def p_always_optional_and_audit():
    for sysv in ("MT_COOP", "GT", "INTERNAL_KHO_THUE", "INTERNAL_KHO_NOIBO", "COMMON"):
        out = apply_lp_required_policy(_lp_targets(), sysv)
        assert len(out) == 5, "policy không được bỏ ô nào (optional vẫn verify + audit)"
        for t in out:
            assert t["required_source"].startswith("POLICY"), t["required_source"]
            assert "required_original" in t and t["policy_channel"]
            if t["role"] in LP_ROLES[:2]:
                assert t["required"] is False, (sysv, t["role"])


def p_unresolved_strict_flag():
    out = apply_lp_required_policy(_lp_targets(), "COMMON")
    assert all(t["policy_channel"] == "UNRESOLVED" and t["policy_channel_unresolved"] for t in out)
    assert {t["role"] for t in out if t["required"]} == {TX, NG, NN}
    assert all("STRICTEST_CHANNEL_UNRESOLVED" in t["required_source"] for t in out if t["required"])


def p_unknown_role_strict():
    out = apply_lp_required_policy([{"role": "Vai trò lạ", "required": False}], "MT_COOP")
    assert out[0]["required"] is True and out[0]["policy_role_unresolved"] is True, out


def p_missing_and_broken_config():
    import json as _json
    import tempfile
    try:
        load_lp_required_policy(os.path.join(ROOT, "config", "__khong_ton_tai__.json"))
        raise AssertionError("thiếu config mà không ném lỗi")
    except Stage4PolicyError:
        pass
    cfg = _json.load(open(os.path.join(ROOT, "config", "stage4_lp_required_policy.json"), encoding="utf-8"))
    cfg["channels"]["UNRESOLVED"]["required_roles"] = ["TAI_XE"]   # không còn nghiêm nhất
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False)
        tmp = f.name
    try:
        load_lp_required_policy(tmp)
        raise AssertionError("UNRESOLVED không nghiêm nhất mà không ném lỗi")
    except Stage4PolicyError:
        pass
    finally:
        os.remove(tmp)


def _zone5():
    return {"has_signatures": True, "anchor_y": 0.3, "status": "TABLE_BOTTOM_DETECTED",
            "targets": [{k: v for k, v in t.items() if k != "detected"} for t in _lp_targets()]}


def p_dispatch_channel():
    # Ô Người nhận (index 3) + Người lập (0) trống, còn lại ký.
    det = [False, False, True, False, True]
    ns, _ = run_dispatch(_zone5(), det, system="MT_BIGC")
    assert (ns["doc_status"], ns["action"]) == ("DAT_CHUAN_GOC", "DUYET"), (ns["doc_status"], ns["reason"])
    assert all(vt.get("policy_channel") == "MT" and vt.get("required_source") for vt in ns["verified_targets"])
    ns, _ = run_dispatch(_zone5(), det, system="GT")
    assert (ns["doc_status"], ns["action"]) == ("THIEU_MOT_SO_CHU_KY", "CANH_BAO"), ns["doc_status"]
    assert NN in ns["reason"] and LP_ROLES[0] not in ns["reason"], ns["reason"]
    ns, _ = run_dispatch(_zone5(), det, system="COMMON")
    assert ns["doc_status"] == "THIEU_MOT_SO_CHU_KY", ns["doc_status"]
    assert all(vt.get("policy_channel_unresolved") for vt in ns["verified_targets"])


for n, f in [
    ("P1 system Tầng 2 -> kênh theo config (chưa rõ -> UNRESOLVED)", p_channel_map),
    ("P2 bộ required theo kênh NPP/MT/KHO_THUE/KHO_NOIBO", p_required_sets),
    ("P3 Người lập + Trưởng BP optional mọi kênh, vẫn giữ ô audit", p_always_optional_and_audit),
    ("P4 kênh chưa rõ -> nghiêm nhất + cờ", p_unresolved_strict_flag),
    ("P5 vai trò lạ -> required (nghiêm) + cờ", p_unknown_role_strict),
    ("P6 thiếu / hỏng config -> Stage4PolicyError", p_missing_and_broken_config),
    ("P7 dispatch Cell 3 áp chính sách trước verdict (MT/NPP/chưa rõ)", p_dispatch_channel),
]:
    case(n, f)


# ---------------------------------------------------------------------------
# Phần 4 — phán quyết hồ sơ đa trang (nhóm trang từ Tầng 3, KHÔNG theo tên file)
# ---------------------------------------------------------------------------
def _page(fn, kind, system="MT_COOP", det=(True, True, True, True, True), modality="TRUE_COLOR"):
    r = {"file_name": fn, "doc_type": "LOADING_PLAN", "system": system, "modality": modality, "targets": []}
    if kind == "P1":
        r.update(zone_status="PAGE_1_NO_SIGNATURES", doc_status="TRANG_1_CHUA_KY")
    elif kind == "ABSTAIN":
        r.update(zone_status="COLUMN_DETECTION_FAILED", doc_status="CHUA_CHUAN_HOA_VUNG_KY")
    else:
        r.update(zone_status="TABLE_BOTTOM_DETECTED", doc_status="X",
                 targets=apply_lp_required_policy(_lp_targets(det), system))
    return r


def _s3(*groups):
    """groups: list các danh sách trang — mỗi nhóm = 1 chứng từ LP của Tầng 3."""
    docs = [{"doc_id": f"DOC_{i:03d}", "doc_type": "LOADING_PLAN", "is_multi_page": len(g) > 1,
             "file_name": g[0], "page_files": [f"output/form_samples/{pg}" for pg in g]} for i, g in enumerate(groups)]
    return {"batches": [{"batch_id": "B1", "documents": docs}]}


def _dv(pages, groups):
    res = evaluate_lp_dossier_verdicts(pages, _s3(*groups), evaluate_document_verdict_v2)
    return res, {d["dossier_id"]: d for d in res["dossiers"]}


def ds_multi_ok():
    # tên file cố ý vô nghĩa: nhóm lấy từ Tầng 3, không từ tên
    pages = [_page("SCAN_Q.png", "P1"), _page("SCAN_A.png", "SIG", det=(False, False, True, False, True))]
    res, m = _dv(pages, [["SCAN_Q.png", "SCAN_A.png"]])
    d = m["DOC_000"]
    assert (d["doc_status"], d["action"]) == ("DAT_CHUAN_GOC", "DUYET"), (d["doc_status"], d["reason"])
    assert d["policy_channel"] == "MT" and not d["policy_channel_unresolved"]


def ds_sig_page_abstain():
    pages = [_page("SCAN_Q.png", "P1"), _page("SCAN_A.png", "ABSTAIN")]
    _, m = _dv(pages, [["SCAN_Q.png", "SCAN_A.png"]])
    assert (m["DOC_000"]["doc_status"], m["DOC_000"]["action"]) == ("CHUA_CHUAN_HOA_VUNG_KY", "ABSTAIN")
    # trang ABSTAIN kể cả khi trang khác đã ký đủ
    pages = [_page("SCAN_A.png", "SIG"), _page("SCAN_B.png", "ABSTAIN")]
    _, m = _dv(pages, [["SCAN_A.png", "SCAN_B.png"]])
    assert m["DOC_000"]["action"] == "ABSTAIN", m["DOC_000"]["doc_status"]


def ds_no_block():
    for grp in (["SCAN_Q.png"], ["SCAN_Q.png", "SCAN_R.png"]):
        pages = [_page(fn, "P1") for fn in grp]
        _, m = _dv(pages, [grp])
        d = m["DOC_000"]
        assert (d["doc_status"], d["action"]) == ("KHONG_TIM_THAY_KHOI_KY", "REVIEW_REQUIRED"), d["doc_status"]
        assert not d["doc_status"].startswith("DAT")


def ds_unresolved_channel():
    pages = [_page("SCAN_Q.png", "P1", system="COMMON"),
             _page("SCAN_A.png", "SIG", system="COMMON", det=(True, True, True, False, True))]
    _, m = _dv(pages, [["SCAN_Q.png", "SCAN_A.png"]])
    d = m["DOC_000"]
    assert d["policy_channel"] == "UNRESOLVED" and d["policy_channel_unresolved"] is True
    assert d["doc_status"] == "THIEU_MOT_SO_CHU_KY" and NN in d["reason"], (d["doc_status"], d["reason"])


def ds_channel_conflict():
    pages = [_page("SCAN_A.png", "SIG", system="MT_COOP", det=(True, True, True, False, True)),
             _page("SCAN_B.png", "SIG", system="GT", det=(True, True, True, False, True))]
    _, m = _dv(pages, [["SCAN_A.png", "SCAN_B.png"]])
    d = m["DOC_000"]
    assert d["policy_channel"] == "UNRESOLVED" and "CHANNEL_CONFLICT" in d["policy_channel_reason"], d
    assert d["doc_status"] == "THIEU_MOT_SO_CHU_KY", d["doc_status"]


def ds_union_across_pages():
    # Tài xế ký ở trang A, Người giao ký ở trang B (kênh MT) -> hồ sơ đạt
    pages = [_page("SCAN_A.png", "SIG", det=(False, False, True, False, False)),
             _page("SCAN_B.png", "SIG", det=(False, False, False, False, True))]
    _, m = _dv(pages, [["SCAN_A.png", "SCAN_B.png"]])
    assert m["DOC_000"]["doc_status"] == "DAT_CHUAN_GOC", m["DOC_000"]["reason"]


def ds_orphan_and_grouping():
    # 2 chứng từ Tầng 3 riêng + 1 trang LP không thuộc chứng từ nào
    pages = [_page("SCAN_A.png", "SIG"), _page("SCAN_B.png", "P1"), _page("SCAN_C.png", "SIG")]
    res, m = _dv(pages, [["SCAN_A.png"], ["SCAN_B.png"]])
    assert m["DOC_000"]["doc_status"] == "DAT_CHUAN_GOC"
    assert m["DOC_001"]["doc_status"] == "KHONG_TIM_THAY_KHOI_KY", "P1 đứng một mình không được DAT"
    assert res["orphan_pages"] == ["SCAN_C.png"]
    orphan = [d for d in res["dossiers"] if d["source"] == "PAGE_NOT_IN_STAGE3_DOCUMENT"]
    assert len(orphan) == 1 and orphan[0]["action"] == "ABSTAIN"


def ds_missing_page_result_and_role():
    # Tầng 3 nhắc 1 trang không có kết quả Tầng 4 -> ABSTAIN
    _, m = _dv([_page("SCAN_A.png", "SIG")], [["SCAN_A.png", "SCAN_GHOST.png"]])
    assert m["DOC_000"]["action"] == "ABSTAIN", m["DOC_000"]["doc_status"]
    # vai trò required không có ô nào để đo -> ABSTAIN, không DAT
    p = _page("SCAN_A.png", "SIG")
    p["targets"] = [t for t in p["targets"] if t["role"] != NG]
    _, m = _dv([p], [["SCAN_A.png"]])
    assert m["DOC_000"]["action"] == "ABSTAIN" and "REQUIRED_ROLE_NOT_MEASURED" in m["DOC_000"]["reason"]


def ds_review_bw():
    p = _page("SCAN_A.png", "SIG", modality="PHOTOCOPY_BW")
    for t in p["targets"]:
        t["review_required"] = True
        t["evidence"] = "BW_NO_STROKE_UNVALIDATED"
    _, m = _dv([p], [["SCAN_A.png"]])
    assert (m["DOC_000"]["doc_status"], m["DOC_000"]["action"]) == ("CAN_KIEM_TRA_TAY", "REVIEW_REQUIRED")


for n, f in [
    ("DS1 đa trang (P1 + trang ký đủ required MT) -> DAT", ds_multi_ok),
    ("DS2 đa trang có trang ký ABSTAIN -> hồ sơ ABSTAIN", ds_sig_page_abstain),
    ("DS3 không trang nào có khối ký -> KHONG_TIM_THAY_KHOI_KY/REVIEW", ds_no_block),
    ("DS4 kênh chưa rõ -> nghiêm nhất + cờ (Người nhận required)", ds_unresolved_channel),
    ("DS5 các trang lệch kênh -> UNRESOLVED", ds_channel_conflict),
    ("DS6 vai trò ký ở các trang khác nhau -> gộp đạt", ds_union_across_pages),
    ("DS7 nhóm theo Tầng 3 + trang mồ côi -> ABSTAIN tường minh", ds_orphan_and_grouping),
    ("DS8 trang thiếu kết quả / vai trò required không đo được -> ABSTAIN", ds_missing_page_result_and_role),
    ("DS9 review_required (BW) -> CAN_KIEM_TRA_TAY cấp hồ sơ", ds_review_bw),
]:
    case(n, f)


if __name__ == "__main__":
    print("=" * 90)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print("=" * 90)
    print(f"{len(results) - n_fail}/{len(results)} PASSED")
    sys.exit(0 if n_fail == 0 else 1)
