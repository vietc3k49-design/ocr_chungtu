"""Khởi tạo schema: users, email_tokens, upload_groups, pages, jobs, signature_reviews, app_settings, audit_log.

Viết tay, khớp 1-1 với app/models.py (kiểm bằng tests/test_auth_migration.py: so DDL của migration
với DDL sinh từ Base.metadata, không cần DB).

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = sa.DateTime(timezone=True)
_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("email_verified_at", _TS, nullable=True),
        sa.Column("last_login_at", _TS, nullable=True),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "email_tokens",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("used_at", _TS, nullable=True),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_tokens_token_hash", "email_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_tokens_user_id", "email_tokens", ["user_id"], unique=False)

    op.create_table(
        "upload_groups",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("use_reference", sa.Boolean(), nullable=False),
        sa.Column("n_pages", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stage3_manifest", _JSONB, nullable=True),
        sa.Column("stage4_dossiers", _JSONB, nullable=True),
        sa.Column("reference_info", _JSONB, nullable=True),
        sa.Column("timings", _JSONB, nullable=True),
        sa.Column("pipeline_contract", sa.String(length=40), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_groups_created_at", "upload_groups", ["created_at"], unique=False)
    op.create_index("ix_upload_groups_status", "upload_groups", ["status"], unique=False)
    op.create_index("ix_upload_groups_user_id", "upload_groups", ["user_id"], unique=False)

    op.create_table(
        "pages",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("group_id", _UUID, nullable=False),
        sa.Column("scan_index", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("stored_filename", sa.String(length=200), nullable=False),
        sa.Column("stored_path", sa.String(length=1000), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime", sa.String(length=50), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("stage1_image_path", sa.String(length=1000), nullable=True),
        sa.Column("s1", _JSONB, nullable=True),
        sa.Column("s2", _JSONB, nullable=True),
        sa.Column("s4", _JSONB, nullable=True),
        sa.Column("s1_status", sa.String(length=30), nullable=True),
        sa.Column("doc_type", sa.String(length=60), nullable=True),
        sa.Column("system", sa.String(length=60), nullable=True),
        sa.Column("page_role", sa.String(length=30), nullable=True),
        sa.Column("batch_id", sa.String(length=120), nullable=True),
        sa.Column("s4_doc_status", sa.String(length=40), nullable=True),
        sa.Column("s4_action", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["upload_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "scan_index", name="uq_page_group_scan"),
    )
    op.create_index("ix_pages_doc_type", "pages", ["doc_type"], unique=False)
    op.create_index("ix_pages_group_id", "pages", ["group_id"], unique=False)
    op.create_index("ix_pages_s4_doc_status", "pages", ["s4_doc_status"], unique=False)
    op.create_index("ix_pages_sha256", "pages", ["sha256"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("group_id", _UUID, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=10), nullable=True),
        sa.Column("stage_done", sa.Integer(), nullable=False),
        sa.Column("stage_total", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("heartbeat_at", _TS, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["upload_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_group_id", "jobs", ["group_id"], unique=False)
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)

    op.create_table(
        "signature_reviews",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("page_id", _UUID, nullable=False),
        sa.Column("target_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=False),
        sa.Column("machine_detected", sa.Boolean(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer_id", _UUID, nullable=False),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_page_target", "signature_reviews",
                    ["page_id", "target_index", "created_at"], unique=False)
    op.create_index("ix_signature_reviews_page_id", "signature_reviews", ["page_id"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", _JSONB, nullable=False),
        sa.Column("updated_by", _UUID, nullable=True),
        sa.Column("updated_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("actor_id", _UUID, nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("payload", _JSONB, nullable=True),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"], unique=False)
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"], unique=False)
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_id", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("app_settings")
    op.drop_index("ix_signature_reviews_page_id", table_name="signature_reviews")
    op.drop_index("ix_review_page_target", table_name="signature_reviews")
    op.drop_table("signature_reviews")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_group_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_pages_sha256", table_name="pages")
    op.drop_index("ix_pages_s4_doc_status", table_name="pages")
    op.drop_index("ix_pages_group_id", table_name="pages")
    op.drop_index("ix_pages_doc_type", table_name="pages")
    op.drop_table("pages")
    op.drop_index("ix_upload_groups_user_id", table_name="upload_groups")
    op.drop_index("ix_upload_groups_status", table_name="upload_groups")
    op.drop_index("ix_upload_groups_created_at", table_name="upload_groups")
    op.drop_table("upload_groups")
    op.drop_index("ix_email_tokens_user_id", table_name="email_tokens")
    op.drop_index("ix_email_tokens_token_hash", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
