"""
BỘ KIỂM THỬ TỰ ĐỘNG CHO PIPELINE HỢP NHẤT 4 TẦNG (E2E TEST SUITE)
================================================================
Kiểm thử 9 kịch bản tự động trên KidoDocumentPipeline:
1. TEST_HOA_DON_DEFERRED: Hóa đơn -> UNMAPPED/ABSTAIN (zone hóa đơn HOÃN, không gọi resolver hóa đơn)
2. TEST_PHOTO_STAMP: Phiếu photo đen trắng có mộc vuông siêu thị -> DAT_CHUAN_PHOTO
3. TEST_MISSING_SIGNATURE: Chứng từ thiếu chữ ký một số bên -> THIEU_MOT_SO_CHU_KY
4. TEST_LOADING_PLAN_CALIBRATED: Bảng kê xếp hàng KIDO, neo đáy bảng động -> DAT_CHUAN_GOC
5. TEST_SOP_NOT_REQUIRED: Biểu đồ nhiệt độ SOP không cần ký -> KHONG_YEU_CAU
6. TEST_GATE_REJECT: Ảnh trắng/hỏng bị Tầng 1 từ chối sớm -> YEU_CAU_CHUP_LAI
7. TEST_NUMPY_ARRAY_INPUT: Kiểm tra truyền trực tiếp buffer numpy array BGR (PGH3.6__0)
8. TEST_DETERMINISM: Chạy lặp lại 2 lần cho kết quả đồng nhất 100% (DIFF == 0) (PGH3.6__0)
9. TEST_PERFORMANCE: Thời gian xử lý E2E trung bình <= MAX_LATENCY_SEC giây/trang (hiện 8.0s).
   ĐÂY LÀ NGƯỠNG HỒI QUY THEO HIỆN TRẠNG ĐO THỰC TẾ, KHÔNG PHẢI MỤC TIÊU MONG MUỐN.
   Đo trên PGH3.6__0 + Loading_Plan_5.2__0 (có chạy detector thật) - không còn đo trên
   hóa đơn vì HOA_DON nay ABSTAIN sớm, đo trên đó sẽ cho latency thấp giả.
10. TEST_LP_ZONE_ABSTAIN: giả lập resolver trả từng status COLUMN_* (targets []) ->
    CHUA_CHUAN_HOA_VUNG_KY/ABSTAIN, TUYỆT ĐỐI không KHONG_YEU_CAU.
11. TEST_LP_PAGE_1: giả lập PAGE_1_NO_SIGNATURES -> TRANG_1_CHUA_KY/HOP_LE.
12. TEST_LP_REQUIRED_POLICY (Giai đoạn 5): zone THẬT của Loading_Plan_5.2__0, Tầng 2 giả lập
    system MT_COOP / COMMON -> required theo kênh (config/stage4_lp_required_policy.json):
    MT = {Tài xế, Người giao}; kênh chưa rõ = nghiêm nhất {Tài xế, Người giao, Người nhận} + cờ.
13. TEST_LP_ENGINE_V2 (Giai đoạn 5): LOADING_PLAN verify bằng Tầng 4 ver2 (engine v1 bị cấm gọi),
    kết quả ghi `engine = "v2"`; doc_type preset tĩnh (PGH3.6__0) vẫn `engine = "v1"`.
14. TEST_LP_PARITY: E2E vs manifest ver2 (`stage4_verification_manifest_v2.json`) trên mọi trang
    LOADING_PLAN — 14a engine (zone/target/detected), 14b verdict với Tầng 2 artifact tiêm vào,
    14c verdict full pipeline (lệch chỉ chấp nhận khi truy được về Tầng 2, in nguyên văn KNOWN-DIFF).

Kỳ vọng verdict test cũ khi đổi engine LP v1 -> v2 (27/09): TEST 4 (Loading_Plan_5.2__0) và TEST 12
không đổi kỳ vọng — ver2 cho DAT_CHUAN_GOC 3/3 required trên trang này, trùng manifest ver2.
TEST 9 nay đo latency có engine v2 cho trang LP (ngưỡng 8.0s giữ nguyên).

Cơ chế đếm: mỗi test chạy trong try/except riêng (hàm `_run`). Test ném exception
(AssertionError hoặc lỗi runtime) đều bị tính FAIL. `run_test_suite()` trả về
False nếu có bất kỳ test nào fail, và `__main__` thoát với exit code 1.

Tác giả: Antigravity Tester Agent
"""

