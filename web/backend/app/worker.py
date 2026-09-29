"""Worker nền — `python -m app.worker [--once]` (SPEC §4).

* Hàng đợi trên PostgreSQL: `SELECT ... FOR UPDATE SKIP LOCKED` (nhiều worker chạy song song an toàn).
* Khởi động: job `running` có heartbeat cũ hơn `job_stale_minutes` ⇒ về `queued` (attempts+1; > 3 ⇒ failed).
* Tiến độ toàn job: T1 0–40 · T2 40–80 · T3 80–85 · T4 85–98 · SAVE 98–100; ghi DB tối đa 2 lần/giây.
  Heartbeat thêm một luồng riêng (phiên DB riêng) để job chạy lâu ở một bước không bị coi là treo.
* Pipeline CHỈ gọi qua `app.pipeline.runner.run_upload_group`. Lưu kết quả: `save_results(db, group, result)`.
* Lỗi ⇒ traceback vào `job.error`, group FAILED + `group.error` ngắn tiếng Việt.
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import socket
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

STAGE_BANDS = {"T1": (0, 40), "T2": (40, 80), "T3": (80, 85), "T4": (85, 98), "SAVE": (98, 100)}
STAGE_VI = {"T1": "Chuẩn hóa ảnh", "T2": "Phân loại chứng từ", "T3": "Gom lô", "T4": "Kiểm chữ ký",
            "SAVE": "Lưu kết quả"}
PROGRESS_MIN_INTERVAL = 0.5          # giây — ghi DB tối đa 2 lần/giây
HEARTBEAT_INTERVAL = 15.0            # giây
MAX_ATTEMPTS = 3


class SaveResultsError(Exception):
    """Kết quả pipeline không khớp hợp đồng (vd thiếu s4 của một trang) — không bỏ qua im lặng."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:100]


def compute_percent(stage: str, done: int, total: int) -> int:
    """Phần trăm toàn job theo dải của từng bước. Bước lạ ⇒ ValueError (không đoán)."""
    if stage not in STAGE_BANDS:
        raise ValueError(f"Bước tiến độ lạ: {stage!r}")
    lo, hi = STAGE_BANDS[stage]
    if total <= 0:
        frac = 0.0
    else:
        frac = min(max(done / float(total), 0.0), 1.0)
    return int(math.floor(lo + (hi - lo) * frac))


# ---------------------------------------------------------------------------------------------------
# Làm sạch JSON cho JSONB (Postgres không nhận NaN/Infinity và ký tự \u0000)
# ---------------------------------------------------------------------------------------------------
def _clean_json(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k).replace("\x00", ""): _clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean_json(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, str):
        return o.replace("\x00", "")
    return o


def _trunc(s: Optional[str], n: int) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= n else s[:n]


# ---------------------------------------------------------------------------------------------------
# Lưu kết quả
# ---------------------------------------------------------------------------------------------------
def save_results(db, group, result: Dict[str, Any]) -> None:
    """Ghi kết quả `run_upload_group` vào group + các page (KHÔNG commit — người gọi commit).

    s1/s2/s4 của trang lấy theo `file_name == page.stored_filename`. Thiếu bản ghi nào ⇒ SaveResultsError.
    """
    from app.models import GROUP_DONE

    pages = sorted(group.pages, key=lambda p: p.scan_index)
    if not pages:
        raise SaveResultsError("Bộ upload không có trang nào")
    by_fn = {}
    for key in ("stage1", "stage2", "stage4_pages"):
        recs = result.get(key)
        if not isinstance(recs, list):
            raise SaveResultsError(f"Kết quả pipeline thiếu '{key}'")
        m = {}
        for r in recs:
            fn = (r or {}).get("file_name")
            if fn in m:
                raise SaveResultsError(f"'{key}' có file_name trùng: {fn}")
            m[fn] = r
        by_fn[key] = m
    missing = {k: [p.stored_filename for p in pages if p.stored_filename not in m] for k, m in by_fn.items()}
    missing = {k: v for k, v in missing.items() if v}
    if missing:
        raise SaveResultsError("Kết quả pipeline thiếu trang: " +
                               "; ".join(f"{k}: {', '.join(v)}" for k, v in missing.items()))
    for p in pages:
        s1 = _clean_json(by_fn["stage1"][p.stored_filename])
        s2 = _clean_json(by_fn["stage2"][p.stored_filename])
        s4 = _clean_json(by_fn["stage4_pages"][p.stored_filename])
        p.s1, p.s2, p.s4 = s1, s2, s4
        p.stage1_image_path = _trunc(((s1.get("output") or {}).get("image")), 1000)
        p.s1_status = _trunc(s1.get("status"), 30)
        p.doc_type = _trunc(s2.get("doc_type"), 60)
        p.system = _trunc(s2.get("system"), 60)
        p.page_role = _trunc(s2.get("page_role"), 30)
        p.batch_id = _trunc(s4.get("batch_id"), 120)
        p.s4_doc_status = _trunc(s4.get("doc_status"), 40)
        p.s4_action = _trunc(s4.get("action"), 30)
    group.stage3_manifest = _clean_json(result.get("stage3_manifest"))
    group.stage4_dossiers = _clean_json(result.get("stage4_dossiers"))
    ref = dict(result.get("reference") or {})
    ref["stage3_scope"] = result.get("stage3_scope")
    ref["stage1_config"] = result.get("stage1_config")
    group.reference_info = _clean_json(ref)
    group.timings = _clean_json(result.get("timings"))
    group.pipeline_contract = _trunc(result.get("contract"), 40)
    group.status = GROUP_DONE
    group.error = None
    group.finished_at = _now()
    if db is not None:
        db.flush()


