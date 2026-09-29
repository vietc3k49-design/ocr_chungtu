"""Auth API (web/SPEC.md §2, §3): đăng ký, xác thực email, đăng nhập/đăng xuất, quên/đặt lại/đổi mật khẩu.

Router prefix "/auth" — main.py gắn dưới "/api".
Nguyên tắc:
  * email lưu lower().strip().
  * register / resend-verification / forgot-password trả lời TRUNG TÍNH (không lộ email đã tồn tại);
    mail gửi bằng BackgroundTasks để thời gian phản hồi không lộ thông tin.
  * Login: sai mật khẩu / không có email ⇒ 401 INVALID_CREDENTIALS + audit login_fail;
    đúng mật khẩu nhưng khóa ⇒ 403 USER_INACTIVE; chưa xác thực ⇒ 403 EMAIL_NOT_VERIFIED.
  * Giới hạn đăng nhập sai (app/services/login_limit.py): quá ngưỡng theo email hoặc IP ⇒ 429
    TOO_MANY_ATTEMPTS + Retry-After, kiểm TRƯỚC mật khẩu; áp cả email không tồn tại.
  * Token mail dùng 1 lần (used_at), có hạn; phát token mới cùng purpose ⇒ XÓA token cũ chưa dùng.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import api_error, get_current_user, get_db, get_optional_user, write_audit
from app.core import mail, security
from app.core.config import get_settings
from app.models import LOGIN_FAIL, LOGIN_LOCKED, LOGIN_SUCCESS, ROLE_USER, TOKEN_RESET_PASSWORD, TOKEN_VERIFY_EMAIL, EmailToken, User
from app.services import login_limit
from app.schemas_auth import (
    ChangePasswordIn, EmailIn, LoginIn, MessageOut, RegisterIn, ResetPasswordIn, TokenIn, UserOut,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Chống spam mail: trong khoảng này sau lần phát token trước (cùng user + purpose) thì không phát/gửi lại.
# Vẫn trả thông báo trung tính. Test có thể đặt về 0.
MAIL_RESEND_COOLDOWN_SECONDS = 60

MAX_EMAIL_LENGTH = 320
MAX_FULL_NAME_LENGTH = 200
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")

MSG_REGISTER = ("Đã ghi nhận đăng ký. Vui lòng kiểm tra hộp thư (kể cả thư rác) và bấm liên kết xác thực "
                "trước khi đăng nhập. Nếu email này đã có tài khoản, hãy đăng nhập hoặc dùng chức năng Quên mật khẩu.")
MSG_RESEND = ("Nếu email này thuộc một tài khoản chưa xác thực, chúng tôi đã gửi lại liên kết xác thực. "
              "Vui lòng kiểm tra hộp thư (kể cả thư rác).")
MSG_FORGOT = ("Nếu email này thuộc một tài khoản đang hoạt động, chúng tôi đã gửi liên kết đặt lại mật khẩu. "
              "Vui lòng kiểm tra hộp thư (kể cả thư rác).")


# ---------------------------------------------------------------- tiện ích
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """DB có thể trả datetime naive (vd SQLite) ⇒ coi là UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def normalize_email(email: object) -> str:
    return email.strip().lower() if isinstance(email, str) else ""


def validate_email_or_422(email: str) -> None:
    if not email or len(email) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(email):
        raise api_error(422, "INVALID_EMAIL", "Địa chỉ email không hợp lệ.")


def validate_password_or_422(password: object) -> None:
    problem = security.password_problem(password)
    if problem:
        raise api_error(422, problem[0], problem[1])


def find_user_by_email(db: Session, email: str) -> Optional[User]:
    if not email:
        return None
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def set_session_cookie(response: Response, user: User) -> None:
    s = get_settings()
    token = security.create_access_token(user.id, user.password_hash)
    response.set_cookie(
        key=s.cookie_name, value=token, max_age=s.access_token_minutes * 60,
        httponly=True, samesite="lax", secure=s.cookie_secure, path="/",
    )