import sys
import os
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import cv2
import numpy as np
from tools.kido_pipeline import KidoDocumentPipeline, KidoPipelineConfig, draw_visual_inspection

# Ngưỡng hiệu năng E2E thực đo trên máy dev (KHÔNG phải mục tiêu mong muốn).
# Đo ngày 2026-09-27 sau khi nối Channel-Aware Invoice Resolver vào orchestrator:
# 4 lần đo x 3 vòng trên Hoadon2.2__0.png cho 5.75 / 5.83 / 5.89 / 6.36 s/trang.
# [27/09] HOA_DON nay ABSTAIN sớm nên TEST 9 đo trên PGH3.6__0 + Loading_Plan_5.2__0; ngưỡng GIỮ NGUYÊN.
# Đặt trần 8.0s/trang (biên ~25%) để bắt hồi quy thật sự mà không FAIL oan do nhiễu máy.
MAX_LATENCY_SEC = 8.0

_RESULTS = []


def _run(name, fn):
    """Chạy 1 test, đếm pass/fail THẬT. Trả về giá trị của fn, hoặc None nếu FAIL."""
    print("\n--- " + name + " ---")
    try:
        val = fn()
        _RESULTS.append((name, True, None))
        return val
    except Exception as exc:
        _RESULTS.append((name, False, "{}: {}".format(type(exc).__name__, exc)))
        print("  [FAIL] {}: {}: {}".format(name, type(exc).__name__, exc))
        return None