# ---------------------------------------------------------------------------------------------------
# Hàng đợi
# ---------------------------------------------------------------------------------------------------
def reset_stale_jobs(db, stale_minutes: int) -> int:
    """Job `running` có heartbeat cũ ⇒ `queued` (attempts+1); quá MAX_ATTEMPTS ⇒ failed. Trả số job xử lý."""
    from sqlalchemy import or_, select

    from app.models import GROUP_FAILED, GROUP_QUEUED, JOB_FAILED, JOB_QUEUED, JOB_RUNNING, Job, UploadGroup

    cutoff = _now() - timedelta(minutes=stale_minutes)
    jobs = db.execute(
        select(Job).where(Job.status == JOB_RUNNING,
                          or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < cutoff))
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for j in jobs:
        g = db.get(UploadGroup, j.group_id)
        j.attempts = (j.attempts or 0) + 1
        j.locked_by = None
        if j.attempts > MAX_ATTEMPTS:
            j.status = JOB_FAILED
            j.finished_at = _now()
            j.error = (j.error or "") + f"\nJob treo quá {MAX_ATTEMPTS} lần (heartbeat cũ hơn {stale_minutes} phút)."
            j.message = "Thất bại: worker dừng giữa chừng quá nhiều lần"
            if g is not None:
                g.status = GROUP_FAILED
                g.error = "Xử lý thất bại: worker dừng giữa chừng quá nhiều lần."
                g.finished_at = _now()
        else:
            j.status = JOB_QUEUED
            j.message = f"Đưa lại vào hàng đợi (lần {j.attempts}) — worker trước dừng giữa chừng"
            if g is not None:
                g.status = GROUP_QUEUED
    db.commit()
    return len(jobs)


def claim_job(db, wid: str):
    """Nhận 1 job queued (cũ nhất) bằng SKIP LOCKED. Trả Job hoặc None. Đã commit."""
    from sqlalchemy import select

    from app.models import GROUP_RUNNING, JOB_QUEUED, JOB_RUNNING, Job, UploadGroup

    job = db.execute(
        select(Job).where(Job.status == JOB_QUEUED).order_by(Job.created_at)
        .with_for_update(skip_locked=True).limit(1)
    ).scalar_one_or_none()
    if job is None:
        db.rollback()
        return None
    now = _now()
    job.status = JOB_RUNNING
    job.locked_by = wid
    job.started_at = now
    job.heartbeat_at = now
    job.stage, job.stage_done, job.stage_total, job.percent = "T1", 0, 0, 0
    job.message = "Bắt đầu xử lý"
    job.error = None
    g = db.get(UploadGroup, job.group_id)
    if g is not None:
        g.status = GROUP_RUNNING
        g.error = None
    db.commit()
    return job


class ProgressWriter:
    """Callback tiến độ cho runner: cập nhật job tối đa 1 lần / PROGRESS_MIN_INTERVAL giây."""

    def __init__(self, db, job, clock=time.monotonic, min_interval: float = PROGRESS_MIN_INTERVAL):
        self.db, self.job, self.clock, self.min_interval = db, job, clock, min_interval
        self._last = None
        self._pending = None
        self.percent = int(job.percent or 0)
        self.stage = job.stage
        self.n_writes = 0

    def __call__(self, stage: str, done: int, total: int, msg: str) -> None:
        pct = max(self.percent, compute_percent(stage, done, total))  # đơn điệu tăng
        self.percent, self.stage = pct, stage
        self._pending = (stage, done, total, msg, pct)
        now = self.clock()
        if self._last is not None and now - self._last < self.min_interval:
            return
        self.flush(now)

    def flush(self, now=None) -> None:
        pend = self._pending
        if pend is None:
            return
        stage, done, total, msg, pct = pend
        j = self.job
        j.stage, j.stage_done, j.stage_total, j.percent = stage, int(done), int(total), int(pct)
        j.message = _trunc(f"{STAGE_VI.get(stage, stage)} {done}/{total}" + (f" — {msg}" if msg else ""), 500)
        j.heartbeat_at = _now()
        if self.db is not None:
            self.db.commit()
        self._last = self.clock() if now is None else now
        self._pending = None
        self.n_writes += 1


