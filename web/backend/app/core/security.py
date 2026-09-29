"""Bảo mật: băm mật khẩu (argon2), JWT phiên (HS256, PyJWT), token mail (token_urlsafe + sha256).

Hợp đồng (web/SPEC.md §2):
  * Mật khẩu tối thiểu MIN_PASSWORD_LENGTH ký tự, băm argon2id (`argon2-cffi`, tham số mặc định thư viện).
  * JWT chứa `sub` = user_id, `exp`, `iat`, cộng claim `pwd` = dấu vân tay của password_hash
    ⇒ đổi / đặt lại mật khẩu làm MỌI phiên cũ hết hiệu lực mà không cần thêm cột DB.
  * Token mail: `secrets.token_urlsafe(32)` gửi cho người dùng; DB chỉ lưu sha256 hex (64 ký tự).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

log = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256          # chặn DoS bằng chuỗi cực dài
JWT_ALGORITHM = "HS256"
JWT_TYPE_SESSION = "session"
MIN_SECRET_KEY_BYTES = 32          # khuyến nghị cho HS256 (RFC 7518 §3.2)

_hasher = PasswordHasher()


# ---------------------------------------------------------------- mật khẩu
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True nếu đúng. Hash hỏng / sai định dạng ⇒ False (không ném lỗi ra ngoài)."""
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        log.warning("password_hash không hợp lệ / không kiểm được")
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:  # hash lạ ⇒ để nguyên, verify đã quyết định
        return False


_DUMMY_HASH: Optional[str] = None


def dummy_verify(password: str) -> None:
    """Chạy verify giả khi email không tồn tại để thời gian phản hồi login gần như nhau."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(password, _DUMMY_HASH)


def password_problem(password: object) -> Optional[tuple[str, str]]:
    """Trả (code, message tiếng Việt) nếu mật khẩu không đạt, None nếu đạt."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return ("PASSWORD_TOO_SHORT", f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")
    if len(password) > MAX_PASSWORD_LENGTH:
        return ("PASSWORD_TOO_LONG", f"Mật khẩu không được dài quá {MAX_PASSWORD_LENGTH} ký tự.")
    return None


# ---------------------------------------------------------------- JWT phiên
def password_fingerprint(password_hash: str) -> str:
    """Dấu vân tay ngắn của password_hash (không lộ hash) — đổi mật khẩu ⇒ đổi dấu vân tay."""
    return hashlib.sha256(("pwd:" + (password_hash or "")).encode("utf-8")).hexdigest()[:24]


def _secret() -> str:
    key = get_settings().secret_key
    if not key:
        raise RuntimeError("SECRET_KEY rỗng — không thể ký JWT")
    return key


def secret_key_is_weak() -> bool:
    return len(get_settings().secret_key.encode("utf-8")) < MIN_SECRET_KEY_BYTES


def create_access_token(user_id: uuid.UUID | str, password_hash: str,
                        minutes: Optional[int] = None, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    minutes = get_settings().access_token_minutes if minutes is None else minutes
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "typ": JWT_TYPE_SESSION,
        "pwd": password_fingerprint(password_hash),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Trả payload nếu chữ ký + hạn + loại hợp lệ, ngược lại None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM],
                             options={"require": ["exp", "sub", "iat"]})
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != JWT_TYPE_SESSION:
        return None
    try:
        uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        return None
    return payload


def token_matches_password(payload: dict, password_hash: str) -> bool:
    return hmac.compare_digest(str(payload.get("pwd", "")), password_fingerprint(password_hash))


# ---------------------------------------------------------------- token mail
def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_mail_token() -> tuple[str, str]:
    """(token thô gửi cho người dùng, sha256 hex lưu DB)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)
