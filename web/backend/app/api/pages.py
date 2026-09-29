"""API trang (SPEC §3 "Trang"). Router prefix "/pages" — main.py include thêm "/api".

Phân quyền: chủ bộ upload hoặc admin; không thì 404 (không lộ sự tồn tại).
Kết quả máy (`page.s4`) không bao giờ bị sửa; duyệt tay là bản ghi append-only `signature_reviews`,
phán quyết sau duyệt tính lại qua `app.services.review` (gọi hàm verdict của pipeline).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import labels
from app.api.deps import api_error, get_current_user, get_db, require_csrf_header, write_audit
from app.models import (
    GROUP_DONE, REVIEW_DECISIONS, ROLE_ADMIN, Page, SignatureReview, UploadGroup, User,
)
from app.services import review as review_svc
from app.services import storage

router = APIRouter(prefix="/pages", tags=["pages"])

MAX_NOTE_LEN = 2000
_IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def is_admin(user: User) -> bool:
    return getattr(user, "role", None) == ROLE_ADMIN


def load_page_for_user(db: Session, page_id: uuid.UUID, user: User) -> Page:
    page = db.get(Page, page_id)
    if page is None:
        raise api_error(404, "PAGE_NOT_FOUND", "Không tìm thấy trang.")
    group = page.group
    if group is None or (group.user_id != user.id and not is_admin(user)):
        raise api_error(404, "PAGE_NOT_FOUND", "Không tìm thấy trang.")
    return page


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------------------------------
# Dựng PageSummary / PageDetail
# ---------------------------------------------------------------------------------------------------
def page_summary(page: Page, latest_by_index: Mapping[int, Any]) -> Dict[str, Any]:
    eff = review_svc.page_effective(page.s4, latest_by_index)
    machine_lbl = labels.page_status_label(page.doc_type, page.s4_doc_status)
    eff_lbl = labels.page_status_label(page.doc_type, eff["doc_status"])
    s1_lbl = labels.s1_status_label(page.s1_status)
    return {
        "id": str(page.id),
        "group_id": str(page.group_id),
        "scan_index": page.scan_index,
        "original_filename": page.original_filename,
        "width": page.width,
        "height": page.height,
        "s1_status": page.s1_status,
        "s1_status_label_vi": s1_lbl["label_vi"],
        "s1_status_tone": s1_lbl["tone"],
        "doc_type": page.doc_type,
        "doc_type_vi": labels.doc_type_vi(page.doc_type),
        "system": page.system,
        "page_role": page.page_role,
        "batch_id": page.batch_id,
        "s4_doc_status": page.s4_doc_status,
        "s4_action": page.s4_action,
        # Nhãn/tone theo phán quyết HIỆU LỰC (sau duyệt nếu có); nhãn máy đi kèm để so sánh.
        "status_label_vi": eff_lbl["label_vi"],
        "status_tone": eff_lbl["tone"],
        "status_unknown": eff_lbl["unknown"],
        "machine_status_label_vi": machine_lbl["label_vi"],
        "machine_status_tone": machine_lbl["tone"],
        "supported": labels.is_supported(page.doc_type),
        "reviewed": eff["n_reviewed"] > 0,
        "effective_doc_status": eff["doc_status"],
        "effective_action": eff["action"],
        "key_fields": (page.s2 or {}).get("key_fields"),
    }


def _review_out(rv: Any, target: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "id": str(rv.id),
        "target_index": rv.target_index,
        "role": rv.role,
        "machine_detected": rv.machine_detected,
        "decision": rv.decision,
        "decision_vi": labels.REVIEW_DECISION_LABELS.get(rv.decision, rv.decision),
        "note": rv.note,
        "reviewer_email": getattr(rv, "reviewer_email", None),
        "created_at": _iso(rv.created_at),
        "stale": target is None or review_svc.review_is_stale(rv, target),
    }


def target_out(i: int, t: Mapping[str, Any], rv: Any) -> Dict[str, Any]:
    ev = labels.evidence_label(t.get("evidence"))
    return {
        "index": i,
        "role": t.get("role"),
        "required": bool(t.get("required", True)),
        "required_source": t.get("required_source"),
        "policy_channel": t.get("policy_channel"),
        "box_norm": t.get("box_norm"),
        "detected": bool(t.get("detected")),
        "confidence": t.get("confidence"),
        "evidence": t.get("evidence"),
        "evidence_label_vi": ev["label_vi"],
        "reason": t.get("reason"),
        "review_required": bool(t.get("review_required", False)),
        "latest_review": None if rv is None else _review_out(rv, t),
        "effective_detected": review_svc.effective_detected(t, rv),
    }


def page_detail(db: Session, page: Page) -> Dict[str, Any]:
    latest = review_svc.latest_reviews_for_pages(db, [page.id]).get(page.id, {})
    out = page_summary(page, latest)
    s1 = page.s1 or {}
    s2 = page.s2 or {}
    s4 = page.s4 or {}
    eff = review_svc.page_effective(page.s4, latest)
    eff_lbl = labels.page_status_label(page.doc_type, eff["doc_status"])
    zl = labels.zone_status_label(s4.get("zone_status"))
    out.update({
        "group_title": page.group.title if page.group else None,
        "group_status": page.group.status if page.group else None,
        "s1": {
            "status": s1.get("status"),
            "status_label_vi": labels.s1_status_label(s1.get("status"))["label_vi"],
            "action": s1.get("action"),
            "warns": s1.get("warns") or [],
            "rejects": s1.get("rejects") or [],
            "source_type": s1.get("source_type"),
            "low_resolution": s1.get("low_resolution"),
            "effective_dpi": (s1.get("quality_output") or {}).get("effective_dpi"),
            "error": s1.get("error"),
        } if page.s1 is not None else None,
        "s2": {
            "doc_type": s2.get("doc_type"),
            "doc_type_vi": labels.doc_type_vi(s2.get("doc_type")),
            "system": s2.get("system"),
            "page_role": s2.get("page_role"),
            "confidence": s2.get("confidence"),
            "status": s2.get("status"),
            "key_fields": s2.get("key_fields"),
            "evidence": s2.get("evidence"),
        } if page.s2 is not None else None,
        "s4": {
            "zone_status": s4.get("zone_status"),
            "zone_status_label_vi": zl["label_vi"],
            "zone_description": s4.get("zone_description"),
            "modality": s4.get("modality"),
            "doc_status": s4.get("doc_status"),
            "doc_status_label_vi": labels.page_status_label(page.doc_type, s4.get("doc_status"))["label_vi"],
            "action": s4.get("action"),
            "action_label_vi": labels.action_label(s4.get("action"))["label_vi"],
            "reason": s4.get("reason"),
            "required_policy": s4.get("required_policy"),
            "a4_size": s4.get("a4_size"),
            "targets": [target_out(i, t, latest.get(i)) for i, t in enumerate(s4.get("targets") or [])],
        } if page.s4 is not None else None,
        "effective": {
            "doc_status": eff["doc_status"],
            "action": eff["action"],
            "action_label_vi": labels.action_label(eff["action"])["label_vi"],
            "reason": eff["reason"],
            "n_overridden": eff["n_overridden"],
            "n_reviewed": eff["n_reviewed"],
            "source": eff["source"],
            "label_vi": eff_lbl["label_vi"],
            "tone": eff_lbl["tone"],
        },
    })
    return out


# ---------------------------------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------------------------------
@router.get("/{page_id}")
def get_page(page_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return page_detail(db, load_page_for_user(db, page_id, user))


@router.get("/{page_id}/image")
def get_page_image(page_id: uuid.UUID, kind: str = Query("stage1"), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    page = load_page_for_user(db, page_id, user)
    if kind == "original":
        src = page.stored_path
    elif kind == "stage1":
        src = page.stage1_image_path
    else:
        raise api_error(400, "INVALID_IMAGE_KIND", "Tham số kind phải là 'original' hoặc 'stage1'.")
    if not src:
        raise api_error(404, "IMAGE_NOT_AVAILABLE", "Ảnh chưa có (trang chưa xử lý xong hoặc Tầng 1 không xuất ảnh).")
    try:
        path = storage.safe_existing_file(src)
    except storage.UnsafePathError:
        path = None  # không lộ đường dẫn thật cho client
    if path is None:
        raise api_error(404, "IMAGE_NOT_AVAILABLE", "Không tìm thấy tệp ảnh.")
    return FileResponse(path, media_type=_IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream"),
                        headers={"Cache-Control": "private, no-cache"})


class ReviewIn(BaseModel):
    decision: str
    note: str = ""


@router.post("/{page_id}/targets/{index}/review", dependencies=[Depends(require_csrf_header)])
def create_review(page_id: uuid.UUID, index: int, body: ReviewIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    page = load_page_for_user(db, page_id, user)
    if body.decision not in REVIEW_DECISIONS:
        raise api_error(400, "INVALID_DECISION",
                        "Quyết định phải là SIGNED (có chữ ký), NOT_SIGNED (không có) hoặc UNCLEAR (không rõ).")
    note = (body.note or "").strip()
    if len(note) > MAX_NOTE_LEN:
        raise api_error(400, "NOTE_TOO_LONG", f"Ghi chú tối đa {MAX_NOTE_LEN} ký tự.")
    if page.group.status != GROUP_DONE:
        raise api_error(409, "GROUP_NOT_READY", "Bộ upload chưa xử lý xong — chưa duyệt được.")
    targets = (page.s4 or {}).get("targets") or []
    if not targets:
        raise api_error(400, "NO_TARGETS", "Trang này không có ô ký để duyệt.")
    if index < 0 or index >= len(targets):
        raise api_error(404, "TARGET_NOT_FOUND", "Không tìm thấy ô ký.")
    t = targets[index]
    rv = SignatureReview(page_id=page.id, target_index=index, role=str(t.get("role") or "")[:200],
                         machine_detected=bool(t.get("detected")), decision=body.decision, note=note,
                         reviewer_id=user.id, created_at=datetime.now(timezone.utc))
    db.add(rv)
    db.flush()
    write_audit(db, user.id, "review_create", "page", str(page.id),
                {"review_id": str(rv.id), "target_index": index, "role": rv.role, "decision": rv.decision,
                 "machine_detected": rv.machine_detected, "group_id": str(page.group_id)})
    db.commit()
    db.refresh(page)
    return page_detail(db, page)


@router.get("/{page_id}/reviews")
def list_reviews(page_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    page = load_page_for_user(db, page_id, user)
    targets = (page.s4 or {}).get("targets") or []
    rows = db.execute(
        select(SignatureReview, User.email).join(User, User.id == SignatureReview.reviewer_id)
        .where(SignatureReview.page_id == page.id)
        .order_by(SignatureReview.created_at.desc(), SignatureReview.target_index)
    ).all()
    out: List[Dict[str, Any]] = []
    for rv, email in rows:
        rv.reviewer_email = email
        t = targets[rv.target_index] if 0 <= rv.target_index < len(targets) else None
        out.append(_review_out(rv, t))
    return out
