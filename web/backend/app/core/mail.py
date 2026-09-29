"""Gửi mail hệ thống (smtplib, text + HTML tiếng Việt): xác thực email, đặt lại mật khẩu.

SMTP theo Settings: smtp_host/port/user/password, smtp_starttls, smtp_ssl. Dev dùng Mailpit
(mailpit:1025, không auth, không TLS). `smtp_user` rỗng ⇒ không login.

Dựng nội dung (build_*) tách khỏi gửi (send_email) để test không cần SMTP thật.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Optional
from urllib.parse import quote

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 20
APP_NAME = "KIDO OCR — Kiểm tra chứng từ giao nhận"


class MailError(RuntimeError):
    pass


def build_link(path: str, token: str, settings: Optional[Settings] = None) -> str:
    settings = settings or get_settings()
    base = str(settings.public_base_url).rstrip("/")
    return f"{base}{path}?token={quote(token, safe='')}"


def verification_link(token: str, settings: Optional[Settings] = None) -> str:
    return build_link("/xac-thuc-email", token, settings)


def reset_link(token: str, settings: Optional[Settings] = None) -> str:
    return build_link("/dat-lai-mat-khau", token, settings)


def _greeting(full_name: str) -> str:
    name = (full_name or "").strip()
    return f"Xin chào {name}," if name else "Xin chào,"


def _html_page(title: str, greeting: str, paragraphs: list[str], button_text: str, link: str,
               footer: str) -> str:
    esc = html.escape
    paras = "".join(f'<p style="margin:0 0 14px">{esc(p)}</p>' for p in paragraphs)
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>{esc(title)}</title></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#1f2933">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;padding:28px">
    <h2 style="margin:0 0 18px;font-size:20px">{esc(title)}</h2>
    <p style="margin:0 0 14px">{esc(greeting)}</p>
    {paras}
    <p style="margin:22px 0">
      <a href="{esc(link, quote=True)}" style="display:inline-block;background:#1d4ed8;color:#ffffff;
         text-decoration:none;padding:11px 20px;border-radius:6px;font-weight:bold">{esc(button_text)}</a>
    </p>
    <p style="margin:0 0 14px;font-size:13px;color:#52606d">Nếu nút không hoạt động, sao chép liên kết sau vào trình duyệt:<br>
      <a href="{esc(link, quote=True)}" style="color:#1d4ed8;word-break:break-all">{esc(link)}</a></p>
    <p style="margin:18px 0 0;font-size:12px;color:#7b8794">{esc(footer)}</p>
  </div>
</body></html>"""


def _message(to_email: str, subject: str, text: str, html_body: str,
             settings: Optional[Settings] = None) -> EmailMessage:
    settings = settings or get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.mail_from
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain="kido-ocr.local")
    msg.set_content(text, charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")
    return msg


def build_verification_email(to_email: str, full_name: str, raw_token: str,
                             settings: Optional[Settings] = None) -> EmailMessage:
    settings = settings or get_settings()
    link = verification_link(raw_token, settings)
    hours = max(1, round(settings.email_token_minutes / 60))
    title = "Xác thực địa chỉ email"
    paras = [
        f"Bạn (hoặc ai đó) vừa đăng ký tài khoản {APP_NAME} bằng địa chỉ email này.",
        f"Vui lòng bấm nút bên dưới để xác thực email. Liên kết có hiệu lực trong {hours} giờ và chỉ dùng được một lần.",
    ]
    footer = "Nếu bạn không đăng ký tài khoản, hãy bỏ qua email này — tài khoản sẽ không được kích hoạt."
    text = "\n\n".join([_greeting(full_name), *paras, f"Liên kết xác thực: {link}", footer])
    return _message(to_email, f"[KIDO OCR] {title}", text,
                    _html_page(title, _greeting(full_name), paras, "Xác thực email", link, footer), settings)


def build_password_reset_email(to_email: str, full_name: str, raw_token: str,
                               settings: Optional[Settings] = None) -> EmailMessage:
    settings = settings or get_settings()
    link = reset_link(raw_token, settings)
    minutes = settings.reset_token_minutes
    title = "Đặt lại mật khẩu"
    paras = [
        f"Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản {APP_NAME} gắn với email này.",
        f"Bấm nút bên dưới để đặt mật khẩu mới. Liên kết có hiệu lực trong {minutes} phút và chỉ dùng được một lần.",
    ]
    footer = "Nếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email này — mật khẩu hiện tại vẫn giữ nguyên."
    text = "\n\n".join([_greeting(full_name), *paras, f"Liên kết đặt lại mật khẩu: {link}", footer])
    return _message(to_email, f"[KIDO OCR] {title}", text,
                    _html_page(title, _greeting(full_name), paras, "Đặt mật khẩu mới", link, footer), settings)


def send_email(msg: EmailMessage, settings: Optional[Settings] = None) -> None:
    """Gửi qua SMTP theo Settings. Lỗi ⇒ MailError (người gọi quyết định log/bỏ qua)."""
    settings = settings or get_settings()
    ctx = ssl.create_default_context()
    try:
        if settings.smtp_ssl:
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                      timeout=SMTP_TIMEOUT_SECONDS, context=ctx)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
        with client:
            client.ehlo()
            if settings.smtp_starttls and not settings.smtp_ssl:
                client.starttls(context=ctx)
                client.ehlo()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Gửi mail thất bại tới {msg['To']}: {exc!r}") from exc


def _send_logged(msg: EmailMessage) -> bool:
    try:
        send_email(msg)
        log.info("Đã gửi mail '%s' tới %s", msg["Subject"], msg["To"])
        return True
    except MailError:
        log.exception("Không gửi được mail '%s' tới %s", msg["Subject"], msg["To"])
        return False


def send_verification_email(to_email: str, full_name: str, raw_token: str) -> bool:
    """Dùng làm BackgroundTask: không ném lỗi, trả True/False."""
    return _send_logged(build_verification_email(to_email, full_name, raw_token))


def send_password_reset_email(to_email: str, full_name: str, raw_token: str) -> bool:
    return _send_logged(build_password_reset_email(to_email, full_name, raw_token))