class _Heartbeat(threading.Thread):
    """Cập nhật heartbeat_at bằng phiên DB riêng — giữ job 'sống' khi một bước chạy lâu."""

    def __init__(self, job_id, interval: float = HEARTBEAT_INTERVAL):
        super().__init__(daemon=True)
        self.job_id, self.interval = job_id, interval
        self._stop_evt = threading.Event()

    def run(self) -> None:
        from sqlalchemy import update

        from app.core.db import SessionLocal
        from app.models import JOB_RUNNING, Job

        while not self._stop_evt.wait(self.interval):
            try:
                with SessionLocal() as s:
                    s.execute(update(Job).where(Job.id == self.job_id, Job.status == JOB_RUNNING)
                              .values(heartbeat_at=_now()))
                    s.commit()
            except Exception:  # heartbeat hỏng không được làm chết job; lần sau thử lại
                pass

    def stop(self) -> None:
        self._stop_evt.set()


def _short_error_vi(stage: Optional[str], exc: BaseException) -> str:
    where = STAGE_VI.get(stage or "", stage or "không rõ")
    return _trunc(f"Xử lý thất bại ở bước {where}: {type(exc).__name__}: {exc}", 500)


def process_job(db, job, run_fn=None) -> bool:
    """Chạy pipeline cho job đã claim. Trả True nếu DONE. run_fn để test (mặc định run_upload_group)."""
    from app.models import GROUP_FAILED, JOB_DONE, JOB_FAILED, UploadGroup
    from app.services import storage

    settings = get_settings()
    group = db.get(UploadGroup, job.group_id)
    if group is None:
        job.status, job.error, job.finished_at = JOB_FAILED, "Không tìm thấy bộ upload", _now()
        db.commit()
        return False
    job_id, group_id = job.id, group.id
    progress = ProgressWriter(db, job)
    hb = _Heartbeat(job_id)
    hb.start()
    try:
        if run_fn is None:
            from app.pipeline.runner import run_upload_group as run_fn  # noqa: N806
        pages = sorted(group.pages, key=lambda p: p.scan_index)
        payload = [{"path": p.stored_path, "file_name": p.stored_filename, "scan_index": p.scan_index}
                   for p in pages]
        work_dir = storage.group_work_dir(group.id)
        if work_dir.exists():  # chạy lại: bỏ ảnh trung gian cũ để không trỏ nhầm
            shutil.rmtree(storage.safe_data_path(work_dir))
        result = run_fn(pages=payload, group_id=str(group.id), work_dir=work_dir,
                        use_reference=bool(group.use_reference),
                        stage1_workers=int(settings.worker_stage1_processes), progress=progress)
        progress("SAVE", 0, 1, "Lưu kết quả")
        progress.flush()
        save_results(db, group, result)
        job.stage, job.stage_done, job.stage_total, job.percent = "SAVE", 1, 1, 100
        job.status, job.finished_at, job.message = JOB_DONE, _now(), "Hoàn tất"
        job.heartbeat_at = _now()
        db.commit()
        return True
    except BaseException as e:  # noqa: BLE001 — mọi lỗi phải được ghi, kể cả KeyboardInterrupt
        tb = traceback.format_exc()
        stage = progress.stage
        db.rollback()
        j = db.get(type(job), job_id)
        g = db.get(UploadGroup, group_id)
        j.status, j.finished_at, j.error = JOB_FAILED, _now(), tb
        j.message = _trunc(_short_error_vi(stage, e), 500)
        g.status, g.error, g.finished_at = GROUP_FAILED, _short_error_vi(stage, e), _now()
        db.commit()
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return False
    finally:
        hb.stop()


def run_loop(once: bool = False, poll: Optional[float] = None) -> int:
    from app.core.db import SessionLocal

    settings = get_settings()
    poll = settings.worker_poll_seconds if poll is None else poll
    wid = worker_id()
    with SessionLocal() as db:
        n = reset_stale_jobs(db, settings.job_stale_minutes)
        if n:
            print(f"[worker {wid}] đưa lại/đánh lỗi {n} job treo", flush=True)
    print(f"[worker {wid}] sẵn sàng (poll {poll}s, once={once})", flush=True)
    processed = 0
    while True:
        with SessionLocal() as db:
            job = claim_job(db, wid)
            if job is not None:
                t0 = time.time()
                ok = process_job(db, job)
                processed += 1
                print(f"[worker {wid}] job {job.id} group {job.group_id}: {'DONE' if ok else 'FAILED'} "
                      f"({time.time() - t0:.1f}s)", flush=True)
                if once:
                    return 0 if ok else 1
                continue
        if once:
            print(f"[worker {wid}] không có job queued", flush=True)
            return 0
        time.sleep(poll)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.worker", description="Worker xử lý bộ upload KIDO OCR")
    ap.add_argument("--once", action="store_true", help="Xử lý tối đa 1 job rồi thoát (exit 1 nếu job FAILED)")
    ap.add_argument("--poll", type=float, default=None, help="Chu kỳ quét hàng đợi (giây)")
    a = ap.parse_args(argv)
    return run_loop(once=a.once, poll=a.poll)


if __name__ == "__main__":
    sys.exit(main())
