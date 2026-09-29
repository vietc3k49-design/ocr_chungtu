"""Schema pydantic cho Auth + Admin (web/SPEC.md §3). Agent AUTH sở hữu."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, StrictBool

from app.models import User


class MessageOut(BaseModel):
    message: str


class RegisterIn(BaseModel):
    email: str
    password: str
    full_name: str = ""


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: str


class LoginIn(BaseModel):
    email: str
    password: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    email_verified: bool
    created_at: Optional[datetime] = None

    @classmethod
    def of(cls, u: User) -> "UserOut":
        return cls(id=str(u.id), email=u.email, full_name=u.full_name or "", role=u.role,
                   is_active=bool(u.is_active), email_verified=u.email_verified_at is not None,
                   created_at=u.created_at)


class AdminUserOut(UserOut):
    last_login_at: Optional[datetime] = None
    # Giới hạn đăng nhập sai (app/services/login_limit.py) — chỉ theo email; khóa theo IP không gắn với user.
    login_locked: bool = False
    login_locked_until: Optional[datetime] = None
    login_recent_fails: int = 0

    @classmethod
    def of(cls, u: User, lock=None) -> "AdminUserOut":  # type: ignore[override]
        base = UserOut.of(u).model_dump()
        extra = {}
        if lock is not None:
            extra = {"login_locked": lock.locked, "login_locked_until": lock.until if lock.locked else None,
                     "login_recent_fails": lock.fails}
        return cls(**base, last_login_at=u.last_login_at, **extra)


class AdminUserPatch(BaseModel):
    role: Optional[str] = None
    is_active: Optional[StrictBool] = None


class SettingsOut(BaseModel):
    use_reference_default: bool


class SettingsIn(BaseModel):
    use_reference_default: StrictBool


class AuditOut(BaseModel):
    id: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    action: str
    entity: str
    entity_id: str
    payload: Optional[Any] = None
    created_at: Optional[datetime] = None
