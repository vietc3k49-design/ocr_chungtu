"""Dependency dùng chung cho mọi router (Agent AUTH sở hữu; Agent JOBS import từ đây).

Export:
  get_db                 — re-export app.core.db.get_db (override trong test qua app.dependency_overrides[get_db])
  get_current_user       — đọc cookie `settings.cookie_name`; 401 NOT_AUTHENTICATED; 403 USER_INACTIVE / EMAIL_NOT_VERIFIED
  require_admin          — 403 FORBIDDEN nếu không phải admin
  require_csrf_header    — POST/PUT/PATCH/DELETE phải có `X-Requested-With: kido`, không thì 403 CSRF
                           (main.py gắn ở cấp app ⇒ áp cho MỌI router, kể cả groups/pages)
  api_error              — dựng HTTPException với detail {"code","message"}
  write_audit            — thêm 1 dòng audit_log (KHÔNG commit, trừ khi commit=True)
  read_use_reference_default — đọc setting `use_reference_default` (mặc định False nếu chưa có dòng)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.db import get_db  # noqa: F401  (re-export)
from app.models import ROLE_ADMIN, SETTING_USE_REFERENCE_DEFAULT, AppSetting, AuditLog, User

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "kido"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

__all__ = [
    "get_db", "get_current_user", "get_optional_user", "require_admin", "require_csrf_header",
    "api_error", "write_audit", "read_use_reference_default", "CSRF_HEADER", "CSRF_VALUE",
]


def api_error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


# ---------------------------------------------------------------- CSRF
def require_csrf_header(request: Request) -> None:
    if request.method.upper() in _UNSAFE_METHODS:
        if request.headers.get(CSRF_HEADER, "").strip().lower() != CSRF_VALUE:
            raise api_error(403, "CSRF", "Yêu cầu bị từ chối: thiếu header bảo vệ X-Requested-With.")


# ---------------------------------------------------------------- người dùng hiện tại
def _user_from_cookie(request: Request, db: Session) -> Optional[User]:
    """User khớp cookie phiên (chữ ký, hạn, dấu vân tay mật khẩu), hoặc None. Không kiểm active/verified."""
    token = request.cookies.get(get_settings().cookie_name)
    payload = security.decode_access_token(token) if token else None
    if payload is None:
        return None
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not security.token_matches_password(payload, user.password_hash):
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _user_from_cookie(request, db)
    if user is None:
        raise api_error(401, "NOT_AUTHENTICATED", "Bạn chưa đăng nhập hoặc phiên đăng nhập đã hết hạn.")
    if not user.is_active:
        raise api_error(403, "USER_INACTIVE", "Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.")
    if user.email_verified_at is None:
        raise api_error(403, "EMAIL_NOT_VERIFIED", "Email chưa được xác thực. Vui lòng kiểm tra hộp thư.")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """User hợp lệ (active + verified) hoặc None — không ném lỗi (dùng cho logout)."""
    user = _user_from_cookie(request, db)
    if user is None or not user.is_active or user.email_verified_at is None:
        return None
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise api_error(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này.")
    return user


# ---------------------------------------------------------------- audit
def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def write_audit(db: Session, actor_id: Optional[uuid.UUID | str], action: str, entity: str = "",
                entity_id: Any = "", payload: Optional[dict] = None, *, commit: bool = False) -> AuditLog:
    """Thêm 1 dòng audit_log vào session. Mặc định KHÔNG commit — người gọi commit cùng giao dịch."""
    if isinstance(actor_id, str):
        actor_id = uuid.UUID(actor_id)
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        entity=entity or "",
        entity_id=str(entity_id) if entity_id is not None else "",
        payload=_jsonable(payload) if payload is not None else None,
    )
    db.add(row)
    if commit:
        db.commit()
    return row


# ---------------------------------------------------------------- settings
def read_use_reference_default(db: Session) -> bool:
    """Setting `use_reference_default`; chưa có dòng ⇒ False. Giá trị không phải bool thật ⇒ False (không đoán)."""
    row = db.get(AppSetting, SETTING_USE_REFERENCE_DEFAULT)
    return bool(row is not None and row.value is True)
