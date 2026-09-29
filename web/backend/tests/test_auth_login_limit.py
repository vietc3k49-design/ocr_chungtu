"""Giới hạn số lần đăng nhập sai (app/services/login_limit.py) qua API thật.

Dùng lại hạ tầng của test_auth_api.py (fixture `client`/`Session` chạy trên Postgres THẬT và SQLite mô phỏng;
thiếu Postgres ⇒ skip, không tính là pass).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app import models
from app.core.config import get_settings
from tests.test_auth_api import (  # noqa: F401  (fixture dùng qua tên)
    H, PW, Session, audits, client, code, db_backend, login, make_user, outbox, token_from,
)

WRONG = "sai-mat-khau-1"


@pytest.fixture(autouse=True)
def _limits(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "login_max_fails_per_email", 5)
    monkeypatch.setattr(s, "login_max_fails_per_ip", 20)
    monkeypatch.setattr(s, "login_window_minutes", 15)
    monkeypatch.setattr(s, "login_lockout_minutes", 15)
    monkeypatch.setattr(s, "trust_proxy_headers", False)
    return s


def _fail_n(client, email, n, headers=None):
    for _ in range(n):
        r = client.post("/api/auth/login", json={"email": email, "password": WRONG}, headers={**H, **(headers or {})})
        assert r.status_code == 401 and code(r) == "INVALID_CREDENTIALS", r.text


def _age_attempts(Session, minutes):
    """Lùi created_at mọi bản ghi login_attempts — mô phỏng thời gian trôi, không sleep."""
    with Session() as db:
        for a in db.execute(select(models.LoginAttempt)).scalars():
            a.created_at = a.created_at - timedelta(minutes=minutes)
        db.commit()


def test_lock_after_n_wrong_passwords_even_with_correct_password(client, Session):
    make_user(Session, "a@kido.vn")
    _fail_n(client, "a@kido.vn", 5)
    r = login(client, "a@kido.vn")                       # mật khẩu ĐÚNG nhưng đang khóa
    assert r.status_code == 429 and code(r) == "TOO_MANY_ATTEMPTS"
    ra = int(r.headers["Retry-After"])
    assert 0 < ra <= 15 * 60 and r.json()["detail"]["retry_after_seconds"] == ra
    assert "tài khoản này" in r.json()["detail"]["message"]
    assert "kido_session" not in r.cookies
    assert len(audits(Session, "login_locked")) == 1


def test_four_fails_not_locked(client, Session):
    make_user(Session, "b@kido.vn")
    _fail_n(client, "b@kido.vn", 4)
    assert login(client, "b@kido.vn").status_code == 200


def test_unknown_email_locks_identically(client, Session):
    """Không lộ email có tài khoản: email không tồn tại cũng bị khóa, cùng mã + cùng khóa JSON."""
    make_user(Session, "that@kido.vn")
    _fail_n(client, "that@kido.vn", 5)
    _fail_n(client, "khongco@kido.vn", 5)
    r1 = login(client, "that@kido.vn")
    r2 = client.post("/api/auth/login", json={"email": "khongco@kido.vn", "password": PW}, headers=H)
    assert r1.status_code == r2.status_code == 429
    assert code(r1) == code(r2) == "TOO_MANY_ATTEMPTS"
    assert set(r1.json()["detail"]) == set(r2.json()["detail"])


def test_email_normalized_for_counting(client, Session):
    make_user(Session, "c@kido.vn")
    _fail_n(client, "  C@KIDO.VN ", 3)
    _fail_n(client, "c@kido.vn", 2)
    assert login(client, "c@kido.vn").status_code == 429


def test_lock_expires(client, Session):
    make_user(Session, "d@kido.vn")
    _fail_n(client, "d@kido.vn", 5)
    assert login(client, "d@kido.vn").status_code == 429
    _age_attempts(Session, 16)
    assert login(client, "d@kido.vn").status_code == 200


def test_locked_attempts_do_not_extend_lock(client, Session):
    make_user(Session, "e@kido.vn")
    _fail_n(client, "e@kido.vn", 5)
    _age_attempts(Session, 14)                            # còn ~1 phút khóa
    for _ in range(3):                                    # thử tiếp trong lúc khóa
        assert login(client, "e@kido.vn", WRONG).status_code == 429
    _age_attempts(Session, 2)                             # lần sai cuối đã 16 phút
    assert login(client, "e@kido.vn").status_code == 200


def test_success_resets_email_counter(client, Session):
    make_user(Session, "f@kido.vn")
    _fail_n(client, "f@kido.vn", 4)
    assert login(client, "f@kido.vn").status_code == 200
    _fail_n(client, "f@kido.vn", 4)
    assert login(client, "f@kido.vn").status_code == 200


def test_password_reset_unlocks(client, Session, outbox):
    make_user(Session, "g@kido.vn")
    _fail_n(client, "g@kido.vn", 5)
    assert login(client, "g@kido.vn").status_code == 429
    assert client.post("/api/auth/forgot-password", json={"email": "g@kido.vn"}, headers=H).status_code == 200
    tok = token_from(outbox[-1], "/dat-lai-mat-khau")
    r = client.post("/api/auth/reset-password", json={"token": tok, "new_password": "matkhau-moi-9"}, headers=H)
    assert r.status_code == 200, r.text
    assert login(client, "g@kido.vn", "matkhau-moi-9").status_code == 200


def test_admin_sees_lock_and_unlocks(client, Session):
    make_user(Session, "admin@kido.vn", role="admin")
    uid = make_user(Session, "h@kido.vn")
    _fail_n(client, "h@kido.vn", 5)
    assert login(client, "admin@kido.vn").status_code == 200
    rows = {u["email"]: u for u in client.get("/api/admin/users").json()}
    assert rows["h@kido.vn"]["login_locked"] is True and rows["h@kido.vn"]["login_recent_fails"] == 5
    assert rows["h@kido.vn"]["login_locked_until"]
    assert rows["admin@kido.vn"]["login_locked"] is False
    r = client.post(f"/api/admin/users/{uid}/unlock-login", headers=H)
    assert r.status_code == 200 and r.json()["login_locked"] is False
    assert len(audits(Session, "login_unlock")) == 1
    client.post("/api/auth/logout", headers=H)
    assert login(client, "h@kido.vn").status_code == 200


def test_unlock_requires_admin(client, Session):
    uid = make_user(Session, "i@kido.vn")
    make_user(Session, "j@kido.vn")
    assert login(client, "j@kido.vn").status_code == 200
    assert client.post(f"/api/admin/users/{uid}/unlock-login", headers=H).status_code == 403


def test_ip_limit_across_emails(client, Session, _limits):
    _limits.login_max_fails_per_ip = 6
    make_user(Session, "k@kido.vn")
    for i in range(3):
        _fail_n(client, f"do{i}@kido.vn", 2)             # 6 lần sai, mỗi email chỉ 2 ⇒ chưa khóa theo email
    r = login(client, "k@kido.vn")                        # email khác, mật khẩu đúng, cùng IP
    assert r.status_code == 429 and "địa chỉ mạng này" in r.json()["detail"]["message"]


def test_success_does_not_reset_ip_counter(client, Session, _limits):
    _limits.login_max_fails_per_ip = 4
    make_user(Session, "l@kido.vn")
    _fail_n(client, "x1@kido.vn", 2)
    assert login(client, "l@kido.vn").status_code == 200   # attacker có 1 tài khoản thật
    _fail_n(client, "x2@kido.vn", 2)
    assert login(client, "l@kido.vn").status_code == 429


def test_x_real_ip_ignored_unless_trusted(client, Session, _limits):
    _limits.login_max_fails_per_ip = 3
    make_user(Session, "m@kido.vn")
    for i in range(3):   # đổi X-Real-IP mỗi lần: không tin header ⇒ vẫn cùng IP thật
        _fail_n(client, f"y{i}@kido.vn", 1, headers={"X-Real-IP": f"10.0.0.{i}"})
    assert login(client, "m@kido.vn").status_code == 429


def test_x_real_ip_used_when_trusted(client, Session, _limits):
    _limits.login_max_fails_per_ip = 3
    _limits.trust_proxy_headers = True
    make_user(Session, "n@kido.vn")
    _fail_n(client, "z@kido.vn", 1, headers={"X-Real-IP": "10.0.0.1"})
    _fail_n(client, "z2@kido.vn", 2, headers={"X-Real-IP": "10.0.0.1"})
    r = client.post("/api/auth/login", json={"email": "n@kido.vn", "password": PW},
                    headers={**H, "X-Real-IP": "10.0.0.2"})   # IP khác ⇒ không bị chặn
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": "n@kido.vn", "password": PW},
                    headers={**H, "X-Real-IP": "10.0.0.1"})
    assert r.status_code == 429
    with Session() as db:
        ips = set(db.execute(select(models.LoginAttempt.ip)).scalars())
    assert {"10.0.0.1", "10.0.0.2"} <= ips


def test_correct_password_unverified_or_inactive_not_counted(client, Session):
    make_user(Session, "o@kido.vn", verified=False)
    for _ in range(6):
        assert code(login(client, "o@kido.vn")) == "EMAIL_NOT_VERIFIED"
    with Session() as db:
        uid = db.execute(select(models.User.id).where(models.User.email == "o@kido.vn")).scalar_one()
        db.execute(update(models.User).where(models.User.id == uid).values(
            email_verified_at=models.func.now()))
        db.commit()
    assert login(client, "o@kido.vn").status_code == 200


def test_old_attempts_purged_on_success(client, Session, _limits):
    _limits.login_attempts_retention_days = 30
    make_user(Session, "p@kido.vn")
    _fail_n(client, "q@kido.vn", 2)
    _age_attempts(Session, 31 * 24 * 60)
    assert login(client, "p@kido.vn").status_code == 200
    with Session() as db:
        kinds = [a.kind for a in db.execute(select(models.LoginAttempt)).scalars()]
    assert kinds == [models.LOGIN_SUCCESS]
