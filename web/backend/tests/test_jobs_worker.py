"""Lớp (a) — worker: percent theo dải, throttle ghi DB, save_results trên result giả (không cần DB)."""
import copy
import json
import math
import uuid
from types import SimpleNamespace

import pytest

from app import worker
from app.models import Page, UploadGroup

from conftest import MANIFEST_V2


def test_percent_bands():
    assert worker.compute_percent("T1", 0, 10) == 0
    assert worker.compute_percent("T1", 10, 10) == 40
    assert worker.compute_percent("T1", 5, 10) == 20
    assert worker.compute_percent("T2", 0, 4) == 40
    assert worker.compute_percent("T2", 4, 4) == 80
    assert worker.compute_percent("T3", 1, 1) == 85
    assert worker.compute_percent("T4", 0, 3) == 85
    assert worker.compute_percent("T4", 3, 3) == 98
    assert worker.compute_percent("SAVE", 1, 1) == 100
    assert worker.compute_percent("T2", 0, 0) == 40            # total 0 ⇒ đầu dải
    assert worker.compute_percent("T1", 99, 10) == 40          # vượt ⇒ kẹp
    with pytest.raises(ValueError):
        worker.compute_percent("T9", 1, 1)


def test_progress_throttle_and_monotonic():
    t = [0.0]
    job = SimpleNamespace(percent=0, stage=None, stage_done=0, stage_total=0, message="", heartbeat_at=None)
    pw = worker.ProgressWriter(None, job, clock=lambda: t[0])
    for i in range(1, 101):  # 100 cập nhật trong 1 giây
        pw("T1", i, 100, "")
        t[0] += 0.01
    assert pw.n_writes <= 3, pw.n_writes  # ≤ 2 lần/giây (+ lần đầu)
    pw.flush()
    assert job.percent == 40 and job.stage == "T1" and job.stage_done == 100
    pw("T1", 0, 10, "")  # lùi giá trị ⇒ percent không giảm
    pw.flush()
    assert job.percent == 40


def _fake_group(fns):
    g = UploadGroup(id=uuid.uuid4(), title="t", status="RUNNING", use_reference=False, n_pages=len(fns))
    g.pages = [Page(id=uuid.uuid4(), scan_index=i, original_filename=f"goc_{i}.png", stored_filename=fn,
                    stored_path=f"/data/uploads/x/{fn}", sha256="0" * 64, mime="image/png", width=10, height=10,
                    size_bytes=1) for i, fn in enumerate(fns)]
    return g


def _fake_result(fns):
    v2 = json.loads(MANIFEST_V2.read_text(encoding="utf-8"))
    lp = [d for d in v2["documents"] if d.get("targets")][: len(fns)]
    s4 = []
    for fn, d in zip(fns, lp):
        r = copy.deepcopy(d)
        r["file_name"] = fn
        s4.append(r)
    return {
        "contract": "web-1.0.0", "group_id": "g", "stage3_scope": "UPLOAD_GROUP",
        "reference": {"enabled": False, "status": "DISABLED"}, "stage1_config": {"a": 1},
        "stage1": [{"file_name": fn, "status": "CANH_BAO", "output": {"image": f"/data/work/g/stage1/{fn}"},
                    "quality_output": {"blur": float("nan")}} for fn in fns],
        "stage2": [{"file_name": fn, "doc_type": "LOADING_PLAN", "system": "MT_BIGC", "page_role": "HEADER",
                    "header_text_preview": "a\x00b"} for fn in fns],
        "stage3_manifest": {"metadata": {"total_batches": 1}, "batches": []},
        "stage4_pages": list(reversed(s4)),  # thứ tự khác trang ⇒ phải ghép theo file_name
        "stage4_dossiers": {"n_dossiers": 0, "summary": {}, "orphan_pages": [], "dossiers": []},
        "timings": {"T1": 1.0, "T2": float("inf")},
    }


def test_save_results_maps_by_file_name():
    fns = ["000_aaaaaaaa.png", "001_bbbbbbbb.png"]
    g = _fake_group(fns)
    res = _fake_result(fns)
    worker.save_results(None, g, res)
    assert g.status == "DONE" and g.error is None and g.finished_at is not None
    assert g.pipeline_contract == "web-1.0.0" and g.reference_info["stage3_scope"] == "UPLOAD_GROUP"
    assert g.timings["T2"] is None  # inf ⇒ null (JSONB không nhận)
    for p in g.pages:
        assert p.s4["file_name"] == p.stored_filename
        assert p.s1["quality_output"]["blur"] is None
        assert "\x00" not in p.s2["header_text_preview"]
        assert p.stage1_image_path == f"/data/work/g/stage1/{p.stored_filename}"
        assert p.doc_type == "LOADING_PLAN" and p.system == "MT_BIGC" and p.s1_status == "CANH_BAO"
        assert p.s4_doc_status == p.s4["doc_status"] and p.batch_id == p.s4["batch_id"]
        assert p.s4_action == p.s4["action"]


def test_save_results_missing_s4_is_explicit_error():
    fns = ["000_aaaaaaaa.png", "001_bbbbbbbb.png"]
    g = _fake_group(fns)
    res = _fake_result(fns)
    res["stage4_pages"] = [r for r in res["stage4_pages"] if r["file_name"] != fns[1]]
    with pytest.raises(worker.SaveResultsError) as e:
        worker.save_results(None, g, res)
    assert fns[1] in str(e.value) and "stage4_pages" in str(e.value)
    assert g.status == "RUNNING" and all(p.s4 is None for p in g.pages)  # không ghi dở dang


def test_save_results_duplicate_file_name_rejected():
    fns = ["000_aaaaaaaa.png"]
    g = _fake_group(fns)
    res = _fake_result(fns)
    res["stage2"] = res["stage2"] * 2
    with pytest.raises(worker.SaveResultsError):
        worker.save_results(None, g, res)


def test_clean_json():
    assert worker._clean_json({"a": [1.0, math.nan, {"b": -math.inf}], "c\x00": "x\x00y"}) == \
        {"a": [1.0, None, {"b": None}], "c": "xy"}


def test_worker_cli_help(capsys):
    with pytest.raises(SystemExit) as e:
        worker.main(["--help"])
    assert e.value.code == 0
    assert "--once" in capsys.readouterr().out