def clear_session_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(key=s.cookie_name, path="/", httponly=True, samesite="lax", secure=s.cookie_secure)


def _recent_token_exists(db: Session, user: User, purpose: str) -> bool:
    if MAIL_RESEND_COOLDOWN_SECONDS <= 0:
        return False
    last = db.execute(
        select(EmailToken.created_at).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose)
        .order_by(EmailToken.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    last = as_utc(last)
    return last is not None and utcnow() - last < timedelta(seconds=MAIL_RESEND_COOLDOWN_SECONDS)


def issue_mail_token(db: Session, user: User, purpose: str) -> str:
    """Xóa token cũ CHƯA DÙNG cùng purpose rồi phát token mới. Trả token thô (chỉ để gửi mail)."""
    s = get_settings()
    minutes = s.email_token_minutes if purpose == TOKEN_VERIFY_EMAIL else s.reset_token_minutes
    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose,
                                        EmailToken.used_at.is_(None)))
    raw, token_hash = security.new_mail_token()
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=token_hash,
                      expires_at=utcnow() + timedelta(minutes=minutes)))
    return raw


def consume_mail_token(db: Session, raw_token: object, purpose: str) -> tuple[EmailToken, User]:
    """Kiểm + đánh dấu đã dùng (chưa commit). Lỗi ⇒ 400 INVALID_TOKEN / TOKEN_USED / TOKEN_EXPIRED."""
    if not isinstance(raw_token, str) or not raw_token.strip() or len(raw_token) > 200:
        raise api_error(400, "INVALID_TOKEN", "Liên kết không hợp lệ hoặc đã được thay bằng liên kết mới hơn.")
    row = db.execute(
        select(EmailToken).where(EmailToken.token_hash == security.hash_token(raw_token.strip()))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.purpose != purpose:
        raise api_error(400, "INVALID_TOKEN", "Liên kết không hợp lệ hoặc đã được thay bằng liên kết mới hơn.")
    if row.used_at is not None:
        raise api_error(400, "TOKEN_USED", "Liên kết này đã được sử dụng.")
    if as_utc(row.expires_at) <= utcnow():
        raise api_error(400, "TOKEN_EXPIRED", "Liên kết đã hết hạn. Vui lòng yêu cầu gửi lại liên kết mới.")
    user = db.get(User, row.user_id)
    if user is None:
        raise api_error(400, "INVALID_TOKEN", "Liên kết không hợp lệ hoặc đã được thay bằng liên kết mới hơn.")
    row.used_at = utcnow()
    return row, user


# ---------------------------------------------------------------- endpoint
@router.post("/register", status_code=201, response_model=MessageOut)
def register(body: RegisterIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> MessageOut:
    email = normalize_email(body.email)
    validate_email_or_422(email)
    validate_password_or_422(body.password)
    full_name = (body.full_name or "").strip()
    if not full_name or len(full_name) > MAX_FULL_NAME_LENGTH:
        raise api_error(422, "INVALID_FULL_NAME", f"Họ tên không được để trống và tối đa {MAX_FULL_NAME_LENGTH} ký tự.")

    existing = find_user_by_email(db, email)
    if existing is not None:
        # Trung tính: không báo "email đã tồn tại". Tài khoản chưa xác thực ⇒ gửi lại mail xác thực.
        # KHÔNG bao giờ đổi mật khẩu / họ tên của tài khoản có sẵn.
        resent = False
        if existing.is_active and existing.email_verified_at is None and not _recent_token_exists(
                db, existing, TOKEN_VERIFY_EMAIL):
            raw = issue_mail_token(db, existing, TOKEN_VERIFY_EMAIL)
            background.add_task(mail.send_verification_email, existing.email, existing.full_name, raw)
            resent = True
        write_audit(db, None, "register_duplicate", "user", existing.id, {"email": email, "resent": resent})
        db.commit()
        return MessageOut(message=MSG_REGISTER)

    user = User(email=email, password_hash=security.hash_password(body.password), full_name=full_name,
                role=ROLE_USER, is_active=True, email_verified_at=None)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # đăng ký đồng thời cùng email
        db.rollback()
        return MessageOut(message=MSG_REGISTER)
    raw = issue_mail_token(db, user, TOKEN_VERIFY_EMAIL)
    write_audit(db, user.id, "register", "user", user.id, {"email": email})
    db.commit()
    background.add_task(mail.send_verification_email, user.email, user.full_name, raw)
    return MessageOut(message=MSG_REGISTER)


@router.post("/verify-email", response_model=MessageOut)
def verify_email(body: TokenIn, db: Session = Depends(get_db)) -> MessageOut:
    _, user = consume_mail_token(db, body.token, TOKEN_VERIFY_EMAIL)
    already = user.email_verified_at is not None
    if not already:
        user.email_verified_at = utcnow()
    write_audit(db, user.id, "verify_email", "user", user.id, {"already_verified": already})
    db.commit()
    return MessageOut(message="Xác thực email thành công. Bạn có thể đăng nhập.")


@router.post("/resend-verification", response_model=MessageOut)
def resend_verification(body: EmailIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> MessageOut:
    user = find_user_by_email(db, normalize_email(body.email))
    if (user is not None and user.is_active and user.email_verified_at is None
            and not _recent_token_exists(db, user, TOKEN_VERIFY_EMAIL)):
        raw = issue_mail_token(db, user, TOKEN_VERIFY_EMAIL)
        db.commit()
        background.add_task(mail.send_verification_email, user.email, user.full_name, raw)
    return MessageOut(message=MSG_RESEND)


def _locked_error(state: "login_limit.LockState"):
    minutes = max(1, -(-state.retry_after_seconds // 60))
    who = "địa chỉ mạng này" if state.scope == "ip" else "tài khoản này"
    exc = api_error(429, "TOO_MANY_ATTEMPTS",
                    f"Đăng nhập sai quá nhiều lần — tạm khóa đăng nhập cho {who}. "
                    f"Vui lòng thử lại sau khoảng {minutes} phút, hoặc dùng chức năng Quên mật khẩu.",
                    retry_after_seconds=state.retry_after_seconds)
    exc.headers = {"Retry-After": str(state.retry_after_seconds)}
    return exc


def _fail(db: Session, email: str, ip: str, user_id, reason: str):
    login_limit.record(db, email, ip, LOGIN_FAIL)
    write_audit(db, user_id, "login_fail", "user", user_id or "", {"email": email, "reason": reason, "ip": ip})
    db.commit()
    return api_error(401, "INVALID_CREDENTIALS", "Email hoặc mật khẩu không đúng.")


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> UserOut:
    raw_email = normalize_email(body.email)
    email = raw_email[:MAX_EMAIL_LENGTH]           # khóa đếm theo bản cắt; tra user chỉ khi không bị cắt
    password = body.password if isinstance(body.password, str) else ""
    ip = login_limit.client_ip(request)

    # Kiểm khóa TRƯỚC mọi thứ: đang khóa thì đúng mật khẩu cũng bị từ chối (áp cả email không tồn tại).
    state = login_limit.check(db, email, ip)
    if state.locked:
        login_limit.record(db, email, ip, LOGIN_LOCKED)
        write_audit(db, None, "login_locked", "user", "", {"email": email, "ip": ip, "scope": state.scope,
                                                             "until": state.until.isoformat()})
        db.commit()
        raise _locked_error(state)

    user = find_user_by_email(db, raw_email) if len(raw_email) <= MAX_EMAIL_LENGTH else None
    too_long = len(password) > security.MAX_PASSWORD_LENGTH

    if user is None:
        if not too_long:
            security.dummy_verify(password)
        raise _fail(db, email, ip, None, "unknown_email")
    if too_long or not security.verify_password(password, user.password_hash):
        raise _fail(db, email, ip, user.id, "bad_password")
    # Từ đây mật khẩu ĐÚNG: không đếm là "sai".
    if not user.is_active:
        write_audit(db, user.id, "login_fail", "user", user.id, {"email": email, "reason": "inactive"}, commit=True)
        raise api_error(403, "USER_INACTIVE", "Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.")
    if user.email_verified_at is None:
        write_audit(db, user.id, "login_fail", "user", user.id, {"email": email, "reason": "email_not_verified"},
                    commit=True)
        raise api_error(403, "EMAIL_NOT_VERIFIED",
                        "Email chưa được xác thực. Vui lòng bấm liên kết trong thư xác thực hoặc yêu cầu gửi lại.")

    if security.password_needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    user.last_login_at = utcnow()
    login_limit.record(db, email, ip, LOGIN_SUCCESS)   # mốc đặt lại bộ đếm theo email
    login_limit.purge_old(db)
    write_audit(db, user.id, "login_ok", "user", user.id, {"email": email})
    db.commit()
    set_session_cookie(response, user)
    return UserOut.of(user)


@router.post("/logout", response_model=MessageOut)
def logout(response: Response, db: Session = Depends(get_db),
           user: Optional[User] = Depends(get_optional_user)) -> MessageOut:
    if user is not None:
        write_audit(db, user.id, "logout", "user", user.id, None, commit=True)
    clear_session_cookie(response)
    return MessageOut(message="Đã đăng xuất.")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.of(user)


@router.post("/forgot-password", response_model=MessageOut)
def forgot_password(body: EmailIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> MessageOut:
    user = find_user_by_email(db, normalize_email(body.email))
    if user is not None and user.is_active and not _recent_token_exists(db, user, TOKEN_RESET_PASSWORD):
        raw = issue_mail_token(db, user, TOKEN_RESET_PASSWORD)
        db.commit()
        background.add_task(mail.send_password_reset_email, user.email, user.full_name, raw)
    return MessageOut(message=MSG_FORGOT)


@router.post("/reset-password", response_model=MessageOut)
def reset_password(body: ResetPasswordIn, db: Session = Depends(get_db)) -> MessageOut:
    validate_password_or_422(body.new_password)
    token_row, user = consume_mail_token(db, body.token, TOKEN_RESET_PASSWORD)
    if not user.is_active:
        # Token vẫn bị tiêu (used_at) để không dùng lại được.
        db.commit()
        raise api_error(403, "USER_INACTIVE", "Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.")
    user.password_hash = security.hash_password(body.new_password)   # đổi hash ⇒ mọi phiên cũ hết hiệu lực
    # Bấm được liên kết gửi tới hộp thư = chứng minh sở hữu email, tương đương xác thực email.
    verified_now = user.email_verified_at is None
    if verified_now:
        user.email_verified_at = utcnow()
    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == TOKEN_RESET_PASSWORD,
                                        EmailToken.used_at.is_(None), EmailToken.id != token_row.id))
    login_limit.reset_email(db, user.email)   # đặt lại mật khẩu qua mail ⇒ mở khóa đăng nhập theo email
    write_audit(db, user.id, "password_reset", "user", user.id, {"email_verified_via_reset": verified_now})
    db.commit()
    return MessageOut(message="Đặt lại mật khẩu thành công. Vui lòng đăng nhập bằng mật khẩu mới.")


@router.post("/change-password", response_model=MessageOut)
def change_password(body: ChangePasswordIn, response: Response, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> MessageOut:
    old_ok = (isinstance(body.old_password, str) and len(body.old_password) <= security.MAX_PASSWORD_LENGTH
              and security.verify_password(body.old_password, user.password_hash))
    if not old_ok:
        # 400 (không phải 401) để frontend không hiểu nhầm là mất phiên.
        raise api_error(400, "INVALID_OLD_PASSWORD", "Mật khẩu hiện tại không đúng.")
    validate_password_or_422(body.new_password)
    user.password_hash = security.hash_password(body.new_password)
    write_audit(db, user.id, "password_change", "user", user.id, None)
    db.commit()
    set_session_cookie(response, user)   # phiên hiện tại được cấp lại; các phiên khác hết hiệu lực
    return MessageOut(message="Đổi mật khẩu thành công.")
