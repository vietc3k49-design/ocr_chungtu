"""Giới hạn số lần đăng nhập sai — lưu ở bảng `login_attempts` (không phải bộ nhớ):
khóa còn hiệu lực qua restart api và dùng chung giữa nhiều tiến trình.

Luật (tham số trong Settings):
  * Theo EMAIL: ≥ `login_max_fails_per_email` lần sai trong `login_window_minutes`, tính từ sau mốc
    đặt lại gần nhất (đăng nhập thành công / đặt lại mật khẩu / admin mở khóa) ⇒ khóa tới
    lần sai gần nhất + `login_lockout_minutes`. Áp CẢ cho email không tồn tại ⇒ không lộ email có tài khoản.
  * Theo IP: ≥ `login_max_fails_per_ip` lần sai (mọi email) trong cửa sổ ⇒ chặn IP tới lần sai gần nhất
    + `login_lockout_minutes`. Chống dò nhiều email từ một máy. Thành công KHÔNG đặt lại bộ đếm IP
    (kẻ tấn công có 1 tài khoản thật không thể tự "rửa" bộ đếm).
  * Kiểm khóa TRƯỚC khi kiểm mật khẩu ⇒ trong lúc khóa, đúng mật khẩu cũng bị từ chối.
  * Chỉ "fail" được đếm; "locked" (bị từ chối do đang khóa) chỉ để kiểm toán, không kéo dài khóa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LOGIN_FAIL, LOGIN_RESET, LOGIN_SUCCESS, LoginAttempt

MAX_IP_LENGTH = 64


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def client_ip(request: Request) -> str:
    s = get_settings()
    ip = ""
    if s.trust_proxy_headers:
        ip = (request.headers.get("x-real-ip") or "").strip()
    if not ip and request.client is not None:
        ip = request.client.host or ""
    return ip[:MAX_IP_LENGTH]


@dataclass
class LockState:
    locked: bool
    scope: Optional[str] = None            # "email" | "ip"
    until: Optional[datetime] = None
    fails: int = 0                         # số lần sai theo email đang được tính

    @property
    def retry_after_seconds(self) -> int:
        if not self.until:
            return 0
        return max(1, math.ceil((self.until - _utcnow()).total_seconds()))


def _last_reset(db: Session, email: str) -> Optional[datetime]:
    return _as_utc(db.execute(
        select(func.max(LoginAttempt.created_at))
        .where(LoginAttempt.email == email, LoginAttempt.kind.in_((LOGIN_SUCCESS, LOGIN_RESET)))
    ).scalar())


def _fails(db: Session, since: datetime, email: Optional[str] = None, ip: Optional[str] = None):
    q = select(func.count(), func.max(LoginAttempt.created_at)).where(
        LoginAttempt.kind == LOGIN_FAIL, LoginAttempt.created_at > since)
    if email is not None:
        q = q.where(LoginAttempt.email == email)
    if ip is not None:
        q = q.where(LoginAttempt.ip == ip)
    n, last = db.execute(q).one()
    return int(n or 0), _as_utc(last)


def email_state(db: Session, email: str, now: Optional[datetime] = None) -> LockState:
    s = get_settings()
    now = now or _utcnow()
    since = now - timedelta(minutes=s.login_window_minutes)
    reset = _last_reset(db, email)
    if reset and reset > since:
        since = reset
    n, last = _fails(db, since, email=email)
    if n >= s.login_max_fails_per_email and last is not None:
        until = last + timedelta(minutes=s.login_lockout_minutes)
        if until > now:
            return LockState(True, "email", until, n)
    return LockState(False, fails=n)


def ip_state(db: Session, ip: str, now: Optional[datetime] = None) -> LockState:
    s = get_settings()
    if not ip:
        return LockState(False)
    now = now or _utcnow()
    n, last = _fails(db, now - timedelta(minutes=s.login_window_minutes), ip=ip)
    if n >= s.login_max_fails_per_ip and last is not None:
        until = last + timedelta(minutes=s.login_lockout_minutes)
        if until > now:
            return LockState(True, "ip", until)
    return LockState(False)


def check(db: Session, email: str, ip: str) -> LockState:
    """Trạng thái khóa hiện hành (email ưu tiên báo trước; lấy thời điểm mở muộn hơn nếu cả hai)."""
    e, i = email_state(db, email), ip_state(db, ip)
    if e.locked and i.locked:
        return e if e.until >= i.until else i
    return e if e.locked else i


def record(db: Session, email: str, ip: str, kind: str) -> None:
    """Ghi một dòng (không commit — caller commit cùng audit)."""
    db.add(LoginAttempt(email=email[:320], ip=ip[:MAX_IP_LENGTH], kind=kind, created_at=_utcnow()))


def reset_email(db: Session, email: str, ip: str = "") -> None:
    """Mốc đặt lại bộ đếm theo email (đặt lại mật khẩu / admin mở khóa). Không commit."""
    record(db, email, ip, LOGIN_RESET)


def purge_old(db: Session) -> int:
    """Xóa bản ghi quá hạn lưu. Không commit."""
    cutoff = _utcnow() - timedelta(days=get_settings().login_attempts_retention_days)
    return db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff)).rowcount or 0
