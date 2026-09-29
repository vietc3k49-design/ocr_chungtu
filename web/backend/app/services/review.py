"""Phán quyết SAU DUYỆT (SPEC §3 "Phán quyết sau duyệt").

Không tự viết luật verdict: chỉ thay `detected` / `review_required` của từng ô theo bản duyệt mới nhất
rồi gọi lại đúng hàm của pipeline:
  * trang   : `tools.stage4_verifier_v2.evaluate_document_verdict_v2(targets, is_color=modality=="TRUE_COLOR")`
  * hồ sơ   : `tools.stage4_required_policy.evaluate_lp_dossier_verdicts(page_results, stage3_manifest, ...)`

Quy tắc áp bản duyệt lên ô i (bản mới nhất theo created_at):
  * SIGNED     ⇒ detected=True,  review_required=False (người đã kiểm chứng)
  * NOT_SIGNED ⇒ detected=False, review_required=False
  * UNCLEAR    ⇒ review_required=True (detected giữ như máy) ⇒ ô required sẽ cho CAN_KIEM_TRA_TAY
  * Bản duyệt có `role` KHÁC role hiện tại của ô i (kết quả máy đã thay sau khi chạy lại) ⇒ `stale`,
    KHÔNG áp dụng.
Kết quả máy (`page.s4`) không bao giờ bị sửa — mọi hàm ở đây làm trên bản sao.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.core.config import get_settings as _get_settings

_get_settings()  # ghim .env theo cwd ban đầu TRƯỚC khi runner os.chdir về gốc repo (env_file tương đối)
from app.pipeline import runner as _runner  # noqa: F401 — đặt sys.path/cwd về gốc repo trước khi import tools
from tools.stage4_required_policy import evaluate_lp_dossier_verdicts, load_lp_required_policy  # noqa: E402
from tools.stage4_verifier_v2 import evaluate_document_verdict_v2  # noqa: E402
from tools.stage4_template_verifier import merge_template_dossiers  # noqa: E402

from app.models import REVIEW_NOT_SIGNED, REVIEW_SIGNED, REVIEW_UNCLEAR  # noqa: E402

_POLICY: Optional[Dict[str, Any]] = None


def _policy() -> Dict[str, Any]:
    global _POLICY
    if _POLICY is None:
        _POLICY = load_lp_required_policy()
    return _POLICY


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------------------------------
# Ô ký
# ---------------------------------------------------------------------------------------------------
def review_is_stale(review: Any, target: Mapping[str, Any]) -> bool:
    """Bản duyệt không còn khớp ô hiện tại (role khác sau khi chạy lại)."""
    return _get(review, "role") != target.get("role")


def apply_review_to_target(target: Mapping[str, Any], review: Any) -> Dict[str, Any]:
    """Bản sao target với detected/review_required hiệu lực. review=None hoặc stale ⇒ như máy."""
    t = dict(target)
    if review is None or review_is_stale(review, target):
        return t
    decision = _get(review, "decision")
    if decision == REVIEW_SIGNED:
        t["detected"] = True
        t["review_required"] = False
    elif decision == REVIEW_NOT_SIGNED:
        t["detected"] = False
        t["review_required"] = False
    elif decision == REVIEW_UNCLEAR:
        t["review_required"] = True
    else:  # quyết định lạ không được âm thầm bỏ qua
        raise ValueError(f"Quyết định duyệt không hợp lệ: {decision!r}")
    t["human_decision"] = decision
    return t


def effective_detected(target: Mapping[str, Any], review: Any) -> Optional[bool]:
    """bool nếu biết chắc (máy đã kiểm chứng hoặc người duyệt SIGNED/NOT_SIGNED); None nếu không rõ."""
    t = apply_review_to_target(target, review)
    if t.get("review_required"):
        return None
    return bool(t.get("detected"))


def _changes_something(machine: Mapping[str, Any], eff: Mapping[str, Any]) -> bool:
    return (bool(machine.get("detected")) != bool(eff.get("detected"))
            or bool(machine.get("review_required")) != bool(eff.get("review_required")))


def effective_targets(targets: Iterable[Mapping[str, Any]], latest_by_index: Mapping[int, Any]):
    """Trả (targets hiệu lực, n_applied, n_overridden). n_overridden = số ô bản duyệt làm ĐỔI trạng thái."""
    out: List[Dict[str, Any]] = []
    n_applied = n_over = 0
    for i, t in enumerate(targets or []):
        rv = latest_by_index.get(i)
        eff = apply_review_to_target(t, rv)
        if rv is not None and not review_is_stale(rv, t):
            n_applied += 1
            if _changes_something(t, eff):
                n_over += 1
        out.append(eff)
    return out, n_applied, n_over


# ---------------------------------------------------------------------------------------------------
# Trang
# ---------------------------------------------------------------------------------------------------
def page_effective(s4: Optional[Mapping[str, Any]], latest_by_index: Mapping[int, Any]) -> Dict[str, Any]:
    """{doc_status, action, reason, n_overridden, n_reviewed, source, targets}.

    Trang không có targets (ngoài phạm vi / zone ABSTAIN / trang 1) hoặc không có bản duyệt áp dụng
    ⇒ phán quyết máy nguyên vẹn (source="MACHINE").
    """
    if not s4:
        return {"doc_status": None, "action": None, "reason": None, "n_overridden": 0, "n_reviewed": 0,
                "source": "NONE", "targets": []}
    targets = s4.get("targets") or []
    machine = {"doc_status": s4.get("doc_status"), "action": s4.get("action"), "reason": s4.get("reason")}
    if not targets:
        return {**machine, "n_overridden": 0, "n_reviewed": 0, "source": "MACHINE", "targets": []}
    eff_targets, n_applied, n_over = effective_targets(targets, latest_by_index)
    if n_applied == 0:
        return {**machine, "n_overridden": 0, "n_reviewed": 0, "source": "MACHINE",
                "targets": [dict(t) for t in targets]}
    st, act, why = evaluate_document_verdict_v2(eff_targets, is_color=(s4.get("modality") == "TRUE_COLOR"))
    return {"doc_status": st, "action": act, "reason": why, "n_overridden": n_over, "n_reviewed": n_applied,
            "source": "AFTER_REVIEW", "targets": eff_targets}


# ---------------------------------------------------------------------------------------------------
# Hồ sơ đa trang
# ---------------------------------------------------------------------------------------------------
def group_effective_dossiers(stage4_dossiers: Optional[Mapping[str, Any]],
                             stage3_manifest: Optional[Mapping[str, Any]],
                             pages_s4: Iterable[Optional[Mapping[str, Any]]],
                             latest_by_file: Mapping[str, Mapping[int, Any]]) -> Optional[Dict[str, Any]]:
    """Phán quyết hồ sơ sau duyệt. pages_s4: s4 của MỌI trang trong bộ; latest_by_file: {file_name: {i: review}}.

    Không có bản duyệt nào áp dụng ⇒ trả nguyên `stage4_dossiers` của máy.
    """
    if stage4_dossiers is None or stage3_manifest is None:
        return None
    page_results = []
    any_applied = False
    for s4 in pages_s4:
        if not s4:
            continue
        fn = s4.get("file_name")
        eff = page_effective(s4, latest_by_file.get(fn, {}))
        if eff["source"] == "AFTER_REVIEW":
            any_applied = True
        r = copy.deepcopy(dict(s4))
        r["targets"] = eff["targets"]
        r["doc_status"], r["action"], r["reason"] = eff["doc_status"], eff["action"], eff["reason"]
        page_results.append(r)
    if not any_applied:
        return copy.deepcopy(dict(stage4_dossiers))
    lp = evaluate_lp_dossier_verdicts(page_results, dict(stage3_manifest), evaluate_document_verdict_v2,
                                      _policy())
    # Giống runner.run_stage4: gộp hồ sơ một-trang của biểu mẫu hạng A, nếu không đường
    # "tính lại sau duyệt tay" sẽ đánh rơi chúng và lệch với kết quả máy.
    return merge_template_dossiers(lp, page_results)


# ---------------------------------------------------------------------------------------------------
# Truy vấn DB (bản duyệt mới nhất)
# ---------------------------------------------------------------------------------------------------
def latest_reviews_for_pages(db, page_ids: Iterable) -> Dict[Any, Dict[int, Any]]:
    """{page_id: {target_index: SignatureReview mới nhất}} — gắn thêm thuộc tính `reviewer_email`."""
    from sqlalchemy import select

    from app.models import SignatureReview, User

    ids = list(page_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(SignatureReview, User.email)
        .join(User, User.id == SignatureReview.reviewer_id)
        .where(SignatureReview.page_id.in_(ids))
        .order_by(SignatureReview.page_id, SignatureReview.target_index, SignatureReview.created_at)
    ).all()
    out: Dict[Any, Dict[int, Any]] = {}
    for rv, email in rows:
        rv.reviewer_email = email  # thuộc tính tạm, không phải cột
        out.setdefault(rv.page_id, {})[rv.target_index] = rv  # tăng dần theo created_at ⇒ bản cuối là mới nhất
    return out
