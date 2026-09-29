"""Schema DB (SQLAlchemy 2.0) — NGUỒN SỰ THẬT DUY NHẤT cho mọi agent. Đổi schema ⇒ thêm migration Alembic.

Nguyên tắc dữ liệu:
  * Kết quả MÁY (pipeline) lưu nguyên vẹn trong các cột JSONB `s1/s2/s4`, `stage3_manifest`,
    `stage4_dossiers` — KHÔNG BAO GIỜ bị ghi đè bởi duyệt tay.
  * Duyệt tay là bảng APPEND-ONLY `signature_reviews` (bản ghi mới nhất theo (page_id, target_index)
    là quyết định hiện hành). Phán quyết "sau duyệt" được TÍNH LẠI bằng
    `tools.stage4_verifier_v2.evaluate_document_verdict_v2` (một nguồn sự thật verdict), không lưu cứng.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

ROLE_ADMIN = "admin"
ROLE_USER = "user"

GROUP_QUEUED, GROUP_RUNNING, GROUP_DONE, GROUP_FAILED = "QUEUED", "RUNNING", "DONE", "FAILED"
JOB_QUEUED, JOB_RUNNING, JOB_DONE, JOB_FAILED = "queued", "running", "done", "failed"

TOKEN_VERIFY_EMAIL = "verify_email"
TOKEN_RESET_PASSWORD = "reset_password"

REVIEW_SIGNED = "SIGNED"          # người duyệt xác nhận ô CÓ chữ ký/mộc của chính vai trò
REVIEW_NOT_SIGNED = "NOT_SIGNED"  # ô KHÔNG có chữ ký của vai trò (kể cả chỉ có mực tràn)
REVIEW_UNCLEAR = "UNCLEAR"        # không xác định được
REVIEW_DECISIONS = (REVIEW_SIGNED, REVIEW_NOT_SIGNED, REVIEW_UNCLEAR)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # lưu dạng lower()
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default=ROLE_USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class EmailToken(Base):
    """Token xác thực mail / đặt lại mật khẩu. Chỉ lưu sha256 của token, không lưu token thô."""
    __tablename__ = "email_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadGroup(Base):
    """Một lần upload = một bộ chứng từ nhiều trang có thứ tự. `id` chính là upload_group_id gửi Tầng 2.
    KHÔNG giả định 1 bộ = 1 chuyến: Tầng 3 tự tách lô trong bộ."""
    __tablename__ = "upload_groups"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default=GROUP_QUEUED, index=True)
    use_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    n_pages: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Kết quả máy cấp bộ (JSONB, bất biến sau khi chạy xong):
    stage3_manifest: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    stage4_dossiers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reference_info: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    pipeline_contract: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    pages: Mapped[list["Page"]] = relationship(back_populates="group", order_by="Page.scan_index",
                                               cascade="all, delete-orphan")
    user: Mapped["User"] = relationship()


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("group_id", "scan_index", name="uq_page_group_scan"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_groups.id", ondelete="CASCADE"), index=True)
    scan_index: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(500))   # chỉ để hiển thị, pipeline KHÔNG dùng
    stored_filename: Mapped[str] = mapped_column(String(200))     # "{scan_index:03d}_{sha8}.{ext}" = file_name gửi pipeline
    stored_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    stage1_image_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # Kết quả máy (JSONB, bất biến):
    s1: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    s2: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    s4: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Cột phẳng để lọc nhanh (sao từ JSONB):
    s1_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
    system: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    page_role: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    s4_doc_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    s4_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    group: Mapped["UploadGroup"] = relationship(back_populates="pages")


class Job(Base):
    """Hàng đợi nền trên PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED). Không cần Redis."""
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_groups.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JOB_QUEUED, index=True)
    stage: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)      # T1 | T2 | T3 | T4 | SAVE
    stage_done: Mapped[int] = mapped_column(Integer, default=0)
    stage_total: Mapped[int] = mapped_column(Integer, default=0)
    percent: Mapped[int] = mapped_column(Integer, default=0)                      # 0..100 toàn job
    message: Mapped[str] = mapped_column(String(500), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship để unit-of-work INSERT upload_groups TRƯỚC jobs (FK) — không phụ thuộc thứ tự flush tay.
    group: Mapped["UploadGroup"] = relationship()


class SignatureReview(Base):
    """Duyệt tay từng ô ký — APPEND-ONLY (không UPDATE/DELETE). Bản mới nhất theo (page_id, target_index) hiện hành."""
    __tablename__ = "signature_reviews"
    __table_args__ = (Index("ix_review_page_target", "page_id", "target_index", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    target_index: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(200))                   # sao từ s4.targets[i].role lúc duyệt
    machine_detected: Mapped[bool] = mapped_column(Boolean)          # sao từ s4.targets[i].detected lúc duyệt
    decision: Mapped[str] = mapped_column(String(20))                # REVIEW_DECISIONS
    note: Mapped[str] = mapped_column(Text, default="")
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


SETTING_USE_REFERENCE_DEFAULT = "use_reference_default"   # bool, mặc định False


class AuditLog(Base):
    """Nhật ký thao tác nhạy cảm: đăng ký, xác thực mail, đăng nhập, đổi vai trò, đổi setting, upload, duyệt."""
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


LOGIN_FAIL = "fail"        # sai mật khẩu hoặc email không tồn tại
LOGIN_SUCCESS = "success"  # đăng nhập thành công — mốc đặt lại bộ đếm theo email
LOGIN_RESET = "reset"      # đặt lại mật khẩu qua mail / admin mở khóa — mốc đặt lại bộ đếm theo email
LOGIN_LOCKED = "locked"    # bị từ chối vì đang khóa (chỉ để kiểm toán, KHÔNG tính vào bộ đếm)


class LoginAttempt(Base):
    """Nhật ký đăng nhập phục vụ giới hạn số lần sai (app/services/login_limit.py).
    Lưu ở DB (không phải bộ nhớ) để khóa còn hiệu lực qua restart và dùng chung giữa nhiều tiến trình api.
    `email` luôn chuẩn hóa lower().strip() — kể cả email không tồn tại (khóa không lộ email có tài khoản)."""
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_created", "email", "created_at"),
        Index("ix_login_attempts_ip_created", "ip", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320))
    ip: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
