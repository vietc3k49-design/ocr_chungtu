"""Alembic env — URL lấy từ app.core.config.get_settings().database_url (hoặc -x db_url=...).

target_metadata = app.models.Base.metadata (models.py là nguồn sự thật schema duy nhất).
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Cho phép `import app` khi chạy alembic từ bất kỳ thư mục nào.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import app.models as models  # noqa: E402  (đăng ký mọi bảng vào Base.metadata)
from app.core.config import get_settings  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata


def _database_url() -> str:
    # Không dùng config.set_main_option: URL có '%' sẽ vỡ nội suy configparser.
    x_args = context.get_x_argument(as_dictionary=True)
    return x_args.get("db_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
