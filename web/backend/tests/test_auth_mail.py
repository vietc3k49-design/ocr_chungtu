"""Lớp (a) — unit, KHÔNG cần DB/SMTP thật: app.core.mail (dựng nội dung + gửi qua smtplib giả)."""
from __future__ import annotations

import os
import smtplib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "test")

import pytest  # noqa: E402

from app.core import mail  # noqa: E402
from app.core.config import Settings  # noqa: E402


def _settings(**kw) -> Settings:
    base = dict(secret_key="test", public_base_url="https://ocr.kido.example/", smtp_host="smtp.example",
                smtp_port=2525, mail_from="KIDO OCR <no-reply@kido.example>")
    base.update(kw)
    return Settings(**base)


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[tuple] = []
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.calls.append(("quit",))

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send",))
        self.sent.append(msg)


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTPSSL)


def _parts(msg):
    text = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    return text, html


def test_verification_email_content_vi():
    s = _settings(email_token_minutes=1440)
    msg = mail.build_verification_email("an@kido.example", "Nguyễn Văn An", "TOKEN_abc-123", s)
    assert msg["To"] == "an@kido.example"
    assert msg["From"] == "KIDO OCR <no-reply@kido.example>"
    assert "Xác thực địa chỉ email" in str(msg["Subject"])
    text, html = _parts(msg)
    link = "https://ocr.kido.example/xac-thuc-email?token=TOKEN_abc-123"
    assert link in text and link in html
    assert "Xin chào Nguyễn Văn An," in text
    assert "24 giờ" in text and "một lần" in text
    assert html.lstrip().startswith("<!doctype html>") and 'lang="vi"' in html


def test_reset_email_content_and_escaping():
    s = _settings(reset_token_minutes=60)
    msg = mail.build_password_reset_email("b@kido.example", "<script>x</script>", "tok", s)
    text, html = _parts(msg)
    assert "https://ocr.kido.example/dat-lai-mat-khau?token=tok" in text
    assert "60 phút" in text
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Đặt lại mật khẩu" in str(msg["Subject"])


def test_token_is_url_quoted():
    assert mail.verification_link("a b&c", _settings()).endswith("?token=a%20b%26c")


def test_send_plain_no_auth_like_mailpit():
    s = _settings(smtp_user="", smtp_starttls=False, smtp_ssl=False)
    msg = mail.build_verification_email("a@kido.example", "", "t", s)
    mail.send_email(msg, s)
    (c,) = FakeSMTP.instances
    assert type(c) is FakeSMTP and (c.host, c.port) == ("smtp.example", 2525)
    assert ("starttls",) not in c.calls and not any(x[0] == "login" for x in c.calls)
    assert c.sent == [msg]


def test_send_starttls_with_login():
    s = _settings(smtp_user="u", smtp_password="p", smtp_starttls=True)
    mail.send_email(mail.build_verification_email("a@kido.example", "", "t", s), s)
    (c,) = FakeSMTP.instances
    names = [x[0] for x in c.calls]
    assert names.index("starttls") < names.index("login") < names.index("send")
    assert ("login", "u", "p") in c.calls


def test_send_ssl():
    s = _settings(smtp_ssl=True, smtp_port=465, smtp_starttls=True)
    mail.send_email(mail.build_verification_email("a@kido.example", "", "t", s), s)
    (c,) = FakeSMTP.instances
    assert type(c) is FakeSMTPSSL and c.context is not None
    assert ("starttls",) not in c.calls  # SSL rồi thì không STARTTLS


def test_send_failure_raises_mailerror_and_logged_helper_returns_false(monkeypatch):
    class Boom(FakeSMTP):
        def send_message(self, msg):
            raise smtplib.SMTPRecipientsRefused({"a@kido.example": (550, b"no")})

    monkeypatch.setattr(mail.smtplib, "SMTP", Boom)
    s = _settings()
    with pytest.raises(mail.MailError):
        mail.send_email(mail.build_verification_email("a@kido.example", "", "t", s), s)

    def refused(*a, **k):
        raise ConnectionRefusedError("khong ket noi duoc")

    monkeypatch.setattr(mail.smtplib, "SMTP", refused)
    assert mail.send_verification_email("a@kido.example", "A", "t") is False
