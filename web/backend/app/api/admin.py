"""Admin API (web/SPEC.md §3): quản lý người dùng, setting, nhật ký. Router prefix "/admin", mọi route require_admin.

Luật an toàn:
  * Admin không tự hạ quyền / tự khóa chính mình ⇒ 409 CANNOT_MODIFY_SELF.
  * Luôn còn ≥ 1 admin "dùng được" (role=admin, is_active, đã xác thực email) ⇒ 409 LAST_ADMIN.
  * POST /users/{id}/unlock-login: mở khóa giới hạn đăng nhập sai theo email (ghi mốc reset + audit).
  * Setting `use_reference_default` (models.SETTING_USE_REFERENCE_DEFAULT) mặc định False khi chưa có dòng;
    PUT ghi audit `setting_change` kèm giá trị cũ / mới.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.services import login_limit
from app.api.deps import api_error, get_db, read_use_reference_default, require_admin, write_audit
from app.models import ROLE_ADMIN, ROLE_USER, SETTING_USE_REFERENCE_DEFAULT, AppSetting, AuditLog, User
from app.schemas_auth import AdminUserOut, AdminUserPatch, AuditOut, SettingsIn, SettingsOut

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

VALID_ROLES = (ROLE_ADMIN, ROLE_USER)


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/users", response_model=list[AdminUserOut])
def list_users(q: Optional[str] = Query(None, max_length=320), db: Session = Depends(get_db)) -> list[AdminUserOut]:
    stmt = select(User)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(or_(User.email.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\")))
    rows = db.execute(stmt.order_by(User.created_at.asc(), User.email.asc())).scalars().all()
    return [AdminUserOut.of(u, login_limit.email_state(db, u.email)) for u in rows]


def _usable_admin_count(db: Session, exclude_id: Optional[uuid.UUID] = None) -> int:
    # Khóa các dòng admin để hai thao tác đồng thời không cùng hạ 2 admin cuối (Postgres; SQLite bỏ qua).
    stmt = select(User.id).where(User.role == ROLE_ADMIN, User.is_active.is_(True),
                                 User.email_verified_at.is_not(None)).with_for_update()
    ids = db.execute(stmt).scalars().all()
    return sum(1 for i in ids if i != exclude_id)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def patch_user(user_id: str, body: AdminUserPatch, db: Session = Depends(get_db),
               actor: User = Depends(require_admin)) -> AdminUserOut:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise api_error(404, "USER_NOT_FOUND", "Không tìm thấy người dùng.")
    if body.role is None and body.is_active is None:
        raise api_error(422, "NO_CHANGES", "Không có thay đổi nào (cần role hoặc is_active).")
    if body.role is not None and body.role not in VALID_ROLES:
        raise api_error(422, "INVALID_ROLE", "Vai trò không hợp lệ (chỉ 'admin' hoặc 'user').")

    target = db.get(User, uid, with_for_update=True)
    if target is None:
        raise api_error(404, "USER_NOT_FOUND", "Không tìm thấy người dùng.")

    new_role = body.role if body.role is not None else target.role
    new_active = body.is_active if body.is_active is not None else target.is_active
    role_changed = new_role != target.role
    active_changed = new_active != target.is_active
    if not role_changed and not active_changed:
        return AdminUserOut.of(target, login_limit.email_state(db, target.email))

    if target.id == actor.id and (new_role != ROLE_ADMIN or not new_active):
        raise api_error(409, "CANNOT_MODIFY_SELF", "Bạn không thể tự hạ quyền hoặc tự khóa tài khoản của chính mình.")

    was_usable_admin = (target.role == ROLE_ADMIN and target.is_active and target.email_verified_at is not None)
    stays_usable_admin = (new_role == ROLE_ADMIN and new_active and target.email_verified_at is not None)
    if was_usable_admin and not stays_usable_admin and _usable_admin_count(db, exclude_id=target.id) < 1:
        raise api_error(409, "LAST_ADMIN", "Phải luôn còn ít nhất một quản trị viên đang hoạt động.")

    if role_changed:
        write_audit(db, actor.id, "role_change", "user", target.id,
                    {"email": target.email, "old": target.role, "new": new_role})
        target.role = new_role
    if active_changed:
        write_audit(db, actor.id, "active_change", "user", target.id,
                    {"email": target.email, "old": target.is_active, "new": new_active})
        target.is_active = new_active
    db.commit()
    return AdminUserOut.of(target, login_limit.email_state(db, target.email))


@router.post("/users/{user_id}/unlock-login", response_model=AdminUserOut)
def unlock_login(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> AdminUserOut:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise api_error(404, "USER_NOT_FOUND", "Không tìm thấy người dùng.")
    user = db.get(User, uid)
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "Không tìm thấy người dùng.")
    before = login_limit.email_state(db, user.email)
    login_limit.reset_email(db, user.email)
    write_audit(db, actor.id, "login_unlock", "user", user.id,
                {"email": user.email, "was_locked": before.locked, "recent_fails": before.fails})
    db.commit()
    return AdminUserOut.of(user, login_limit.email_state(db, user.email))


@router.get("/settings", response_model=SettingsOut)
def get_app_settings(db: Session = Depends(get_db)) -> SettingsOut:
    return SettingsOut(use_reference_default=read_use_reference_default(db))


@router.put("/settings", response_model=SettingsOut)
def put_app_settings(body: SettingsIn, db: Session = Depends(get_db),
                     actor: User = Depends(require_admin)) -> SettingsOut:
    row = db.get(AppSetting, SETTING_USE_REFERENCE_DEFAULT, with_for_update=True)
    old_effective = bool(row is not None and row.value is True)
    row_existed = row is not None
    old_raw = row.value if row is not None else None
    new_value = bool(body.use_reference_default)
    if row is None:
        row = AppSetting(key=SETTING_USE_REFERENCE_DEFAULT, value=new_value, updated_by=actor.id)
        db.add(row)
    else:
        row.value = new_value
        row.updated_by = actor.id
    write_audit(db, actor.id, "setting_change", "app_setting", SETTING_USE_REFERENCE_DEFAULT,
                {"key": SETTING_USE_REFERENCE_DEFAULT, "old": old_effective, "old_raw": old_raw,
                 "row_existed": row_existed, "new": new_value})
    db.commit()
    return SettingsOut(use_reference_default=new_value)


@router.get("/audit", response_model=list[AuditOut])
def list_audit(limit: int = Query(200, ge=1, le=1000), action: Optional[str] = Query(None, max_length=60),
               db: Session = Depends(get_db)) -> list[AuditOut]:
    stmt = select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)).all()
    return [
        AuditOut(id=str(a.id), actor_id=str(a.actor_id) if a.actor_id else None, actor_email=email,
                 action=a.action, entity=a.entity or "", entity_id=a.entity_id or "", payload=a.payload,
                 created_at=a.created_at)
        for a, email in rows
    ]

