"""Seed dữ liệu (SPEC §5) — `python -m scripts.seed_demo [--with-demo] [--reference]`.

* Tạo admin từ ADMIN_EMAIL / ADMIN_PASSWORD (đã xác thực mail). Idempotent: có rồi thì chỉ đảm bảo
  role=admin, is_active, email_verified — KHÔNG đổi mật khẩu.
* `--with-demo`: đọc `{repo}/output/stage2_upload_groups.json` (MÔ PHỎNG 1 sheet = 1 upload), tạo 52 bộ
  `DEMO {sheet}` dưới tên admin, file theo đúng `scan_index`, enqueue job. Bộ đã có cùng title (của admin)
  ⇒ bỏ qua. Tên file gốc chỉ giữ ở `original_filename` (pipeline không thấy).
* `--reference`: bật dữ liệu tham chiếu mã chuyến DEMO (suy từ GT) cho các bộ demo — mặc định TẮT.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import GROUP_QUEUED, JOB_QUEUED, ROLE_ADMIN, AuditLog, Job, Page, UploadGroup, User
from app.services import storage

REPO_ROOT = Path(os.environ.get("KIDO_REPO_ROOT") or Path(__file__).resolve().parents[3]).resolve()


def _hash_password(pw: str) -> str:
    from app.core.security import hash_password
    return hash_password(pw)


def ensure_admin(db, email: str, password: str) -> User:
    email = (email or "").strip().lower()
    if not email or not password:
        raise SystemExit("Thiếu ADMIN_EMAIL / ADMIN_PASSWORD trong biến môi trường.")
    if len(password) < 8:
        raise SystemExit("ADMIN_PASSWORD phải có ít nhất 8 ký tự.")
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if u is None:
        u = User(email=email, password_hash=_hash_password(password), full_name="Quản trị viên",
                 role=ROLE_ADMIN, is_active=True, email_verified_at=now)
        db.add(u)
        db.flush()
        db.add(AuditLog(actor_id=u.id, action="seed_admin_create", entity="user", entity_id=str(u.id),
                        payload={"email": email}))
        print(f"[seed] tạo admin {email}")
    else:
        changed = []
        if u.role != ROLE_ADMIN:
            u.role = ROLE_ADMIN
            changed.append("role")
        if not u.is_active:
            u.is_active = True
            changed.append("is_active")
        if u.email_verified_at is None:
            u.email_verified_at = now
            changed.append("email_verified_at")
        if changed:
            db.add(AuditLog(actor_id=u.id, action="seed_admin_update", entity="user", entity_id=str(u.id),
                            payload={"changed": changed}))
        print(f"[seed] admin {email} đã có" + (f" — cập nhật {', '.join(changed)}" if changed else ""))
    db.commit()
    return u


def seed_demo_groups(db, admin: User, use_reference: bool, repo_root: Path = REPO_ROOT,
                     limit: Optional[int] = None) -> List[str]:
    """Trả danh sách title đã tạo mới."""
    ug_path = repo_root / "output" / "stage2_upload_groups.json"
    samples = repo_root / "output" / "form_samples"
    ug = json.loads(ug_path.read_text(encoding="utf-8"))
    groups = {}
    for fn, m in ug["pages"].items():
        groups.setdefault(m["upload_group_id"], {"sheet": m.get("sheet"), "pages": []})["pages"].append(
            (int(m["scan_index"]), fn))
    sheet_of = {g["upload_group_id"]: g.get("sheet") for g in ug.get("groups", [])}
    created = []
    for k, ugid in enumerate(sorted(groups)):
        if limit is not None and k >= limit:
            break
        info = groups[ugid]
        sheet = sheet_of.get(ugid) or info["sheet"] or ugid
        title = f"DEMO {sheet}"
        exists = db.execute(select(UploadGroup.id).where(UploadGroup.user_id == admin.id,
                                                         UploadGroup.title == title)).first()
        if exists:
            print(f"[seed] bỏ qua '{title}' (đã có)")
            continue
        pages = sorted(info["pages"])
        idxs = [i for i, _ in pages]
        if idxs != list(range(len(pages))):
            raise SystemExit(f"{ugid}: scan_index không liên tục 0..n-1: {idxs}")
        files = [(fn, (samples / fn).read_bytes()) for _, fn in pages]
        gid = uuid.uuid4()
        stored = storage.save_group_files(gid, files)
        try:
            db.add(UploadGroup(id=gid, user_id=admin.id, title=title, status=GROUP_QUEUED,
                               use_reference=use_reference, n_pages=len(stored)))
            db.flush()  # INSERT group trước Page/Job (Job không có relationship ⇒ không tự sắp thứ tự)
            for s in stored:
                db.add(Page(group_id=gid, scan_index=s.scan_index, original_filename=s.original_filename,
                            stored_filename=s.stored_filename, stored_path=s.stored_path, sha256=s.sha256,
                            mime=s.mime, width=s.width, height=s.height, size_bytes=s.size_bytes))
            db.add(Job(group_id=gid, status=JOB_QUEUED, message="Đang chờ xử lý (seed DEMO)"))
            db.flush()
            db.add(AuditLog(actor_id=admin.id, action="upload_create", entity="upload_group", entity_id=str(gid),
                            payload={"n_pages": len(stored), "use_reference": use_reference,
                                     "use_reference_source": "SEED_DEMO_FLAG", "demo_upload_group_id": ugid}))
            db.commit()
        except Exception:
            db.rollback()
            storage.remove_group_files(gid)
            raise
        created.append(title)
        print(f"[seed] tạo '{title}' — {len(stored)} trang, use_reference={use_reference}")
    return created


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.seed_demo")
    ap.add_argument("--with-demo", action="store_true", help="Tạo 52 bộ DEMO từ output/stage2_upload_groups.json")
    ap.add_argument("--reference", action="store_true",
                    help="Bật dữ liệu tham chiếu mã chuyến DEMO (suy từ GT) cho các bộ demo (mặc định TẮT)")
    ap.add_argument("--limit", type=int, default=None, help="Chỉ tạo N bộ demo đầu (thử nghiệm)")
    a = ap.parse_args(argv)
    s = get_settings()
    with SessionLocal() as db:
        admin = ensure_admin(db, s.admin_email, s.admin_password)
        if a.with_demo:
            created = seed_demo_groups(db, admin, use_reference=a.reference, limit=a.limit)
            print(f"[seed] xong: {len(created)} bộ DEMO mới")
    return 0


if __name__ == "__main__":
    sys.exit(main())
