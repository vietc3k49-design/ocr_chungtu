"""API Auth + Admin qua fastapi.testclient.

Hai backend DB (tham số hóa fixture `db_backend`):
  * "postgres" — lớp (b) THẬT: TEST_DATABASE_URL, schema dựng bằng `alembic upgrade head`, TRUNCATE trước mỗi test.
    Không có biến / không kết nối được ⇒ pytest.skip (KHÔNG tính là PASS).
  * "sqlite"  — lớp phụ MÔ PHỎNG: SQLite in-memory + shim JSONB→JSON, bảng tạo bằng metadata.create_all.
    Chỉ để kiểm logic endpoint khi không có Postgres; KHÔNG thay thế lớp postgres (không kiểm FOR UPDATE,
    timestamptz, migration).
Mail không gửi thật: monkeypatch `app.core.mail.send_email` ghi vào danh sách.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SECRET_KEY", "test")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.api import admin as admin_api  # noqa: E402
from app.api import auth as auth_api  # noqa: E402
from app.core import mail, security  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas_auth import AdminUserPatch  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw):  # chỉ cho backend mô phỏng
    return "JSON"


H = {"X-Requested-With": "kido"}
PW = "matkhau-123"
USER_OUT_KEYS = {"id", "email", "full_name", "role", "is_active", "email_verified", "created_at"}
ALL_TABLES = "login_attempts, audit_log, app_settings, signature_reviews, jobs, pages, upload_groups, email_tokens, users"


def ensure_schema_at_head(url: str) -> None:
    """Đưa DB test về đúng head bằng alembic, kể cả khi suite khác (vd conftest của JOBS dùng
    metadata.drop_all/create_all trên cùng TEST_DATABASE_URL) để lại trạng thái lệch:
      * có alembic_version nhưng thiếu bảng  ⇒ xóa alembic_version rồi upgrade;
      * có bảng nhưng không có alembic_version ⇒ drop_all theo metadata rồi upgrade."""
    from argparse import Namespace

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    import app.models as _models
    expected = {t.name for t in _models.Base.metadata.sorted_tables}
    eng = create_engine(url, future=True)
    try:
        with eng.begin() as c:
            names = set(inspect(c).get_table_names())
            if "alembic_version" in names and not expected <= names:
                c.execute(text("DROP TABLE alembic_version"))
            elif "alembic_version" not in names and names & expected:
                _models.Base.metadata.drop_all(c)
    finally:
        eng.dispose()
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"), cmd_opts=Namespace(x=[f"db_url={url}"]))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")


# ---------------------------------------------------------------- hạ tầng DB
def _postgres_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Chưa đặt TEST_DATABASE_URL — bỏ qua test API trên Postgres (lớp b)")
    try:
        eng = create_engine(url, future=True, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as exc:
        pytest.skip(f"Không kết nối được Postgres TEST_DATABASE_URL: {exc.__class__.__name__}: {exc}")
    ensure_schema_at_head(url)
    return eng


def _sqlite_engine():
    eng = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False},
                        poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    models.Base.metadata.create_all(eng)
    return eng


_ENGINES: dict[str, object] = {}


@pytest.fixture(params=["postgres", "sqlite"])
def db_backend(request):
    name = request.param
    if name not in _ENGINES:
        _ENGINES[name] = _postgres_engine() if name == "postgres" else _sqlite_engine()
    eng = _ENGINES[name]
    with eng.begin() as c:
        if name == "postgres":
            c.execute(text(f"TRUNCATE {ALL_TABLES} CASCADE"))
        else:
            for t in reversed(models.Base.metadata.sorted_tables):
                c.execute(t.delete())
    return name, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


@pytest.fixture
def Session(db_backend):
    return db_backend[1]


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_email", lambda msg, settings=None: sent.append(msg))
    monkeypatch.setattr(auth_api, "MAIL_RESEND_COOLDOWN_SECONDS", 0)
    return sent


@pytest.fixture
def client(Session, outbox):
    def _get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------- tiện ích
def token_from(msg, path: str) -> str:
    text_part = msg.get_body(preferencelist=("plain",)).get_content()
    m = re.search(re.escape(path) + r"\?token=([A-Za-z0-9_\-]+)", text_part)
    assert m, text_part
    return m.group(1)


def make_user(Session, email, password=PW, role="user", verified=True, active=True, full_name="Người Thử"):
    with Session() as db:
        u = models.User(email=email, password_hash=security.hash_password(password), full_name=full_name,
                        role=role, is_active=active,
                        email_verified_at=datetime.now(timezone.utc) if verified else None)
        db.add(u)
        db.commit()
        return u.id


def login(client, email, password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers=H)


def audits(Session, action):
    with Session() as db:
        return list(db.execute(select(models.AuditLog).where(models.AuditLog.action == action)).scalars())


def code(resp):
    return resp.json()["detail"]["code"]


# ---------------------------------------------------------------- health / CSRF / lỗi
def test_health_and_error_format(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/khong-ton-tai")
    assert r.status_code == 404 and code(r) == "NOT_FOUND" and r.json()["detail"]["message"]


def test_csrf_header_required_on_unsafe_methods(client):
    r = client.post("/api/auth/login", json={"email": "a@b.vn", "password": PW})
    assert r.status_code == 403 and code(r) == "CSRF"
    r = client.post("/api/auth/login", json={"email": "a@b.vn", "password": PW},
                    headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 403 and code(r) == "CSRF"
    assert client.get("/api/auth/me").status_code == 401  # GET không cần header


def test_validation_error_format(client):
    r = client.post("/api/auth/register", json={"email": "a@b.vn"}, headers=H)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "VALIDATION_ERROR" and "password" in d["message"] and isinstance(d["errors"], list)


# ---------------------------------------------------------------- đăng ký / xác thực / đăng nhập
def test_register_verify_login_flow(client, Session, outbox):
    r = client.post("/api/auth/register",
                    json={"email": "  An.Nguyen@KIDO.vn ", "password": PW, "full_name": " Nguyễn An "}, headers=H)
    assert r.status_code == 201 and "kiểm tra hộp thư" in r.json()["message"]
    assert len(outbox) == 1 and outbox[0]["To"] == "an.nguyen@kido.vn"
    tok = token_from(outbox[0], "/xac-thuc-email")
    with Session() as db:
        u = db.execute(select(models.User)).scalar_one()
        assert u.email == "an.nguyen@kido.vn" and u.full_name == "Nguyễn An" and u.role == "user"
        assert u.email_verified_at is None and u.is_active
        et = db.execute(select(models.EmailToken)).scalar_one()
        assert et.token_hash == security.hash_token(tok) and tok not in et.token_hash  # chỉ lưu sha256
    assert len(audits(Session, "register")) == 1

    # sai mật khẩu khi chưa verify ⇒ 401 (không lộ trạng thái); đúng mật khẩu ⇒ 403 EMAIL_NOT_VERIFIED
    assert code(login(client, "an.nguyen@kido.vn", "sai-mat-khau")) == "INVALID_CREDENTIALS"
    r = login(client, "AN.NGUYEN@kido.vn")
    assert r.status_code == 403 and code(r) == "EMAIL_NOT_VERIFIED"
    assert get_settings().cookie_name not in r.cookies

    r = client.post("/api/auth/verify-email", json={"token": tok}, headers=H)
    assert r.status_code == 200, r.text
    assert len(audits(Session, "verify_email")) == 1
    r = client.post("/api/auth/verify-email", json={"token": tok}, headers=H)
    assert r.status_code == 400 and code(r) == "TOKEN_USED"

    r = login(client, "an.nguyen@kido.vn")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == USER_OUT_KEYS and body["email_verified"] is True and body["role"] == "user"
    sc = r.headers["set-cookie"]
    assert sc.startswith(get_settings().cookie_name + "=")
    assert "HttpOnly" in sc and "samesite=lax" in sc.lower() and "Path=/" in sc
    assert f"Max-Age={get_settings().access_token_minutes * 60}" in sc
    assert "Secure" not in sc  # cookie_secure=False mặc định
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["id"] == body["id"]
    with Session() as db:
        assert db.execute(select(models.User)).scalar_one().last_login_at is not None
    assert len(audits(Session, "login_ok")) == 1


def test_register_validation(client):
    r = client.post("/api/auth/register", json={"email": "a@kido.vn", "password": "1234567", "full_name": "A"},
                    headers=H)
    assert r.status_code == 422 and code(r) == "PASSWORD_TOO_SHORT"
    r = client.post("/api/auth/register", json={"email": "khong-phai-email", "password": PW, "full_name": "A"},
                    headers=H)
    assert r.status_code == 422 and code(r) == "INVALID_EMAIL"
    r = client.post("/api/auth/register", json={"email": "a@kido.vn", "password": PW, "full_name": "   "},
                    headers=H)
    assert r.status_code == 422 and code(r) == "INVALID_FULL_NAME"


def test_register_duplicate_is_neutral_and_never_overwrites(client, Session, outbox):
    make_user(Session, "da-co@kido.vn", verified=True)
    first = client.post("/api/auth/register", json={"email": "moi@kido.vn", "password": PW, "full_name": "M"},
                        headers=H)
    outbox.clear()
    r = client.post("/api/auth/register",
                    json={"email": "DA-CO@kido.vn", "password": "mat-khau-ke-gian", "full_name": "Kẻ gian"}, headers=H)
    assert r.status_code == 201 and r.json() == first.json()  # cùng thông báo
    assert outbox == []  # đã verify ⇒ không gửi gì
    assert login(client, "da-co@kido.vn").status_code == 200
    assert code(login(client, "da-co@kido.vn", "mat-khau-ke-gian")) == "INVALID_CREDENTIALS"
    with Session() as db:
        assert db.execute(select(models.User).where(models.User.email == "da-co@kido.vn")).scalar_one() \
                 .full_name == "Người Thử"
    # tài khoản chưa verify đăng ký lại ⇒ gửi lại mail xác thực
    r = client.post("/api/auth/register", json={"email": "moi@kido.vn", "password": "khac-nua-nhe", "full_name": "X"},
                    headers=H)
    assert r.status_code == 201 and len(outbox) == 1 and outbox[0]["To"] == "moi@kido.vn"


def test_login_failures_are_audited(client, Session):
    make_user(Session, "u@kido.vn")
    r = login(client, "u@kido.vn", "sai-roi-nhe")
    assert r.status_code == 401 and code(r) == "INVALID_CREDENTIALS"
    r2 = login(client, "khong-ton-tai@kido.vn")
    assert r2.status_code == 401 and r2.json() == r.json()  # không phân biệt email có/không
    rows = audits(Session, "login_fail")
    assert sorted(a.payload["reason"] for a in rows) == ["bad_password", "unknown_email"]
    assert all(a.payload.get("email") for a in rows)


def test_inactive_user_login_and_existing_session(client, Session):
    uid = make_user(Session, "u@kido.vn")
    assert login(client, "u@kido.vn").status_code == 200
    with Session() as db:
        db.get(models.User, uid).is_active = False
        db.commit()
    r = client.get("/api/auth/me")
    assert r.status_code == 403 and code(r) == "USER_INACTIVE"
    client.cookies.clear()
    r = login(client, "u@kido.vn")
    assert r.status_code == 403 and code(r) == "USER_INACTIVE"
    assert code(login(client, "u@kido.vn", "sai-roi-nhe")) == "INVALID_CREDENTIALS"


def test_me_requires_valid_cookie(client, Session):
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and code(r) == "NOT_AUTHENTICATED"
    client.cookies.set(get_settings().cookie_name, "rac.rac.rac")
    assert client.get("/api/auth/me").status_code == 401
    # token hợp lệ nhưng user không tồn tại
    client.cookies.set(get_settings().cookie_name, security.create_access_token(uuid.uuid4(), "h"))
    assert client.get("/api/auth/me").status_code == 401


def test_logout(client, Session):
    make_user(Session, "u@kido.vn")
    login(client, "u@kido.vn")
    r = client.post("/api/auth/logout", headers=H)
    assert r.status_code == 200 and "Max-Age=0" in r.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401
    assert len(audits(Session, "logout")) == 1
    assert client.post("/api/auth/logout", headers=H).status_code == 200  # không có phiên vẫn OK


# ---------------------------------------------------------------- gửi lại / token
def test_resend_verification_neutral_and_invalidates_old(client, Session, outbox):
    client.post("/api/auth/register", json={"email": "a@kido.vn", "password": PW, "full_name": "A"}, headers=H)
    old = token_from(outbox[-1], "/xac-thuc-email")
    make_user(Session, "verified@kido.vn")

    msgs = set()
    for e in ("a@kido.vn", "verified@kido.vn", "khong-co@kido.vn", ""):
        r = client.post("/api/auth/resend-verification", json={"email": e}, headers=H)
        assert r.status_code == 200
        msgs.add(r.json()["message"])
    assert len(msgs) == 1  # trung tính tuyệt đối
    assert [m["To"] for m in outbox] == ["a@kido.vn", "a@kido.vn"]
    new = token_from(outbox[-1], "/xac-thuc-email")
    assert new != old
    r = client.post("/api/auth/verify-email", json={"token": old}, headers=H)
    assert r.status_code == 400 and code(r) == "INVALID_TOKEN"
    assert client.post("/api/auth/verify-email", json={"token": new}, headers=H).status_code == 200


def test_resend_cooldown(client, Session, outbox, monkeypatch):
    client.post("/api/auth/register", json={"email": "a@kido.vn", "password": PW, "full_name": "A"}, headers=H)
    monkeypatch.setattr(auth_api, "MAIL_RESEND_COOLDOWN_SECONDS", 3600)
    r = client.post("/api/auth/resend-verification", json={"email": "a@kido.vn"}, headers=H)
    assert r.status_code == 200 and len(outbox) == 1  # không gửi thêm trong thời gian chờ


def test_expired_and_bogus_tokens(client, Session, outbox):
    client.post("/api/auth/register", json={"email": "a@kido.vn", "password": PW, "full_name": "A"}, headers=H)
    tok = token_from(outbox[-1], "/xac-thuc-email")
    with Session() as db:
        et = db.execute(select(models.EmailToken)).scalar_one()
        et.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/auth/verify-email", json={"token": tok}, headers=H)
    assert r.status_code == 400 and code(r) == "TOKEN_EXPIRED"
    for bogus in ("", "x" * 500, "khong-ton-tai"):
        r = client.post("/api/auth/verify-email", json={"token": bogus}, headers=H)
        assert r.status_code == 400 and code(r) == "INVALID_TOKEN"


def test_token_expiry_follows_settings(client, Session, outbox):
    client.post("/api/auth/register", json={"email": "a@kido.vn", "password": PW, "full_name": "A"}, headers=H)
    uid = make_user(Session, "b@kido.vn")
    client.post("/api/auth/forgot-password", json={"email": "b@kido.vn"}, headers=H)
    s = get_settings()
    with Session() as db:
        rows = {t.purpose: t for t in db.execute(select(models.EmailToken)).scalars()}
    now = datetime.now(timezone.utc)

    def minutes_left(t):
        e = t.expires_at if t.expires_at.tzinfo else t.expires_at.replace(tzinfo=timezone.utc)
        return (e - now).total_seconds() / 60

    assert abs(minutes_left(rows[models.TOKEN_VERIFY_EMAIL]) - s.email_token_minutes) < 2
    assert abs(minutes_left(rows[models.TOKEN_RESET_PASSWORD]) - s.reset_token_minutes) < 2
    assert rows[models.TOKEN_RESET_PASSWORD].user_id == uid


# ---------------------------------------------------------------- quên / đặt lại / đổi mật khẩu
def test_forgot_and_reset_password(client, Session, outbox):
    make_user(Session, "u@kido.vn")
    assert login(client, "u@kido.vn").status_code == 200
    old_cookie = client.cookies.get(get_settings().cookie_name)

    msgs = {client.post("/api/auth/forgot-password", json={"email": e}, headers=H).json()["message"]
            for e in ("U@kido.vn", "khong-co@kido.vn")}
    assert len(msgs) == 1 and len(outbox) == 1
    tok = token_from(outbox[0], "/dat-lai-mat-khau")

    r = client.post("/api/auth/reset-password", json={"token": tok, "new_password": "ngan"}, headers=H)
    assert r.status_code == 422 and code(r) == "PASSWORD_TOO_SHORT"  # token KHÔNG bị tiêu
    # token xác thực email không dùng được để đặt lại mật khẩu
    r = client.post("/api/auth/reset-password", json={"token": "x" + tok, "new_password": "moi-moi-123"}, headers=H)
    assert code(r) == "INVALID_TOKEN"

    r = client.post("/api/auth/reset-password", json={"token": tok, "new_password": "moi-moi-123"}, headers=H)
    assert r.status_code == 200, r.text
    assert code(client.post("/api/auth/reset-password", json={"token": tok, "new_password": "lan-hai-123"},
                            headers=H)) == "TOKEN_USED"
    assert len(audits(Session, "password_reset")) == 1

    client.cookies.set(get_settings().cookie_name, old_cookie)
    assert client.get("/api/auth/me").status_code == 401  # phiên cũ hết hiệu lực sau đặt lại
    client.cookies.clear()
    assert code(login(client, "u@kido.vn")) == "INVALID_CREDENTIALS"
    assert login(client, "u@kido.vn", "moi-moi-123").status_code == 200


def test_reset_with_verify_token_rejected(client, Session, outbox):
    client.post("/api/auth/register", json={"email": "a@kido.vn", "password": PW, "full_name": "A"}, headers=H)
    vtok = token_from(outbox[-1], "/xac-thuc-email")
    r = client.post("/api/auth/reset-password", json={"token": vtok, "new_password": "moi-moi-123"}, headers=H)
    assert r.status_code == 400 and code(r) == "INVALID_TOKEN"


def test_new_reset_token_invalidates_old(client, Session, outbox):
    make_user(Session, "u@kido.vn")
    client.post("/api/auth/forgot-password", json={"email": "u@kido.vn"}, headers=H)
    client.post("/api/auth/forgot-password", json={"email": "u@kido.vn"}, headers=H)
    t1, t2 = (token_from(m, "/dat-lai-mat-khau") for m in outbox)
    assert code(client.post("/api/auth/reset-password", json={"token": t1, "new_password": "moi-moi-123"},
                            headers=H)) == "INVALID_TOKEN"
    assert client.post("/api/auth/reset-password", json={"token": t2, "new_password": "moi-moi-123"},
                       headers=H).status_code == 200


def test_forgot_for_inactive_user_sends_nothing(client, Session, outbox):
    make_user(Session, "khoa@kido.vn", active=False)
    r = client.post("/api/auth/forgot-password", json={"email": "khoa@kido.vn"}, headers=H)
    assert r.status_code == 200 and outbox == []


def test_change_password(client, Session):
    make_user(Session, "u@kido.vn")
    login(client, "u@kido.vn")
    r = client.post("/api/auth/change-password", json={"old_password": "sai-roi-nhe", "new_password": "moi-moi-123"},
                    headers=H)
    assert r.status_code == 400 and code(r) == "INVALID_OLD_PASSWORD"
    r = client.post("/api/auth/change-password", json={"old_password": PW, "new_password": "1"}, headers=H)
    assert r.status_code == 422 and code(r) == "PASSWORD_TOO_SHORT"
    r = client.post("/api/auth/change-password", json={"old_password": PW, "new_password": "moi-moi-123"}, headers=H)
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # phiên hiện tại được cấp lại
    client.cookies.clear()
    assert login(client, "u@kido.vn", "moi-moi-123").status_code == 200
    assert len(audits(Session, "password_change")) == 1
    client.cookies.clear()
    assert client.post("/api/auth/change-password", json={"old_password": "a", "new_password": "b"},
                       headers=H).status_code == 401


# ---------------------------------------------------------------- admin
def test_admin_routes_require_admin(client, Session):
    make_user(Session, "u@kido.vn")
    assert client.get("/api/admin/users").status_code == 401
    login(client, "u@kido.vn")
    for method, path, body in (("get", "/api/admin/users", None), ("get", "/api/admin/settings", None),
                               ("put", "/api/admin/settings", {"use_reference_default": True}),
                               ("get", "/api/admin/audit", None),
                               ("patch", f"/api/admin/users/{uuid.uuid4()}", {"role": "admin"})):
        r = client.request(method.upper(), path, json=body, headers=H)
        assert r.status_code == 403 and code(r) == "FORBIDDEN", (path, r.text)


def test_admin_list_and_patch_users(client, Session):
    aid = make_user(Session, "admin@kido.vn", role="admin", full_name="Quản Trị")
    uid = make_user(Session, "nhan.vien@kido.vn", full_name="Nhân Viên Kho")
    assert login(client, "admin@kido.vn").status_code == 200

    rows = client.get("/api/admin/users").json()
    assert {r["email"] for r in rows} == {"admin@kido.vn", "nhan.vien@kido.vn"}
    assert all(set(r) == USER_OUT_KEYS | {"last_login_at", "login_locked", "login_locked_until", "login_recent_fails"} for r in rows)
    assert next(r for r in rows if r["email"] == "admin@kido.vn")["last_login_at"] is not None
    assert [r["email"] for r in client.get("/api/admin/users", params={"q": "nhân viên"}).json()] == ["nhan.vien@kido.vn"]
    assert [r["email"] for r in client.get("/api/admin/users", params={"q": "NHAN.VIEN@"}).json()] == ["nhan.vien@kido.vn"]
    assert client.get("/api/admin/users", params={"q": "%"}).json() == []  # ký tự LIKE được escape

    # tự hạ quyền / tự khóa
    for body in ({"role": "user"}, {"is_active": False}):
        r = client.patch(f"/api/admin/users/{aid}", json=body, headers=H)
        assert r.status_code == 409 and code(r) == "CANNOT_MODIFY_SELF"
    assert client.patch(f"/api/admin/users/{aid}", json={"role": "admin"}, headers=H).status_code == 200  # no-op

    # validate
    assert code(client.patch(f"/api/admin/users/{uid}", json={"role": "sep"}, headers=H)) == "INVALID_ROLE"
    assert code(client.patch(f"/api/admin/users/{uid}", json={}, headers=H)) == "NO_CHANGES"
    assert client.patch(f"/api/admin/users/{uid}", json={"is_active": "no"}, headers=H).status_code == 422
    assert code(client.patch(f"/api/admin/users/{uuid.uuid4()}", json={"role": "user"}, headers=H)) == "USER_NOT_FOUND"
    assert code(client.patch("/api/admin/users/khong-phai-uuid", json={"role": "user"}, headers=H)) == "USER_NOT_FOUND"

    # nâng quyền rồi khóa người khác
    r = client.patch(f"/api/admin/users/{uid}", json={"role": "admin"}, headers=H)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    r = client.patch(f"/api/admin/users/{uid}", json={"role": "user", "is_active": False}, headers=H)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["role"] == "user"
    rc = audits(Session, "role_change")
    assert sorted((a.payload["old"], a.payload["new"]) for a in rc) == [("admin", "user"), ("user", "admin")]
    ac = audits(Session, "active_change")
    assert len(ac) == 1 and ac[0].payload == {"email": "nhan.vien@kido.vn", "old": True, "new": False}
    assert all(a.actor_id == aid and a.entity_id == str(uid) for a in rc + ac)


def test_last_admin_guard(Session):
    """Qua API không thể chạm LAST_ADMIN (actor luôn là 1 admin còn hoạt động) — kiểm trực tiếp luật với actor
    không nằm trong DB (mô phỏng race: admin còn lại vừa bị khóa ở giao dịch khác)."""
    aid = make_user(Session, "admin@kido.vn", role="admin")
    ghost = SimpleNamespace(id=uuid.uuid4(), role="admin")
    with Session() as db:
        for body in (AdminUserPatch(role="user"), AdminUserPatch(is_active=False)):
            with pytest.raises(HTTPException) as ei:
                admin_api.patch_user(str(aid), body, db=db, actor=ghost)
            assert ei.value.status_code == 409 and ei.value.detail["code"] == "LAST_ADMIN"
            db.rollback()
    # admin chưa xác thực không được tính là admin dùng được
    make_user(Session, "admin2@kido.vn", role="admin", verified=False)
    with Session() as db:
        with pytest.raises(HTTPException) as ei:
            admin_api.patch_user(str(aid), AdminUserPatch(role="user"), db=db, actor=ghost)
        assert ei.value.detail["code"] == "LAST_ADMIN"
    # có admin thứ 2 dùng được ⇒ cho phép
    a3 = make_user(Session, "admin3@kido.vn", role="admin")
    with Session() as db:
        out = admin_api.patch_user(str(aid), AdminUserPatch(role="user"), db=db, actor=db.get(models.User, a3))
        assert out.role == "user"


def test_admin_settings(client, Session):
    make_user(Session, "admin@kido.vn", role="admin")
    login(client, "admin@kido.vn")
    assert client.get("/api/admin/settings").json() == {"use_reference_default": False}  # chưa có dòng
    r = client.put("/api/admin/settings", json={"use_reference_default": True}, headers=H)
    assert r.status_code == 200 and r.json() == {"use_reference_default": True}
    assert client.get("/api/admin/settings").json() == {"use_reference_default": True}
    client.put("/api/admin/settings", json={"use_reference_default": False}, headers=H)
    assert client.put("/api/admin/settings", json={"use_reference_default": "yes"}, headers=H).status_code == 422
    assert client.put("/api/admin/settings", json={}, headers=H).status_code == 422
    rows = sorted(audits(Session, "setting_change"), key=lambda a: a.payload["new"], reverse=True)
    assert [(a.payload["old"], a.payload["new"], a.payload["row_existed"]) for a in rows] == \
           [(False, True, False), (True, False, True)]
    with Session() as db:
        row = db.get(models.AppSetting, models.SETTING_USE_REFERENCE_DEFAULT)
        assert row.value is False and row.updated_by is not None


def test_admin_audit_list(client, Session):
    make_user(Session, "admin@kido.vn", role="admin")
    login(client, "admin@kido.vn", "sai-roi-nhe")
    login(client, "admin@kido.vn")
    rows = client.get("/api/admin/audit").json()
    actions = {r["action"] for r in rows}
    assert {"login_fail", "login_ok"} <= actions
    ok = next(r for r in rows if r["action"] == "login_ok")
    assert ok["actor_email"] == "admin@kido.vn" and ok["entity"] == "user"
    assert len(client.get("/api/admin/audit", params={"limit": 1}).json()) == 1
    assert {r["action"] for r in client.get("/api/admin/audit", params={"action": "login_fail"}).json()} == {"login_fail"}
    assert client.get("/api/admin/audit", params={"limit": 0}).status_code == 422
