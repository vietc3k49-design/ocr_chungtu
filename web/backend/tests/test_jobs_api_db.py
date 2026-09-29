"""Lớp (b) — cần PostgreSQL (TEST_DATABASE_URL). Không kết nối được ⇒ SKIP (không tính là pass).

End-to-end: API upload → `python -m app.worker --once` (tiến trình thật) → đọc kết quả → duyệt tay → chạy lại.
Bộ nhỏ: `Load_3.2__0.png` + `Load_3.2__1.png` (LOADING_PLAN đa trang). Kết quả T4 đối chiếu manifest ver2
chính thức (parity runner đã 0 lệch — lệch ở đây ⇒ lỗi phần lưu/đọc của web).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from conftest import BACKEND, FORM_SAMPLES, MANIFEST_V2

H = {"X-Requested-With": "kido"}
PW = "matkhau-test-123"


@pytest.fixture(scope="module")
def env(pg_engine):
    from fastapi.testclient import TestClient

    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.main import app
    from app.models import ROLE_ADMIN, ROLE_USER, User

    assert app.state.optional_routers.get("app.api.groups") and app.state.optional_routers.get("app.api.pages")
    now = datetime.now(timezone.utc)
    users = {}
    with SessionLocal() as db:
        for key, role in (("owner", ROLE_USER), ("other", ROLE_USER), ("admin", ROLE_ADMIN)):
            u = User(email=f"{key}-{uuid.uuid4().hex[:6]}@kido-test.vn", password_hash=hash_password(PW),
                     full_name=key, role=role, is_active=True, email_verified_at=now)
            db.add(u)
            db.commit()
            users[key] = (u.id, u.email)
    clients = {}
    for key, (_, email) in users.items():
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "password": PW}, headers=H)
        assert r.status_code == 200, r.text
        clients[key] = c
    return {"clients": clients, "users": users, "SessionLocal": SessionLocal}


def _files(names):
    return [("files", (n, (FORM_SAMPLES / n).read_bytes(), "image/png")) for n in names]


def _run_worker_once():
    e = dict(os.environ)
    e["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    e["WORKER_STAGE1_PROCESSES"] = "2"
    e["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-m", "app.worker", "--once"], cwd=str(BACKEND), env=e,
                       capture_output=True, text=True, encoding="utf-8", timeout=900)
    return p


def test_upload_validation(env):
    c = env["clients"]["owner"]
    r = c.post("/api/groups", files=[("files", ("gia_mao.png", b"day la van ban" * 20, "image/png"))], headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_IMAGE", r.text
    buf = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (20, 20)).save(buf, format="GIF")
    r = c.post("/api/groups", files=[("files", ("a.png", buf.getvalue(), "image/png"))], headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"
    r = c.post("/api/groups", data={"title": "x"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "NO_FILES"
    r = c.post("/api/groups", files=_files(["Load_3.2__0.png"]))  # thiếu header CSRF
    assert r.status_code == 403


def test_use_reference_only_admin(env):
    cu, ca = env["clients"]["owner"], env["clients"]["admin"]
    r = cu.post("/api/groups", files=_files(["Load_3.8__0.png"]), data={"use_reference": "true", "title": "ref-u"},
                headers=H)
    assert r.status_code == 201 and r.json()["use_reference"] is False
    r = ca.post("/api/groups", files=_files(["Load_3.8__0.png"]), data={"use_reference": "true", "title": "ref-a"},
                headers=H)
    assert r.status_code == 201 and r.json()["use_reference"] is True
    assert r.json()["reference_badge_vi"]
    # dọn job để worker --once sau không nhặt nhầm
    from app.models import JOB_FAILED, Job
    with env["SessionLocal"]() as db:
        for j in db.query(Job).all():
            j.status = JOB_FAILED
        db.commit()


def test_end_to_end_lp_two_pages(env, data_dir):
    cu, co, ca = env["clients"]["owner"], env["clients"]["other"], env["clients"]["admin"]
    r = cu.post("/api/groups", files=_files(["Load_3.2__0.png", "Load_3.2__1.png"]), data={"title": "LP 3.2"},
                headers=H)
    assert r.status_code == 201, r.text
    g = r.json()
    gid = g["id"]
    assert g["status"] == "QUEUED" and g["n_pages"] == 2 and g["use_reference"] is False
    assert [p["scan_index"] for p in g["pages"]] == [0, 1]
    assert [p["original_filename"] for p in g["pages"]] == ["Load_3.2__0.png", "Load_3.2__1.png"]
    assert g["job"]["status"] == "queued"
    # phân quyền
    assert co.get(f"/api/groups/{gid}").status_code == 404
    assert ca.get(f"/api/groups/{gid}").status_code == 200
    assert gid not in [x["id"] for x in co.get("/api/groups").json()]
    assert gid in [x["id"] for x in ca.get("/api/groups?all=true").json()]
    assert gid in [x["id"] for x in cu.get("/api/groups").json()]
    # chạy worker thật
    p = _run_worker_once()
    assert p.returncode == 0, p.stdout + p.stderr
    st = cu.get(f"/api/groups/{gid}/status").json()
    assert st["status"] == "DONE" and st["job"]["percent"] == 100 and st["job"]["status"] == "done", st
    g = cu.get(f"/api/groups/{gid}").json()
    assert g["stage3_scope"] == "UPLOAD_GROUP" and g["reference_info"]["enabled"] is False
    assert g["n_lp_pages"] == 2
    # đối chiếu T4 với manifest ver2 chính thức (theo trang gốc)
    off = {d["file_name"]: d for d in json.loads(MANIFEST_V2.read_text(encoding="utf-8"))["documents"]}
    for ps in g["pages"]:
        det = cu.get(f"/api/pages/{ps['id']}").json()
        o = off[ps["original_filename"]]
        assert det["doc_type"] == "LOADING_PLAN" and det["supported"] is True
        assert det["s4"]["doc_status"] == o["doc_status"], (ps["original_filename"], det["s4"], o["doc_status"])
        assert [t["detected"] for t in det["s4"]["targets"]] == [t["detected"] for t in o["targets"]]
        assert [t["required"] for t in det["s4"]["targets"]] == [t["required"] for t in o["targets"]]
        assert det["effective"]["doc_status"] == o["doc_status"] and det["effective"]["source"] == "MACHINE"
        for kind in ("original", "stage1"):
            im = cu.get(f"/api/pages/{ps['id']}/image?kind={kind}")
            assert im.status_code == 200 and im.headers["content-type"].startswith("image/"), (kind, im.text[:200])
        assert co.get(f"/api/pages/{ps['id']}").status_code == 404
        assert co.get(f"/api/pages/{ps['id']}/image?kind=original").status_code == 404
    print("\n[e2e] timings", g["timings"], "| batches", g["batches"], "| pages",
          [(x["original_filename"], x["system"], x["page_role"], x["s4_doc_status"], x["status_label_vi"])
           for x in g["pages"]],
          "| dossiers", [(x["dossier_id"], x["pages"], x["doc_status"]) for x in g["dossiers"]])
    assert g["dossiers"], "phải có hồ sơ LOADING_PLAN"
    d0 = g["dossiers"][0]
    assert d0["effective_doc_status"] == d0["doc_status"]
    assert all(ref["page_id"] for ref in d0["page_refs"])

    # --- duyệt tay: NOT_SIGNED một ô required ở trang có khối ký ⇒ trang + hồ sơ hết DAT
    sig = None
    for ps in g["pages"]:
        det = cu.get(f"/api/pages/{ps['id']}").json()
        req = [t for t in det["s4"]["targets"] if t["required"] and t["detected"]]
        if req:
            sig, t = det, req[0]
            break
    assert sig is not None, "bộ Load_3.2 phải có trang có khối ký với ô required đã ký"
    pid, ti = sig["id"], t["index"]
    assert co.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "NOT_SIGNED"}, headers=H).status_code == 404
    r = cu.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "MAYBE"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_DECISION"
    assert cu.post(f"/api/pages/{pid}/targets/999/review", json={"decision": "SIGNED"}, headers=H).status_code == 404
    r = cu.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "NOT_SIGNED", "note": "không thấy"},
                headers=H)
    assert r.status_code == 200, r.text
    det = r.json()
    assert not str(det["effective"]["doc_status"]).startswith("DAT_"), det["effective"]
    assert str(det["s4"]["doc_status"]).startswith("DAT_")  # máy bất biến
    tt = det["s4"]["targets"][ti]
    assert tt["latest_review"]["decision"] == "NOT_SIGNED" and tt["effective_detected"] is False
    assert tt["detected"] is True and det["reviewed"] is True
    g2 = cu.get(f"/api/groups/{gid}").json()
    dd = next(x for x in g2["dossiers"] if pid in [ref["page_id"] for ref in x["page_refs"]])
    assert str(dd["doc_status"]).startswith("DAT_") and not str(dd["effective_doc_status"]).startswith("DAT_")
    # UNCLEAR ⇒ cần kiểm tra tay; SIGNED ⇒ về DAT; lịch sử append-only
    det = cu.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "UNCLEAR"}, headers=H).json()
    assert det["effective"]["doc_status"] == "CAN_KIEM_TRA_TAY"
    det = ca.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "SIGNED"}, headers=H).json()
    assert str(det["effective"]["doc_status"]).startswith("DAT_")
    hist = cu.get(f"/api/pages/{pid}/reviews").json()
    assert [h["decision"] for h in hist] == ["SIGNED", "UNCLEAR", "NOT_SIGNED"]
    assert hist[0]["reviewer_email"] == env["users"]["admin"][1] and not any(h["stale"] for h in hist)
    # lại NOT_SIGNED để kiểm stale/giữ sau khi chạy lại
    cu.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "NOT_SIGNED"}, headers=H)

    # --- chạy lại
    r = cu.post(f"/api/groups/{gid}/rerun", headers=H)
    assert r.status_code == 202 and r.json()["status"] == "QUEUED", r.text
    assert cu.post(f"/api/groups/{gid}/rerun", headers=H).status_code == 409
    assert cu.post(f"/api/pages/{pid}/targets/{ti}/review", json={"decision": "SIGNED"},
                   headers=H).status_code == 409  # chưa DONE ⇒ không duyệt
    p = _run_worker_once()
    assert p.returncode == 0, p.stdout + p.stderr
    det = cu.get(f"/api/pages/{pid}").json()
    assert det["group_status"] == "DONE"
    assert det["s4"]["targets"][ti]["latest_review"]["stale"] is False  # role không đổi ⇒ vẫn áp dụng
    assert not str(det["effective"]["doc_status"]).startswith("DAT_")
    assert len(cu.get(f"/api/pages/{pid}/reviews").json()) == 4

    # --- path traversal: đường dẫn trong DB trỏ ra ngoài data_dir ⇒ 404, không phục vụ file
    from app.models import Page
    with env["SessionLocal"]() as db:
        pg = db.get(Page, uuid.UUID(pid))
        pg.stored_path = str(MANIFEST_V2)
        db.commit()
    assert cu.get(f"/api/pages/{pid}/image?kind=original").status_code == 404
    assert cu.get(f"/api/pages/{pid}/image?kind=abc").status_code == 400


def test_worker_failure_is_recorded(env):
    from app import worker
    from app.models import GROUP_QUEUED, JOB_QUEUED, Job, UploadGroup

    with env["SessionLocal"]() as db:
        g = UploadGroup(user_id=env["users"]["owner"][0], title="fail", status=GROUP_QUEUED, n_pages=0)
        db.add(g)
        db.flush()
        db.add(Job(group_id=g.id, status=JOB_QUEUED))
        db.commit()
        gid = g.id
        job = worker.claim_job(db, "test:1")
        assert job is not None and job.group_id == gid

        def boom(**kw):
            kw["progress"]("T2", 1, 2, "x")
            raise RuntimeError("hỏng giả lập")

        assert worker.process_job(db, job, run_fn=boom) is False
        db.expire_all()
        j, g = db.get(Job, job.id), db.get(UploadGroup, gid)
        assert j.status == "failed" and "RuntimeError" in j.error and "Traceback" in j.error
        assert g.status == "FAILED" and "Phân loại chứng từ" in g.error


def test_skip_locked_and_stale_reset(env):
    from sqlalchemy import select

    from app import worker
    from app.models import GROUP_QUEUED, JOB_QUEUED, JOB_RUNNING, Job, UploadGroup

    SL = env["SessionLocal"]
    with SL() as db:
        gids = []
        for i in range(2):
            g = UploadGroup(user_id=env["users"]["owner"][0], title=f"q{i}", status=GROUP_QUEUED, n_pages=0)
            db.add(g)
            db.flush()
            db.add(Job(group_id=g.id, status=JOB_QUEUED, created_at=datetime.now(timezone.utc) + timedelta(seconds=i)))
            gids.append(g.id)
        db.commit()
    a, b = SL(), SL()
    try:
        first = a.execute(select(Job).where(Job.status == JOB_QUEUED).order_by(Job.created_at)
                          .with_for_update(skip_locked=True).limit(1)).scalar_one()
        got = worker.claim_job(b, "test:b")
        assert got is not None and got.id != first.id  # job bị khóa được bỏ qua
        a.rollback()
    finally:
        a.close()
        b.close()
    with SL() as db:
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        for j in db.execute(select(Job).where(Job.group_id.in_(gids))).scalars():
            j.status, j.heartbeat_at, j.attempts = JOB_RUNNING, old, 0
        jobs = db.execute(select(Job).where(Job.group_id.in_(gids)).order_by(Job.created_at)).scalars().all()
        jobs[1].attempts = 3
        db.commit()
        worker.reset_stale_jobs(db, 30)
        db.expire_all()
        j0, j1 = [db.get(Job, j.id) for j in jobs]
        assert j0.status == "queued" and j0.attempts == 1
        assert j1.status == "failed" and j1.attempts == 4
        assert db.get(UploadGroup, j1.group_id).status == "FAILED"
        for j in (j0,):
            j.status = "failed"  # không để worker khác nhặt
        db.commit()


def test_seed_demo_idempotent(env, monkeypatch):
    from app.core.config import get_settings
    from app.models import UploadGroup, User
    from scripts import seed_demo

    s = get_settings()
    monkeypatch.setattr(s, "admin_email", "Seed-Admin@kido-test.vn")
    monkeypatch.setattr(s, "admin_password", "seedpass-123")
    SL = env["SessionLocal"]
    with SL() as db:
        a1 = seed_demo.ensure_admin(db, s.admin_email, s.admin_password)
        a2 = seed_demo.ensure_admin(db, s.admin_email, s.admin_password)
        assert a1.id == a2.id and a1.email == "seed-admin@kido-test.vn" and a1.role == "admin"
        assert a1.email_verified_at is not None
        c1 = seed_demo.seed_demo_groups(db, a1, use_reference=False, limit=2)
        c2 = seed_demo.seed_demo_groups(db, a1, use_reference=False, limit=2)
        assert len(c1) == 2 and c2 == []
        rows = db.query(UploadGroup).filter(UploadGroup.user_id == a1.id).all()
        assert sorted(r.title for r in rows) == sorted(c1) and all(r.use_reference is False for r in rows)
        # các trang theo đúng scan_index và giữ tên gốc
        ug = json.loads((FORM_SAMPLES.parent / "stage2_upload_groups.json").read_text(encoding="utf-8"))
        for r in rows:
            for p in r.pages:
                assert ug["pages"][p.original_filename]["scan_index"] == p.scan_index
        assert db.query(User).filter(User.email == "seed-admin@kido-test.vn").count() == 1
        from app.models import Job
        for r in rows:  # không để lại job queued
            for j in db.query(Job).filter(Job.group_id == r.id):
                j.status = "failed"
        db.commit()
