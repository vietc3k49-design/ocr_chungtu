"""API bộ upload (SPEC §3 "Bộ upload"). Router prefix "/groups" — main.py include thêm "/api".

* Thứ tự file trong form = scan_index 0..n-1. Pipeline chỉ thấy `stored_filename`, không thấy tên gốc.
* `use_reference` (dữ liệu tham chiếu mã chuyến DEMO suy từ GT): chỉ admin được đặt khi upload;
  user thường ⇒ bỏ qua giá trị gửi lên, dùng setting `use_reference_default` (mặc định TẮT).
* Phân quyền: chủ sở hữu hoặc admin, không thì 404.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import labels
from app.api.deps import (
    get_current_user, get_db, read_use_reference_default, require_csrf_header, write_audit,
)
from app.api.pages import api_error, is_admin, page_summary
from app.models import (
    GROUP_DONE, GROUP_FAILED, GROUP_QUEUED, JOB_QUEUED, JOB_RUNNING, Job, Page, SignatureReview, UploadGroup, User,
)
from app.services import review as review_svc
from app.services import storage

router = APIRouter(prefix="/groups", tags=["groups"])

REFERENCE_BADGE_VI = "Dùng dữ liệu tham chiếu DEMO (suy từ GT)"
GROUP_STATUS_VI = {"QUEUED": "Đang chờ", "RUNNING": "Đang xử lý", "DONE": "Hoàn tất", "FAILED": "Thất bại"}
_TRUE = {"1", "true", "on", "yes"}
_FALSE = {"0", "false", "off", "no", ""}


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def load_group_for_user(db: Session, group_id: uuid.UUID, user: User) -> UploadGroup:
    g = db.get(UploadGroup, group_id)
    if g is None or (g.user_id != user.id and not is_admin(user)):
        raise api_error(404, "GROUP_NOT_FOUND", "Không tìm thấy bộ upload.")
    return g


def _parse_bool_form(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise api_error(400, "INVALID_USE_REFERENCE", "Giá trị use_reference không hợp lệ (true/false).")


def latest_job(db: Session, group_id) -> Optional[Job]:
    return db.execute(select(Job).where(Job.group_id == group_id).order_by(Job.created_at.desc()).limit(1)
                      ).scalar_one_or_none()


def job_out(job: Optional[Job]) -> Optional[Dict[str, Any]]:
    if job is None:
        return None
    return {"id": str(job.id), "status": job.status, "stage": job.stage, "stage_done": job.stage_done,
            "stage_total": job.stage_total, "percent": job.percent, "message": job.message,
            "error": job.error, "attempts": job.attempts, "created_at": _iso(job.created_at),
            "started_at": _iso(job.started_at), "finished_at": _iso(job.finished_at)}


def _dossier_key(d: Dict[str, Any]):
    return (d.get("dossier_id"), tuple(d.get("pages") or []))


def _effective_dossiers(db: Session, group: UploadGroup, latest: Dict[Any, Dict[int, Any]]):
    by_file = {p.stored_filename: latest.get(p.id, {}) for p in group.pages}
    return review_svc.group_effective_dossiers(group.stage4_dossiers, group.stage3_manifest,
                                               [p.s4 for p in group.pages], by_file)


def _lp_summary(dossiers: Optional[Dict[str, Any]]) -> Dict[str, int]:
    return dict((dossiers or {}).get("summary") or {})


def group_summary(group: UploadGroup, owner_email: Optional[str], n_lp_pages: int,
                  eff_dossiers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": str(group.id),
        "title": group.title,
        "status": group.status,
        "status_label_vi": GROUP_STATUS_VI.get(group.status, f"{group.status} · Cần kiểm tra"),
        "error": group.error,
        "n_pages": group.n_pages,
        "use_reference": bool(group.use_reference),
        "reference_badge_vi": REFERENCE_BADGE_VI if group.use_reference else None,
        "created_at": _iso(group.created_at),
        "finished_at": _iso(group.finished_at),
        "owner_email": owner_email,
        "n_lp_pages": n_lp_pages,
        "lp_dossier_summary": _lp_summary(eff_dossiers if eff_dossiers is not None else group.stage4_dossiers),
        "lp_dossier_summary_machine": _lp_summary(group.stage4_dossiers),
    }


def group_detail(db: Session, group: UploadGroup) -> Dict[str, Any]:
    pages = sorted(group.pages, key=lambda p: p.scan_index)
    latest = review_svc.latest_reviews_for_pages(db, [p.id for p in pages])
    eff = _effective_dossiers(db, group, latest)
    owner = db.get(User, group.user_id)
    n_lp = sum(1 for p in pages if p.doc_type in labels.SUPPORTED_DOC_TYPES)
    out = group_summary(group, owner.email if owner else None, n_lp, eff)
    fn_to_page = {p.stored_filename: p for p in pages}
    eff_by_key = {_dossier_key(d): d for d in ((eff or {}).get("dossiers") or [])}
    dossiers = []
    for d in ((group.stage4_dossiers or {}).get("dossiers") or []):
        m_lbl = labels.doc_status_label(d.get("doc_status"))
        e = eff_by_key.get(_dossier_key(d))
        if e is None:  # không được xảy ra (cùng manifest, cùng thứ tự) — báo tường minh thay vì đoán
            e = {"doc_status": None, "action": None, "reason": "EFFECTIVE_DOSSIER_NOT_FOUND"}
        e_lbl = labels.doc_status_label(e.get("doc_status"))
        dossiers.append({
            **d,
            "label_vi": m_lbl["label_vi"], "tone": m_lbl["tone"], "unknown": m_lbl["unknown"],
            "effective_doc_status": e.get("doc_status"), "effective_action": e.get("action"),
            "effective_reason": e.get("reason"),
            "effective_label_vi": e_lbl["label_vi"], "effective_tone": e_lbl["tone"],
            "page_refs": [{"file_name": fn,
                           "page_id": str(fn_to_page[fn].id) if fn in fn_to_page else None,
                           "scan_index": fn_to_page[fn].scan_index if fn in fn_to_page else None}
                          for fn in (d.get("pages") or [])],
        })
    batches = []
    for b in ((group.stage3_manifest or {}).get("batches") or []):
        bid = b.get("batch_id") or ""
        batches.append({"batch_id": bid, "n_documents": len(b.get("documents") or []),
                        "is_isolated": bid.startswith("UNRESOLVED_"), "system": b.get("system")})
    out.update({
        "pages": [page_summary(p, latest.get(p.id, {})) for p in pages],
        "dossiers": dossiers,
        "batches": batches,
        "reference_info": group.reference_info,
        "timings": group.timings,
        "pipeline_contract": group.pipeline_contract,
        "stage3_scope": "UPLOAD_GROUP",
        "job": job_out(latest_job(db, group.id)),
    })
    return out


def _summaries(db: Session, groups: List[UploadGroup]) -> List[Dict[str, Any]]:
    ids = [g.id for g in groups]
    if not ids:
        return []
    n_lp = dict(db.execute(select(Page.group_id, func.count()).where(
        Page.group_id.in_(ids), Page.doc_type.in_(labels.SUPPORTED_DOC_TYPES)).group_by(Page.group_id)).all())
    emails = dict(db.execute(select(User.id, User.email).where(User.id.in_({g.user_id for g in groups}))).all())
    reviewed = set(db.execute(select(Page.group_id).join(SignatureReview, SignatureReview.page_id == Page.id)
                              .where(Page.group_id.in_(ids)).distinct()).scalars().all())
    out = []
    for g in groups:
        eff = None
        if g.id in reviewed and g.status == GROUP_DONE:
            latest = review_svc.latest_reviews_for_pages(db, [p.id for p in g.pages])
            eff = _effective_dossiers(db, g, latest)
        out.append(group_summary(g, emails.get(g.user_id), int(n_lp.get(g.id, 0)), eff))
    return out


# ---------------------------------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------------------------------
def _read_uploads(files: Iterable[UploadFile]) -> List[tuple]:
    limit = storage.max_file_bytes()
    out = []
    for i, f in enumerate(files):
        name = f.filename or f"trang {i + 1}"
        data = f.file.read(limit + 1)
        storage.check_file_size(len(data), name)
        out.append((f.filename or "", data))
    return out


@router.post("", status_code=201, dependencies=[Depends(require_csrf_header)])
def create_group(files: Optional[List[UploadFile]] = File(None), title: Optional[str] = Form(None),
                 use_reference: Optional[str] = Form(None), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    files = [f for f in (files or []) if f is not None]
    try:
        storage.check_file_count(len(files))
        uploads = _read_uploads(files)
    except storage.UploadError as e:
        raise api_error(e.status_code, e.code, e.message)
    requested = _parse_bool_form(use_reference)
    if is_admin(user) and requested is not None:
        use_ref, ref_source = requested, "ADMIN_UPLOAD_FLAG"
    else:
        use_ref, ref_source = read_use_reference_default(db), "SETTING_DEFAULT"
    gid = uuid.uuid4()
    try:
        stored = storage.save_group_files(gid, uploads)
    except storage.UploadError as e:
        raise api_error(e.status_code, e.code, e.message)
    try:
        t = (title or "").strip()[:300] or f"Bộ {len(stored)} trang — {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC"
        group = UploadGroup(id=gid, user_id=user.id, title=t, status=GROUP_QUEUED, use_reference=use_ref,
                            n_pages=len(stored))
        db.add(group)
        db.flush()  # Job không có relationship tới UploadGroup ⇒ phải INSERT group trước (FK)
        for s in stored:
            db.add(Page(group_id=gid, scan_index=s.scan_index, original_filename=s.original_filename,
                        stored_filename=s.stored_filename, stored_path=s.stored_path, sha256=s.sha256,
                        mime=s.mime, width=s.width, height=s.height, size_bytes=s.size_bytes))
        db.add(Job(group_id=gid, status=JOB_QUEUED, message="Đang chờ xử lý"))
        db.flush()
        write_audit(db, user.id, "upload_create", "upload_group", str(gid),
                    {"n_pages": len(stored), "use_reference": use_ref, "use_reference_source": ref_source,
                     "sha256": [s.sha256 for s in stored]})
        db.commit()
    except Exception:
        db.rollback()
        storage.remove_group_files(gid)
        raise
    group = db.get(UploadGroup, gid)
    db.refresh(group)
    return group_detail(db, group)


@router.get("")
def list_groups(all: bool = Query(False), limit: int = Query(200, ge=1, le=1000),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(UploadGroup).order_by(UploadGroup.created_at.desc()).limit(limit)
    if not (all and is_admin(user)):
        q = q.where(UploadGroup.user_id == user.id)
    groups = list(db.execute(q).scalars().all())
    return _summaries(db, groups)


@router.get("/{group_id}")
def get_group(group_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return group_detail(db, load_group_for_user(db, group_id, user))


@router.get("/{group_id}/status")
def get_group_status(group_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = load_group_for_user(db, group_id, user)
    return {"status": g.status, "status_label_vi": GROUP_STATUS_VI.get(g.status, g.status), "error": g.error,
            "job": job_out(latest_job(db, g.id))}


@router.post("/{group_id}/rerun", status_code=202, dependencies=[Depends(require_csrf_header)])
def rerun_group(group_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = load_group_for_user(db, group_id, user)
    if g.status not in (GROUP_DONE, GROUP_FAILED):
        raise api_error(409, "GROUP_BUSY", "Bộ upload đang chờ hoặc đang xử lý — chưa chạy lại được.")
    busy = db.execute(select(func.count()).select_from(Job).where(
        Job.group_id == g.id, Job.status.in_((JOB_QUEUED, JOB_RUNNING)))).scalar_one()
    if busy:
        raise api_error(409, "GROUP_BUSY", "Bộ upload đã có job đang chờ/đang chạy.")
    prev_status = g.status
    g.status, g.error, g.finished_at = GROUP_QUEUED, None, None
    db.add(Job(group_id=g.id, status=JOB_QUEUED, message="Đang chờ xử lý (chạy lại)"))
    db.flush()
    write_audit(db, user.id, "rerun", "upload_group", str(g.id),
                {"previous_status": prev_status, "use_reference": bool(g.use_reference)})
    db.commit()
    db.refresh(g)
    return group_detail(db, g)
