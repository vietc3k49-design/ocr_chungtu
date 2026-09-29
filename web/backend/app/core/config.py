"""Cấu hình ứng dụng web — đọc từ biến môi trường (xem web/.env.example). Không có giá trị bí mật mặc định."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Đường dẫn .env TUYỆT ĐỐI: runner.py chdir về gốc repo lúc import (tools/ đọc config bằng đường dẫn
# tương đối), nên env_file tương đối sẽ bị tìm nhầm chỗ. Trong Docker biến môi trường đến từ compose.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ENV_FILES = (str(_BACKEND_DIR.parent / ".env"), str(_BACKEND_DIR / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    # --- Hạ tầng ---
    database_url: str = "postgresql+psycopg://kido:kido@db:5432/kido"
    data_dir: Path = Path("/data")               # ảnh upload + kết quả trung gian
    kido_repo_root: Path = Path("/repo")         # gốc repo chứa tools/, config/, output/

    # --- Bảo mật ---
    secret_key: str                              # BẮT BUỘC, không mặc định
    access_token_minutes: int = 60 * 12
    cookie_name: str = "kido_session"
    cookie_secure: bool = False                  # True khi chạy HTTPS
    email_token_minutes: int = 60 * 24
    reset_token_minutes: int = 60

    # --- Giới hạn đăng nhập sai (app/services/login_limit.py) ---
    login_max_fails_per_email: int = 5       # số lần sai trong cửa sổ ⇒ khóa email
    login_max_fails_per_ip: int = 20         # số lần sai (mọi email) từ 1 IP trong cửa sổ ⇒ chặn IP
    login_window_minutes: int = 15
    login_lockout_minutes: int = 15          # khóa tính từ lần sai gần nhất
    login_attempts_retention_days: int = 30
    # Chỉ tin X-Real-IP khi đứng sau nginx của compose (api không public ra ngoài 127.0.0.1).
    trust_proxy_headers: bool = False

    # --- Mail (dev: Mailpit) ---
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    mail_from: str = "KIDO OCR <no-reply@kido-ocr.local>"
    public_base_url: str = "http://localhost:8080"   # dùng để dựng link trong mail

    # --- Upload ---
    max_files_per_upload: int = 60
    max_file_mb: int = 25

    # --- Worker ---
    worker_poll_seconds: float = 1.0
    worker_stage1_processes: int = 4
    job_stale_minutes: int = 30

    # --- Seed ---
    admin_email: str = ""
    admin_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
