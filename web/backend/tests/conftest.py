"""Cấu hình chung cho test Agent JOBS.

* Đặt SECRET_KEY / DATA_DIR TRƯỚC khi import app (get_settings có lru_cache).
* DATA_DIR = thư mục tạm riêng cho phiên test (không đụng /data thật, không ghi vào repo).
* Lớp (b) cần PostgreSQL: đọc TEST_DATABASE_URL; không kết nối được ⇒ pytest.skip có lý do (fixture `pg_engine`).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("SECRET_KEY", "test")
_TMP_DATA = Path(tempfile.mkdtemp(prefix="kido_jobs_test_")).resolve()
os.environ["DATA_DIR"] = str(_TMP_DATA)
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

MANIFEST_V2 = REPO / "output" / "stage4_out" / "stage4_verification_manifest_v2.json"
MANIFEST_S3 = REPO / "output" / "stage3_out" / "stage3_batched_manifest.json"
FORM_SAMPLES = REPO / "output" / "form_samples"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _TMP_DATA


@pytest.fixture(scope="session")
def pg_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL chưa đặt — bỏ qua test cần PostgreSQL")
    from sqlalchemy import create_engine, text
    try:
        eng = create_engine(url, pool_pre_ping=True, future=True)
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Không kết nối được PostgreSQL ({url}): {type(e).__name__}: {e}")
    from app.core.db import Base
    import app.models  # noqa: F401 — đăng ký bảng
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()
