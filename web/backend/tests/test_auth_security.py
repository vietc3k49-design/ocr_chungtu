"""Lớp (a) — unit, KHÔNG cần DB: app.core.security."""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "test")

import jwt  # noqa: E402
import pytest  # noqa: E402

from app.core import security  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def test_hash_and_verify_password():
    h = security.hash_password("mat-khau-dung-8")
    assert h.startswith("$argon2id$")
    assert security.verify_password("mat-khau-dung-8", h)
    assert not security.verify_password("mat-khau-sai-88", h)
    # hash hỏng / rỗng ⇒ False, không ném lỗi
    assert not security.verify_password("x", "khong-phai-hash")
    assert not security.verify_password("x", "")
    assert security.hash_password("mat-khau-dung-8") != h  # có salt


def test_password_problem_rules():
    assert security.password_problem("1234567")[0] == "PASSWORD_TOO_SHORT"
    assert security.password_problem("12345678") is None
    assert security.password_problem("x" * 257)[0] == "PASSWORD_TOO_LONG"
    assert security.password_problem(None)[0] == "PASSWORD_TOO_SHORT"
    assert "8 ký tự" in security.password_problem("")[1]


def test_access_token_roundtrip_and_claims():
    uid = uuid.uuid4()
    h = security.hash_password("abcdefgh")
    tok = security.create_access_token(uid, h)
    payload = security.decode_access_token(tok)
    assert payload is not None
    assert payload["sub"] == str(uid)
    assert payload["exp"] - payload["iat"] == get_settings().access_token_minutes * 60
    assert jwt.get_unverified_header(tok)["alg"] == "HS256"
    assert security.token_matches_password(payload, h)
    # đổi mật khẩu ⇒ dấu vân tay khác ⇒ phiên cũ hết hiệu lực
    assert not security.token_matches_password(payload, security.hash_password("khac-han-nhe"))
    assert "pwd" in payload and h not in tok  # không lộ hash trong token


def test_access_token_rejects_expired_tampered_wrong_alg():
    uid = uuid.uuid4()
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    expired = security.create_access_token(uid, "h", minutes=1, now=past)
    assert security.decode_access_token(expired) is None

    tok = security.create_access_token(uid, "h")
    head, body, sig = tok.split(".")
    assert security.decode_access_token(f"{head}.{body}.{sig[:-2]}AA") is None
    assert security.decode_access_token("") is None
    assert security.decode_access_token("rac") is None

    # ký bằng khóa khác
    forged = jwt.encode({"sub": str(uid), "iat": int(time.time()), "exp": int(time.time()) + 60,
                         "typ": "session"}, "khoa-khac", algorithm="HS256")
    assert security.decode_access_token(forged) is None
    # alg none
    none_tok = jwt.encode({"sub": str(uid), "iat": int(time.time()), "exp": int(time.time()) + 60,
                           "typ": "session"}, None, algorithm="none")
    assert security.decode_access_token(none_tok) is None
    # sai typ / sub không phải uuid
    key = get_settings().secret_key
    bad_typ = jwt.encode({"sub": str(uid), "iat": int(time.time()), "exp": int(time.time()) + 60,
                          "typ": "refresh"}, key, algorithm="HS256")
    assert security.decode_access_token(bad_typ) is None
    bad_sub = jwt.encode({"sub": "1", "iat": int(time.time()), "exp": int(time.time()) + 60,
                          "typ": "session"}, key, algorithm="HS256")
    assert security.decode_access_token(bad_sub) is None


def test_mail_token_hashing():
    raw, h = security.new_mail_token()
    assert len(raw) >= 43  # token_urlsafe(32)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert security.hash_token(raw) == h
    raw2, h2 = security.new_mail_token()
    assert raw2 != raw and h2 != h


def test_dummy_verify_does_not_raise():
    security.dummy_verify("bat-ky")


@pytest.mark.parametrize("pw", ["", "a" * 8, "mật khẩu có dấu tiếng Việt"])
def test_unicode_passwords(pw):
    h = security.hash_password(pw)
    assert security.verify_password(pw, h)
