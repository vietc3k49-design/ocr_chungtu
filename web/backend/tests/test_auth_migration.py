"""Chuỗi migration (0001_initial → 0002_login_attempts) khớp app/models.py.

  * Lớp (a) — không cần DB: sinh DDL offline (`alembic upgrade head --sql`) và so từng câu CREATE TABLE /
    CREATE INDEX với DDL biên dịch từ Base.metadata (dialect postgresql). Downgrade offline xóa đủ mọi bảng.
  * Lớp (b) — cần Postgres (TEST_DATABASE_URL): upgrade head thật → autogenerate compare_metadata rỗng →
    downgrade base → upgrade head lại. Không kết nối được ⇒ pytest.skip.
"""
from __future__ import annotations

import io
import os
import re
import sys
from argparse import Namespace
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SECRET_KEY", "test")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

import app.models as models  # noqa: E402

FAKE_URL = "postgresql+psycopg://u:p@127.0.0.1:1/offline"
EXPECTED_TABLES = {"users", "email_tokens", "upload_groups", "pages", "jobs", "signature_reviews",
                   "app_settings", "audit_log", "login_attempts"}


def _cfg(url: str, buf: io.StringIO | None = None) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"), output_buffer=buf, cmd_opts=Namespace(x=[f"db_url={url}"]))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _norm_stmt(stmt: str) -> tuple[str, frozenset]:
    """CREATE TABLE ⇒ (đầu câu, tập phần tử — không phụ thuộc thứ tự ràng buộc); CREATE INDEX ⇒ (câu, ∅)."""
    s = " ".join(stmt.split()).rstrip(";").strip()
    m = re.match(r"^(CREATE TABLE \S+) \((.*)\)$", s)
    if not m:
        return s, frozenset()
    body, parts, depth, cur = m.group(2), [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip()); cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return m.group(1), frozenset(parts)


def _offline_sql(revision: str, downgrade: bool = False) -> str:
    buf = io.StringIO()
    cfg = _cfg(FAKE_URL, buf)
    (command.downgrade if downgrade else command.upgrade)(cfg, revision, sql=True)
    return buf.getvalue()


def _statements(sql: str, prefixes: tuple[str, ...]) -> list[str]:
    out = []
    for chunk in sql.split(";"):
        lines = [ln for ln in chunk.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        s = "\n".join(lines).strip()
        if s.startswith(prefixes) and "alembic_version" not in s:
            out.append(s)
    return out


def test_offline_upgrade_ddl_matches_models():
    mig = {_norm_stmt(s) for s in _statements(_offline_sql("head"), ("CREATE TABLE", "CREATE UNIQUE INDEX",
                                                                     "CREATE INDEX"))}
    d = postgresql.dialect()
    expected = set()
    for t in models.Base.metadata.sorted_tables:
        expected.add(_norm_stmt(str(CreateTable(t).compile(dialect=d))))
        for ix in t.indexes:
            expected.add(_norm_stmt(str(CreateIndex(ix).compile(dialect=d))))
    assert {t.name for t in models.Base.metadata.sorted_tables} == EXPECTED_TABLES
    missing, extra = expected - mig, mig - expected
    assert not missing and not extra, f"Lệch migration↔models.\nThiếu: {missing}\nThừa: {extra}"


def test_offline_downgrade_drops_everything():
    sql = _offline_sql("head:base", downgrade=True)
    dropped = set(re.findall(r"DROP TABLE (\w+)", sql)) - {"alembic_version"}
    assert dropped == EXPECTED_TABLES
    n_idx = sum(len(t.indexes) for t in models.Base.metadata.sorted_tables)
    assert len(re.findall(r"DROP INDEX", sql)) == n_idx


# ---------------------------------------------------------------- lớp (b): Postgres thật
def _pg_url_or_skip() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Chưa đặt TEST_DATABASE_URL — bỏ qua kiểm migration trên Postgres thật")
    from sqlalchemy import create_engine, text
    try:
        eng = create_engine(url, future=True)
        with eng.connect() as c:
            c.execute(text("select 1"))
        eng.dispose()
    except Exception as exc:  # pragma: no cover - phụ thuộc môi trường
        pytest.skip(f"Không kết nối được Postgres TEST_DATABASE_URL: {exc.__class__.__name__}: {exc}")
    return url


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

def test_live_upgrade_matches_models_and_roundtrip():
    url = _pg_url_or_skip()
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    cfg = _cfg(url)
    ensure_schema_at_head(url)
    eng = create_engine(url, future=True)
    try:
        with eng.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
            diff = compare_metadata(ctx, models.Base.metadata)
            assert diff == [], f"Schema DB sau upgrade lệch models: {diff}"
            assert EXPECTED_TABLES <= set(inspect(conn).get_table_names())
        command.downgrade(cfg, "base")
        with eng.connect() as conn:
            assert not (EXPECTED_TABLES & set(inspect(conn).get_table_names()))
    finally:
        command.upgrade(cfg, "head")  # để DB ở head cho các test API
        eng.dispose()
