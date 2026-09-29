"""Lớp (a) — app/services/review.py trên bản ghi s4 THẬT của manifest ver2 chính thức.

Không tự viết luật verdict: mọi kỳ vọng dưới đây là hệ quả của `evaluate_document_verdict_v2` /
`evaluate_lp_dossier_verdicts` khi thay detected/review_required theo bản duyệt.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from app.services import review as rs
from tools.stage4_verifier_v2 import evaluate_document_verdict_v2

from conftest import MANIFEST_S3, MANIFEST_V2


@pytest.fixture(scope="module")
def v2():
    return json.loads(MANIFEST_V2.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def s3():
    return json.loads(MANIFEST_S3.read_text(encoding="utf-8"))


def _page(v2, fn):
    return copy.deepcopy(next(d for d in v2["documents"] if d["file_name"] == fn))


def _rv(target, decision):
    return SimpleNamespace(role=target["role"], decision=decision)


def _dat_page_with_both(v2):
    """Trang LP DAT_CHUAN_* có cả ô required (detected) lẫn ô optional."""
    for d in v2["documents"]:
        ts = d.get("targets") or []
        if (d["doc_type"] == "LOADING_PLAN" and str(d["doc_status"]).startswith("DAT_CHUAN_")
                and any(t["required"] and t["detected"] for t in ts) and any(not t["required"] for t in ts)):
            return copy.deepcopy(d)
    pytest.fail("manifest ver2 không có trang LP DAT với ô required + optional")


def test_no_review_equals_machine_and_recompute_consistent(v2):
    for d in v2["documents"]:
        eff = rs.page_effective(d, {})
        assert (eff["doc_status"], eff["action"], eff["reason"]) == (d["doc_status"], d["action"], d["reason"])
        assert eff["source"] == "MACHINE" and eff["n_overridden"] == 0
        if d.get("targets"):  # hàm verdict gọi lại trên targets máy phải ra đúng như pipeline
            st, act, _ = evaluate_document_verdict_v2(d["targets"], is_color=(d["modality"] == "TRUE_COLOR"))
            assert (st, act) == (d["doc_status"], d["action"])


def test_not_signed_required_breaks_dat(v2):
    d = _dat_page_with_both(v2)
    i = next(k for k, t in enumerate(d["targets"]) if t["required"] and t["detected"])
    before = copy.deepcopy(d)
    eff = rs.page_effective(d, {i: _rv(d["targets"][i], "NOT_SIGNED")})
    assert not str(eff["doc_status"]).startswith("DAT_"), eff
    assert eff["doc_status"] in ("THIEU_MOT_SO_CHU_KY", "CHUA_KY_DONG_DAU")
    assert eff["n_overridden"] == 1 and eff["source"] == "AFTER_REVIEW"
    assert d == before  # kết quả máy không bị sửa


def test_not_signed_optional_keeps_dat(v2):
    d = _dat_page_with_both(v2)
    i = next(k for k, t in enumerate(d["targets"]) if not t["required"])
    eff = rs.page_effective(d, {i: _rv(d["targets"][i], "NOT_SIGNED")})
    assert eff["doc_status"] == d["doc_status"] and str(eff["doc_status"]).startswith("DAT_CHUAN_")


def test_unclear_required_needs_manual_check(v2):
    d = _dat_page_with_both(v2)
    i = next(k for k, t in enumerate(d["targets"]) if t["required"])
    eff = rs.page_effective(d, {i: _rv(d["targets"][i], "UNCLEAR")})
    assert eff["doc_status"] == "CAN_KIEM_TRA_TAY" and eff["action"] == "REVIEW_REQUIRED"
    assert rs.effective_detected(d["targets"][i], _rv(d["targets"][i], "UNCLEAR")) is None


def test_signed_fixes_missing_required(v2):
    d = _dat_page_with_both(v2)
    reqs = [k for k, t in enumerate(d["targets"]) if t["required"]]
    # máy: bỏ 1 ô required (giả lập), người duyệt xác nhận có ký ⇒ về DAT
    d["targets"][reqs[0]]["detected"] = False
    assert not evaluate_document_verdict_v2(d["targets"], True)[0].startswith("DAT_")
    d["doc_status"] = "THIEU_MOT_SO_CHU_KY"
    eff = rs.page_effective(d, {reqs[0]: _rv(d["targets"][reqs[0]], "SIGNED")})
    assert eff["doc_status"] == "DAT_CHUAN_GOC"


def test_stale_review_not_applied(v2):
    d = _dat_page_with_both(v2)
    i = next(k for k, t in enumerate(d["targets"]) if t["required"])
    stale = SimpleNamespace(role="VAI TRO CU KHAC", decision="NOT_SIGNED")
    assert rs.review_is_stale(stale, d["targets"][i])
    eff = rs.page_effective(d, {i: stale})
    assert eff["doc_status"] == d["doc_status"] and eff["source"] == "MACHINE"


def test_page_without_targets_is_machine(v2):
    for d in v2["documents"]:
        if not d.get("targets"):
            eff = rs.page_effective(d, {0: SimpleNamespace(role="x", decision="SIGNED")})
            assert eff["doc_status"] == d["doc_status"] and eff["source"] == "MACHINE"
    assert rs.page_effective(None, {})["doc_status"] is None


def test_invalid_decision_raises(v2):
    d = _dat_page_with_both(v2)
    with pytest.raises(ValueError):
        rs.apply_review_to_target(d["targets"][0], _rv(d["targets"][0], "MAYBE"))


def test_dossier_after_review(v2, s3):
    dv = v2["dossier_verdicts"]
    docs = v2["documents"]
    # Không duyệt ⇒ đúng phán quyết hồ sơ của máy
    same = rs.group_effective_dossiers(dv, s3, docs, {})
    assert same["summary"] == dv["summary"]
    # Hồ sơ đa trang: đánh NOT_SIGNED một ô required ở trang có khối ký ⇒ hồ sơ hết DAT
    multi = next(x for x in dv["dossiers"] if len(x["pages"]) > 1 and x["doc_status"].startswith("DAT_"))
    sig_pg = next(p for p, c in multi["page_classes"].items() if c == "SIGNATURE_BLOCK")
    page = next(d for d in docs if d["file_name"] == sig_pg)
    req = [k for k, t in enumerate(page["targets"]) if t["required"] and t["detected"]]
    assert req
    latest = {sig_pg: {k: _rv(page["targets"][k], "NOT_SIGNED") for k in req}}
    eff = rs.group_effective_dossiers(dv, s3, docs, latest)
    got = next(x for x in eff["dossiers"] if x["dossier_id"] == multi["dossier_id"] and x["pages"] == multi["pages"])
    assert not got["doc_status"].startswith("DAT_"), got["doc_status"]
    # các hồ sơ khác không đổi
    others = {(x["dossier_id"], tuple(x["pages"])): x["doc_status"] for x in eff["dossiers"]}
    for x in dv["dossiers"]:
        if x["dossier_id"] != multi["dossier_id"]:
            assert others[(x["dossier_id"], tuple(x["pages"]))] == x["doc_status"]
    # UNCLEAR ô required ⇒ hồ sơ cần kiểm tra tay
    latest_u = {sig_pg: {req[0]: _rv(page["targets"][req[0]], "UNCLEAR")}}
    eff_u = rs.group_effective_dossiers(dv, s3, docs, latest_u)
    got_u = next(x for x in eff_u["dossiers"] if x["dossier_id"] == multi["dossier_id"])
    assert got_u["doc_status"] == "CAN_KIEM_TRA_TAY"