def run_test_suite():
    print("=" * 80)
    print("BẮT ĐẦU CHẠY TEST SUITE E2E CHO PIPELINE HỢP NHẤT 4 TẦNG (TESTER AGENT)")
    print("=" * 80)

    _RESULTS.clear()
    pipeline = KidoDocumentPipeline()

    t1_path = "output/form_samples/Hoadon2.2__0.png"
    # Ảnh dùng cho numpy/tất định/hiệu năng: đi qua preset tĩnh + detector thật.
    t_real_path = "output/form_samples/PGH3.6__0.png"
    t_lp_path = "output/form_samples/Loading_Plan_5.2__0.png"

    # --- TEST 1: TEST_HOA_DON_DEFERRED ---
    def test_1():
        import tools.kido_pipeline as kp

        def _forbidden(*a, **k):
            raise AssertionError("HOA_DON khong duoc goi detect_invoice_signature_zone (zone hoan)")

        orig = kp.detect_invoice_signature_zone
        kp.detect_invoice_signature_zone = _forbidden
        try:
            r1 = pipeline.process_document(t1_path)
        finally:
            kp.detect_invoice_signature_zone = orig
        s4 = r1["stage4"]
        assert r1["status"] == "THANH_CONG", "Loi status: " + str(r1["status"])
        assert r1["stage2"]["doc_type"] == "HOA_DON", "Loi doc_type: " + str(r1["stage2"]["doc_type"])
        assert s4["overall_verdict"] == "UNMAPPED", "Loi verdict: " + str(s4["overall_verdict"])
        assert s4["action"] == "ABSTAIN", "Loi action: " + str(s4["action"])
        assert r1["stage3"]["mapping_status"] == "UNMAPPED", "Loi mapping: " + str(r1["stage3"]["mapping_status"])
        assert r1["stage3"]["zone_status"] == "HOA_DON_ZONE_DEFERRED", "Loi zone_status"
        assert s4["target_results"] == [] and r1["stage3"]["targets"] == [], \
            "HOA_DON khong duoc co target (khong fallback preset tinh)"
        assert "hoãn" in (s4["abstain_reason"] or ""), "Thieu ly do: " + str(s4["abstain_reason"])
        print("  [PASS] {} -> {} | {} / {} ({})".format(
            t1_path, r1["stage2"]["doc_type"], s4["overall_verdict"], s4["action"], s4["abstain_reason"]))
        return r1

    _run("TEST 1: Hóa đơn -> UNMAPPED/ABSTAIN (zone hóa đơn hoãn)", test_1)

    # --- TEST 2: TEST_PHOTO_STAMP ---
    def test_2():
        t2_path = "output/form_samples/PGH3.6__0.png"
        r2 = pipeline.process_document(t2_path)
        s4 = r2["stage4"]
        assert r2["status"] == "THANH_CONG", "Loi status: " + str(r2["status"])
        assert r2["stage2"]["doc_type"] in ["PHIEU_NHAP_KHO", "PHIEU_GIAO_HANG"], \
            "Loi doc_type: " + str(r2["stage2"]["doc_type"])
        assert s4["overall_verdict"] == "DAT_CHUAN_PHOTO", "Loi verdict: " + str(s4["overall_verdict"])
        print("  [PASS] {} -> {} | {}".format(t2_path, r2["stage2"]["doc_type"], s4["overall_verdict"]))

    _run("TEST 2: Phiếu giao hàng photo đen trắng có mộc siêu thị", test_2)

    # --- TEST 3: TEST_MISSING_SIGNATURE ---
    def test_3():
        t3_path = "output/form_samples/BB_NO_HANG__0.png"
        r3 = pipeline.process_document(t3_path)
        s4 = r3["stage4"]
        assert r3["status"] == "THANH_CONG", "Loi status: " + str(r3["status"])
        assert s4["overall_verdict"] == "THIEU_MOT_SO_CHU_KY", "Loi verdict: " + str(s4["overall_verdict"])
        print("  [PASS] {} -> {} | {} ({})".format(
            t3_path, r3["stage2"]["doc_type"], s4["overall_verdict"], s4["verdict_title"]))

    _run("TEST 3: Biên bản thiếu một số chữ ký / con dấu", test_3)

    # --- TEST 4: TEST_LOADING_PLAN_CALIBRATED ---
    def test_4():
        t4_path = "output/form_samples/Loading_Plan_5.2__0.png"
        r4 = pipeline.process_document(t4_path)
        s4 = r4["stage4"]
        assert r4["status"] == "THANH_CONG", "Loi status: " + str(r4["status"])
        assert s4["overall_verdict"] == "DAT_CHUAN_GOC", "Loi verdict: " + str(s4["overall_verdict"])
        assert s4["detected_required_targets"] >= 3, \
            "So vi tri dat qua it: " + str(s4["detected_required_targets"])
        print("  [PASS] {} -> {} | {} ({}/{} vi tri dat)".format(
            t4_path, r4["stage2"]["doc_type"], s4["overall_verdict"],
            s4["detected_required_targets"], r4["stage3"]["required_targets"]))

    _run("TEST 4: Bảng kê xếp hàng KIDO với neo đáy bảng động", test_4)

    # --- TEST 5: TEST_SOP_NOT_REQUIRED ---
    def test_5():
        t5_path = "output/form_samples/Bieu_do_nhiet_do__0.png"
        r5 = pipeline.process_document(t5_path)
        s4 = r5["stage4"]
        assert r5["status"] == "THANH_CONG", "Loi status: " + str(r5["status"])
        assert s4["overall_verdict"] == "KHONG_YEU_CAU", "Loi verdict: " + str(s4["overall_verdict"])
        assert s4["total_required_targets"] == 0, "Loi total_required: " + str(s4["total_required_targets"])
        print("  [PASS] {} -> {} | {} (NOT_REQUIRED)".format(
            t5_path, r5["stage2"]["doc_type"], s4["overall_verdict"]))

    _run("TEST 5: Biểu đồ nhiệt độ SOP không yêu cầu chữ ký", test_5)

    # --- TEST 6: TEST_GATE_REJECT ---
    def test_6():
        # Anh trang TONG HOP (xac dinh, seed co dinh). Truoc day test nay dung THU_HOI_4.2__0.png
        # voi gia dinh "anh trang" - SAI: anh do co noi dung; Tang 1 tu choi oan vi do muc tren
        # mat na giay rac (o vang 2.43% khung). Da sua o Tang 1 (27/09) -> anh nay nay qua cong.
        rng6 = np.random.default_rng(20250927)
        blank = np.clip(rng6.normal(242, 3, size=(2200, 1556, 3)), 0, 255).astype(np.uint8)
        t6_path = "synthetic_blank_page.png"
        r6 = pipeline.process_document(blank, file_name=t6_path)
        assert r6["status"] == "YEU_CAU_CHUP_LAI", "Loi status: " + str(r6["status"])
        assert r6["stage1"]["action"] == "YEU_CAU_CHUP_LAI", "Loi action: " + str(r6["stage1"]["action"])
        assert r6["stage4"]["overall_verdict"] == "YEU_CAU_CHUP_LAI", \
            "Loi verdict: " + str(r6["stage4"]["overall_verdict"])
        print("  [PASS] {} -> Tu choi som an toan ({}) trong {}s".format(
            t6_path, r6["stage1"]["action"], r6["elapsed_sec"]))

    _run("TEST 6: Ảnh lỗi / trắng gác cổng Tầng 1 từ chối sớm", test_6)

    # --- TEST 7: TEST_NUMPY_ARRAY_INPUT ---
    def test_7():
        raw_img = cv2.imread(t_real_path)
        assert raw_img is not None, "Khong doc duoc anh: " + t_real_path
        r_path = pipeline.process_document(t_real_path)
        r7 = pipeline.process_document(raw_img, file_name="in_memory_test.png")
        s4 = r7["stage4"]
        assert r7["status"] == "THANH_CONG", "Loi status: " + str(r7["status"])
        assert r7["stage2"]["doc_type"] == r_path["stage2"]["doc_type"], \
            "Loi doc_type: {} vs {}".format(r7["stage2"]["doc_type"], r_path["stage2"]["doc_type"])
        assert s4["overall_verdict"] == "DAT_CHUAN_PHOTO", "Loi verdict: " + str(s4["overall_verdict"])
        assert s4["overall_verdict"] == r_path["stage4"]["overall_verdict"], "numpy vs path lech verdict"
        print("  [PASS] Array input {} -> {} | {}".format(
            raw_img.shape, r7["stage2"]["doc_type"], s4["overall_verdict"]))

    _run("TEST 7: Truyền trực tiếp numpy array BGR", test_7)

    # --- TEST 8: TEST_DETERMINISM ---
    def test_8():
        run_a = pipeline.process_document(t_real_path)
        run_b = pipeline.process_document(t_real_path)
        ta = run_a["stage4"]["target_results"]
        tb = run_b["stage4"]["target_results"]
        assert run_a["stage2"]["doc_type"] == run_b["stage2"]["doc_type"], "doc_type khong tat dinh"
        assert run_a["stage4"]["overall_verdict"] == run_b["stage4"]["overall_verdict"], "verdict khong tat dinh"
        assert len(ta) == len(tb), "so luong target khong tat dinh"
        assert len(ta) > 0, "Test tat dinh vo nghia khi khong co target nao"
        for idx in range(len(ta)):
            assert ta[idx]["detected"] == tb[idx]["detected"], "target[{}].detected lech".format(idx)
            assert ta[idx]["ink_type"] == tb[idx]["ink_type"], "target[{}].ink_type lech".format(idx)
        print("  [PASS] Hai lan chay doc lap tren cung 1 anh cho ket qua hoan toan trung khop (DIFF == 0)")

    _run("TEST 8: Tính tất định & tái lặp (DIFF == 0)", test_8)

    # --- TEST 9: TEST_PERFORMANCE ---
    def test_9():
        t_start = time.time()
        n_runs = 0
        for _ in range(2):
            for pth in (t_real_path, t_lp_path):
                r = pipeline.process_document(pth)
                assert len(r["stage4"]["target_results"]) > 0, \
                    "Anh do hieu nang khong chay detector: " + pth
                n_runs += 1
        avg_latency = (time.time() - t_start) / n_runs
        print("  Thoi gian xu ly trung binh E2E: {:.2f}s/trang (nguong hoi quy <= {:.1f}s)".format(
            avg_latency, MAX_LATENCY_SEC))
        assert avg_latency <= MAX_LATENCY_SEC, \
            "HOI QUY HIEU NANG: {:.2f}s/trang > nguong {:.1f}s/trang".format(avg_latency, MAX_LATENCY_SEC)
        print("  [PASS] Dat nguong hoi quy hieu nang ({:.2f}s <= {:.1f}s)".format(avg_latency, MAX_LATENCY_SEC))

    _run("TEST 9: Hiệu năng & độ trễ xử lý (Latency Check)", test_9)

    # --- TEST 10/11: TIÊU THỤ ABSTAIN CỦA TẦNG 3B (giả lập resolver) ---
    import tools.kido_pipeline as kp

    class _FixedLPClassifier:
        """Giả lập Tầng 2 trả LOADING_PLAN để test cô lập đúng nhánh cổng Tầng 3b."""
        def __init__(self, role, system="COMMON"):
            self.role = role
            self.system = system

        def classify_document(self, *a, **k):
            return {"doc_type": "LOADING_PLAN", "system": self.system,
                    "confidence": 1.0, "page_role": self.role, "key_fields": {}}

    def _with_fake_zone(zone, role="HEADER"):
        orig_zone = kp.detect_loading_plan_signature_zone
        orig_cls = pipeline.classifier
        kp.detect_loading_plan_signature_zone = lambda img, page_role="HEADER": dict(zone)
        pipeline.classifier = _FixedLPClassifier(role)
        try:
            return pipeline.process_document(t_lp_path)
        finally:
            kp.detect_loading_plan_signature_zone = orig_zone
            pipeline.classifier = orig_cls

    abstain_statuses = [
        "COLUMN_DETECTION_FAILED", "COLUMN_ORDER_VIOLATION", "COLUMN_PITCH_IMPLAUSIBLE",
        "COLUMN_OCR_UNAVAILABLE", "COLUMN_LABELS_UNAVAILABLE",
        "SOME_FUTURE_UNKNOWN_STATUS",
    ]
    for st in abstain_statuses:
        def test_abstain(st=st):
            r = _with_fake_zone({"has_signatures": False, "anchor_y": 0.6, "status": st,
                                 "description": "gia lap " + st, "targets": []})
            s4 = r["stage4"]
            assert r["status"] == "THANH_CONG", "Loi status: " + str(r["status"])
            assert s4["overall_verdict"] != "KHONG_YEU_CAU", "PASS GIA: ABSTAIN bi cham KHONG_YEU_CAU"
            assert s4["overall_verdict"] == "CHUA_CHUAN_HOA_VUNG_KY", "Loi verdict: " + str(s4["overall_verdict"])
            assert s4["action"] == "ABSTAIN", "Loi action: " + str(s4["action"])
            assert r["stage3"]["zone_status"] == st, "Mat zone_status: " + str(r["stage3"]["zone_status"])
            assert st in (s4["abstain_reason"] or ""), "abstain_reason khong ghi zone_status"
            assert s4["target_results"] == [], "Khong duoc verify target khi ABSTAIN"
            print("  [PASS] {} -> {} / {}".format(st, s4["overall_verdict"], s4["action"]))
        _run("TEST 10: LP resolver {} -> ABSTAIN".format(st), test_abstain)

    def test_abstain_true_but_empty():
        # has_signatures=True nhưng targets rỗng (vi phạm hợp đồng) cũng phải ABSTAIN.
        r = _with_fake_zone({"has_signatures": True, "anchor_y": 0.6,
                             "status": "TABLE_BOTTOM_DETECTED", "targets": []}, role="CONTINUATION")
        s4 = r["stage4"]
        assert s4["overall_verdict"] == "CHUA_CHUAN_HOA_VUNG_KY", "Loi verdict: " + str(s4["overall_verdict"])
        assert s4["action"] == "ABSTAIN", "Loi action: " + str(s4["action"])
        print("  [PASS] has_signatures=True + targets [] -> {}".format(s4["overall_verdict"]))

    _run("TEST 10b: LP has_signatures=True nhưng targets rỗng -> ABSTAIN", test_abstain_true_but_empty)

    def test_11():
        r = _with_fake_zone({"has_signatures": False, "anchor_y": None, "status": "PAGE_1_NO_SIGNATURES",
                             "description": "Trang 1/2 gia lap", "targets": []}, role="HEADER")
        s4 = r["stage4"]
        assert s4["overall_verdict"] == "TRANG_1_CHUA_KY", "Loi verdict: " + str(s4["overall_verdict"])
        assert s4["action"] == "HOP_LE", "Loi action: " + str(s4["action"])
        assert s4["overall_verdict"] != "KHONG_YEU_CAU", "Nhan sai nghia KHONG_YEU_CAU"
        assert s4["target_results"] == [], "Trang 1 khong duoc co target"
        print("  [PASS] PAGE_1_NO_SIGNATURES -> {} / {}".format(s4["overall_verdict"], s4["action"]))

    _run("TEST 11: LP PAGE_1_NO_SIGNATURES -> TRANG_1_CHUA_KY/HOP_LE", test_11)

    # --- TEST 12: chính sách required theo kênh trên đường E2E (zone THẬT, Tầng 2 giả lập system) ---
    def _with_fake_system(system):
        orig_cls = pipeline.classifier
        pipeline.classifier = _FixedLPClassifier("HEADER", system=system)
        try:
            return pipeline.process_document(t_lp_path)
        finally:
            pipeline.classifier = orig_cls

    def test_12():
        exp = {"MT_COOP": ("MT", False, {"Tài xế (Lái xe nhận hàng)", "Người giao / Thủ kho xuất"}),
               "COMMON": ("UNRESOLVED", True, {"Tài xế (Lái xe nhận hàng)", "Người giao / Thủ kho xuất",
                                               "Người nhận hàng"})}
        for system, (ch, unres, req) in exp.items():
            r = _with_fake_system(system)
            pol = r["stage3"]["required_policy"]
            assert pol and pol["policy_channel"] == ch and pol["policy_channel_unresolved"] is unres, pol
            tg = r["stage3"]["targets"]
            assert len(tg) == 5, "zone phai co 5 o (optional van verify + audit): {}".format(len(tg))
            got = {t["role"] for t in tg if t["required"]}
            assert got == req, "required {} != {} (system {})".format(sorted(got), sorted(req), system)
            assert all(str(t.get("required_source", "")).startswith("POLICY") for t in tg), "thieu required_source"
            assert {t["role"] for t in r["stage4"]["target_results"] if t.get("required")} == req,                 "Tang 4 khong dung required cua chinh sach"
            assert r["stage3"]["required_targets"] == len(req), r["stage3"]["required_targets"]
            print("  [PASS] system {} -> kenh {} (unresolved={}) required {} | {}".format(
                system, ch, unres, len(req), r["stage4"]["overall_verdict"]))

    _run("TEST 12: LP required theo kênh (MT / kênh chưa rõ -> nghiêm nhất)", test_12)

    # --- TEST 13: LOADING_PLAN đi Tầng 4 ver2, KHÔNG đi v1; doc_type preset tĩnh vẫn v1 ---
    def test_13():
        def _forbidden_v1(*a, **k):
            raise AssertionError("LOADING_PLAN khong duoc goi engine v1 (stage4_verifier.verify_single_target)")

        orig_v1 = kp.verify_single_target
        kp.verify_single_target = _forbidden_v1
        try:
            r = pipeline.process_document(t_lp_path)
        finally:
            kp.verify_single_target = orig_v1
        s4 = r["stage4"]
        assert r["stage2"]["doc_type"] == "LOADING_PLAN", r["stage2"]["doc_type"]
        assert r["engine"] == "v2" and s4["engine"] == "v2", "engine trang LP: {}".format(r["engine"])
        assert len(s4["target_results"]) > 0, "LP khong co target"
        assert all(t.get("verifier") == "v2" for t in s4["target_results"]), "co target khong qua v2"
        assert s4["action"] == kp._VERDICT_ACTION[s4["overall_verdict"]], (s4["overall_verdict"], s4["action"])
        r_v1 = pipeline.process_document(t_real_path)
        assert r_v1["engine"] == "v1", "PGH (preset tinh) phai la v1: {}".format(r_v1["engine"])
        assert all(t.get("verifier") == "v1" for t in r_v1["stage4"]["target_results"])
        print("  [PASS] {} -> engine v2 ({} target, v1 khong duoc goi) | {} -> engine v1".format(
            t_lp_path, len(s4["target_results"]), t_real_path))

    _run("TEST 13: LOADING_PLAN -> engine v2 (không gọi v1); preset tĩnh -> v1", test_13)

    # --- TEST 14: PARITY E2E vs manifest ver2 trên toàn bộ trang LOADING_PLAN ---
    # Manifest ver2 (generate_nb4_ver2.py Cell 3) đọc ảnh Tầng 1 trên đĩa + Tầng 2 artifact
    # (`stage2_classified_results.json`); E2E chạy lại Tầng 1 + Tầng 2 trên ảnh gốc. Tách 3 phép so:
    #   14a ENGINE (full pipeline, ảnh gốc): zone_status, số target, detected từng target — PHẢI trùng.
    #   14b VERDICT với Tầng 2 artifact tiêm vào (system/page_role của manifest): doc_status, action,
    #       required từng target — PHẢI trùng. Cô lập đúng phần E2E-vs-Cell 3.
    #   14c VERDICT full pipeline: lệch doc_status được IN NGUYÊN VĂN; chỉ được coi là KNOWN-DIFF khi
    #       (i) Tầng 2 của E2E khác artifact trên chính trang đó VÀ (ii) 14b trùng trên trang đó —
    #       tức nguyên nhân nằm ở đầu vào Tầng 2, không ở Tầng 3b/4. Mọi lệch khác -> FAIL.
    manifest_v2_path = "output/stage4_out/stage4_verification_manifest_v2.json"
    import json as _json
    _parity = {}

    def _load_lp_manifest():
        with open(manifest_v2_path, "r", encoding="utf-8") as f:
            man = _json.load(f)
        lp_docs = [d for d in man["documents"] if d["doc_type"] == "LOADING_PLAN"]
        assert lp_docs, "manifest ver2 khong co trang LOADING_PLAN"
        assert len(lp_docs) == man["n_documents_in_scope"], \
            "so trang LP {} != n_documents_in_scope {}".format(len(lp_docs), man["n_documents_in_scope"])
        return lp_docs

    def _det(ts):
        return "".join("1" if t.get("detected") else "0" for t in ts)

    def test_14a():
        lp_docs = _load_lp_manifest()
        diffs = []
        for d in lp_docs:
            fn = d["file_name"]
            r = pipeline.process_document("output/form_samples/" + fn)
            _parity[fn] = r
            tr = r["stage4"]["target_results"]
            probs = []
            if r["stage2"]["doc_type"] != "LOADING_PLAN":
                probs.append("doc_type E2E={} (manifest LOADING_PLAN)".format(r["stage2"]["doc_type"]))
            if r["stage3"]["zone_status"] != d["zone_status"]:
                probs.append("zone_status E2E={} manifest={}".format(r["stage3"]["zone_status"], d["zone_status"]))
            if len(tr) != len(d["targets"]):
                probs.append("so target E2E={} manifest={}".format(len(tr), len(d["targets"])))
            else:
                for i, (te, tm) in enumerate(zip(tr, d["targets"])):
                    if te.get("role") != tm.get("role") or bool(te.get("detected")) != bool(tm.get("detected")):
                        probs.append("target[{}] E2E=({}, detected={}) manifest=({}, detected={})".format(
                            i, te.get("role"), te.get("detected"), tm.get("role"), tm.get("detected")))
            print("  {} {:26s} zone {} | detected E2E {} / manifest {} | engine {}".format(
                "OK  " if not probs else "LECH", fn, r["stage3"]["zone_status"], _det(tr), _det(d["targets"]),
                r.get("engine")))
            if probs:
                diffs.append("{}: {}".format(fn, "; ".join(probs)))
        assert not diffs, "LECH ENGINE {}/{} trang:\n    ".format(len(diffs), len(lp_docs)) + "\n    ".join(diffs)
        print("  [PASS] ENGINE PARITY {}/{} trang LOADING_PLAN (zone_status, so target, detected tung o)".format(
            len(lp_docs), len(lp_docs)))

    def test_14b():
        lp_docs = _load_lp_manifest()
        diffs = []
        orig_cls = pipeline.classifier
        try:
            for d in lp_docs:
                fn = d["file_name"]
                pipeline.classifier = _FixedLPClassifier(d["page_role"], system=d["system"])
                r = pipeline.process_document("output/form_samples/" + fn)
                s4 = r["stage4"]
                tr = s4["target_results"]
                probs = []
                if s4["overall_verdict"] != d["doc_status"]:
                    probs.append("doc_status E2E={} manifest={}".format(s4["overall_verdict"], d["doc_status"]))
                if s4["action"] != d["action"]:
                    probs.append("action E2E={} manifest={}".format(s4["action"], d["action"]))
                if r["stage3"]["zone_status"] != d["zone_status"]:
                    probs.append("zone_status E2E={} manifest={}".format(r["stage3"]["zone_status"], d["zone_status"]))
                if len(tr) != len(d["targets"]):
                    probs.append("so target E2E={} manifest={}".format(len(tr), len(d["targets"])))
                else:
                    for i, (te, tm) in enumerate(zip(tr, d["targets"])):
                        for key in ("role", "required", "detected", "evidence", "review_required"):
                            if te.get(key) != tm.get(key):
                                probs.append("target[{}].{} E2E={} manifest={}".format(i, key, te.get(key), tm.get(key)))
                if d["targets"] and s4["detected_required_targets"] != d["detected_required_targets"]:
                    probs.append("detected_required E2E={} manifest={}".format(
                        s4["detected_required_targets"], d["detected_required_targets"]))
                if probs:
                    diffs.append("{}: {}".format(fn, "; ".join(probs)))
                _parity.setdefault("_14b", {})[fn] = not probs
        finally:
            pipeline.classifier = orig_cls
        assert not diffs, "LECH VERDICT (Tang 2 artifact) {}/{} trang:\n    ".format(len(diffs), len(lp_docs)) + \
            "\n    ".join(diffs)
        print("  [PASS] VERDICT PARITY (Tang 2 artifact tiem vao) {}/{} trang: doc_status, action, "
              "role/required/detected/evidence/review_required tung o".format(len(lp_docs), len(lp_docs)))

    def test_14c():
        lp_docs = _load_lp_manifest()
        assert all(d["file_name"] in _parity for d in lp_docs), "TEST 14a chua chay du trang (FAIL som?)"
        ok_14b = _parity.get("_14b", {})
        unexplained, known = [], []
        for d in lp_docs:
            fn = d["file_name"]
            r = _parity[fn]
            s2e, s4 = r["stage2"], r["stage4"]
            if s4["overall_verdict"] == d["doc_status"] and s4["action"] == d["action"]:
                continue
            line = "{}: doc_status E2E={}/{} manifest={}/{} | Tang 2 E2E system={} page_role={} ; artifact system={} page_role={}".format(
                fn, s4["overall_verdict"], s4["action"], d["doc_status"], d["action"],
                s2e["system"], s2e["page_role"], d["system"], d["page_role"])
            pol = (r["stage3"].get("required_policy") or {})
            line += " | kenh E2E {} (unresolved={})".format(pol.get("policy_channel"), pol.get("policy_channel_unresolved"))
            s2_differs = (s2e["system"] != d["system"] or s2e["page_role"] != d["page_role"])
            if s2_differs and ok_14b.get(fn):
                known.append(line)
            else:
                unexplained.append(line)
        for ln in known:
            print("  [KNOWN-DIFF] " + ln)
        for ln in unexplained:
            print("  [LECH]       " + ln)
        n_same = len(lp_docs) - len(known) - len(unexplained)
        print("  VERDICT full pipeline: trung {}/{} · KNOWN-DIFF (do Tang 2 E2E khac artifact) {} · lech khong giai thich {}".format(
            n_same, len(lp_docs), len(known), len(unexplained)))
        assert not unexplained, "LECH VERDICT KHONG GIAI THICH DUOC {} trang".format(len(unexplained))
        print("  [PASS] moi lech doc_status deu truy duoc ve dau vao Tang 2 (14b trung tren cung trang)")

    _run("TEST 14a: PARITY ENGINE E2E (ảnh gốc, full pipeline) vs manifest ver2 — 19 trang LP", test_14a)
    _run("TEST 14b: PARITY VERDICT E2E (Tầng 2 artifact tiêm vào) vs manifest ver2", test_14b)
    _run("TEST 14c: PARITY VERDICT full pipeline — lệch phải truy được về Tầng 2", test_14c)

    # --- TỔNG KẾT THẬT (đếm từ _RESULTS, không hardcode) ---
    total_tests = len(_RESULTS)
    passed_tests = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = [(n, e) for n, ok, e in _RESULTS if not ok]

    print("\n" + "=" * 80)
    pct = (passed_tests / total_tests * 100.0) if total_tests else 0.0
    print("KẾT QUẢ TEST SUITE E2E: {}/{} TESTS PASSED ({:.1f}%)".format(passed_tests, total_tests, pct))
    if failed:
        print("-" * 80)
        print("DANH SÁCH TEST FAIL:")
        for n, e in failed:
            print("  [FAIL] " + n)
            print("         " + str(e))
    print("=" * 80)
    return len(failed) == 0


if __name__ == "__main__":
    success = run_test_suite()
    if not success:
        sys.exit(1)
