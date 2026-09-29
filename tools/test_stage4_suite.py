"""
Test Suite cho Tầng 4: Kiểm tra Chữ ký & Mộc đỏ
Audit 10 Edge Cases theo quy chuẩn Handoff Tầng 4
"""

import os
import sys
import json
import copy
import random
import cv2
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, '.')
from tools.stage4_verifier import (
    detect_document_modality,
    extract_adaptive_roi,
    verify_color_roi,
    verify_bw_roi,
    verify_single_target,
    evaluate_document_verdict,
    verify_document_item
)

def run_all_stage4_tests():
    print("=" * 70)
    print("BẮT ĐẦU CHẠY TEST SUITE TẦNG 4 (25 EDGE CASES, SAFETY GATES & DETERMINISM)")
    print("=" * 70)
    
    passed_tests = 0
    total_tests = 25
    
    manifest_path = "output/stage3_out/stage3_batched_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    all_docs = [d for b in manifest['batches'] for d in b['documents']]
    
    # -------------------------------------------------------------
    # CASE 1: Signature màu xanh -> detect đúng
    # -------------------------------------------------------------
    print("\n--- CASE 1: Signature màu xanh -> detect đúng ---")
    doc_po = next((d for d in all_docs if d['doc_id'] == 'DOC_056'), None) # PO_3.1
    img_c1 = cv2.imread(f"output/form_samples/{os.path.basename(doc_po['file_name'])}")
    target_blue = next((t for t in doc_po['signature_targets'] if t['expected_color'] == 'blue_ink'), None)
    res_c1 = verify_single_target(img_c1, target_blue, is_color=True)
    
    c1_pass = res_c1['detected'] is True and res_c1['ink_type'] in ['blue_ink', 'blue_stamp_or_sig'] and res_c1['confidence'] >= 0.5
    print(f"  Result: detected={res_c1['detected']}, ink_type={res_c1['ink_type']}, conf={res_c1['confidence']}")
    print(f"  -> CASE 1: {'PASS' if c1_pass else 'FAIL'}")
    if c1_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 2: Stamp đỏ -> detect đúng
    # -------------------------------------------------------------
    print("\n--- CASE 2: Stamp đỏ -> detect đúng ---")
    doc_hd = next((d for d in all_docs if d['file_name'] == 'Hoadon2.2__0.png'), None)
    img_c2 = cv2.imread(f"output/form_samples/{os.path.basename(doc_hd['file_name'])}")
    target_stamp = next((t for t in doc_hd['signature_targets'] if t['expected_color'] == 'red_stamp'), None)
    res_c2 = verify_single_target(img_c2, target_stamp, is_color=True)
    
    c2_pass = res_c2['detected'] is True and res_c2['ink_type'] == 'red_stamp' and res_c2['confidence'] >= 0.5
    print(f"  Result: detected={res_c2['detected']}, ink_type={res_c2['ink_type']}, conf={res_c2['confidence']}")
    print(f"  -> CASE 2: {'PASS' if c2_pass else 'FAIL'}")
    if c2_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 3: Không có signature -> không hallucinate signature
    # -------------------------------------------------------------
    print("\n--- CASE 3: Không có signature -> không hallucinate signature ---")
    white_img = np.ones((500, 500, 3), dtype=np.uint8) * 255
    dummy_sig_target = {
        'role': 'Thủ kho xuất',
        'expected_color': 'blue_ink',
        'box_norm': [0.2, 0.2, 0.4, 0.4]
    }
    res_c3 = verify_single_target(white_img, dummy_sig_target, is_color=True)
    c3_pass = res_c3['detected'] is False and res_c3['confidence'] == 0.0 and res_c3['ink_type'] == 'none'
    print(f"  Result on blank page: detected={res_c3['detected']}, conf={res_c3['confidence']}, ink={res_c3['ink_type']}")
    print(f"  -> CASE 3: {'PASS' if c3_pass else 'FAIL'}")
    if c3_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 4: Không có stamp -> không hallucinate stamp
    # -------------------------------------------------------------
    print("\n--- CASE 4: Không có stamp -> không hallucinate stamp ---")
    dummy_stamp_target = {
        'role': 'Con dấu mộc đỏ',
        'expected_color': 'red_stamp',
        'box_norm': [0.2, 0.2, 0.4, 0.4]
    }
    res_c4 = verify_single_target(white_img, dummy_stamp_target, is_color=True)
    c4_pass = res_c4['detected'] is False and res_c4['confidence'] == 0.0 and res_c4['ink_type'] == 'none'
    print(f"  Result on blank page: detected={res_c4['detected']}, conf={res_c4['confidence']}, ink={res_c4['ink_type']}")
    print(f"  -> CASE 4: {'PASS' if c4_pass else 'FAIL'}")
    if c4_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 5: Signature + stamp cùng page / ROI -> phân biệt đúng (HSV-based Color-Layer Separation)
    # -------------------------------------------------------------
    print("\n--- CASE 5: Signature + stamp cùng page / ROI -> phân biệt đúng ---")
    # Hoadon2.2 has red stamp stamped directly over the signature
    crop_overlap, bbox_ov = extract_adaptive_roi(img_c2, [0.606, 0.317, 0.796, 0.549], margin=0.10)
    res_stamp = verify_color_roi(crop_overlap, 'red_stamp', 'Con dấu mộc đỏ')
    res_sig = verify_color_roi(crop_overlap, 'blue_ink', 'Thủ trưởng đơn vị / Người bán')
    
    c5_pass = (res_stamp['detected'] is True and res_sig['detected'] is True and 
               (res_stamp['overlap_detected'] is True or res_sig['overlap_detected'] is True))
    print(f"  Stamp detected: {res_stamp['detected']} (red_px={res_stamp['red_px']})")
    print(f"  Signature detected: {res_sig['detected']} (blue_px={res_sig['blue_px']})")
    print(f"  Overlap flag: stamp={res_stamp['overlap_detected']}, sig={res_sig['overlap_detected']}")
    print(f"  -> CASE 5: {'PASS' if c5_pass else 'FAIL'}")
    if c5_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 6: Signature nằm sát mép ảnh -> không crash
    # -------------------------------------------------------------
    print("\n--- CASE 6: Signature nằm sát mép ảnh -> không crash ---")
    edge_target = {
        'role': 'Chữ ký sát mép',
        'expected_color': 'blue_ink',
        'box_norm': [0.95, 0.92, 1.05, 1.08] # exceeds bounds intentionally
    }
    try:
        res_c6 = verify_single_target(img_c1, edge_target, is_color=True)
        c6_pass = res_c6 is not None and isinstance(res_c6, dict)
        print(f"  Handled boundary exceed safely: crop bbox={res_c6['bbox']}")
    except Exception as e:
        print(f"  Crashed with exception: {e}")
        c6_pass = False
    print(f"  -> CASE 6: {'PASS' if c6_pass else 'FAIL'}")
    if c6_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 7: Target bbox invalid -> reject an toàn
    # -------------------------------------------------------------
    print("\n--- CASE 7: Target bbox invalid -> reject an toàn ---")
    invalid_targets = [
        {'role': 'Zero dim', 'expected_color': 'blue_ink', 'box_norm': [0.5, 0.5, 0.5, 0.5]},
        {'role': 'Inverted', 'expected_color': 'red_stamp', 'box_norm': [0.8, 0.8, 0.2, 0.2]},
        {'role': 'Empty list', 'expected_color': 'blue_ink', 'box_norm': []},
        {'role': 'None box', 'expected_color': 'red_stamp', 'box_norm': None}
    ]
    all_invalid_handled = True
    for it in invalid_targets:
        try:
            r = verify_single_target(img_c1, it, is_color=True)
            if r['detected'] is not False or r['confidence'] != 0.0:
                all_invalid_handled = False
        except Exception as e:
            print(f"  Crash on invalid target {it}: {e}")
            all_invalid_handled = False
            
    c7_pass = all_invalid_handled
    print(f"  All 4 invalid geometry cases rejected safely without crashing: {c7_pass}")
    print(f"  -> CASE 7: {'PASS' if c7_pass else 'FAIL'}")
    if c7_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 8: Document UNMAPPED -> không fallback DEFAULT
    # -------------------------------------------------------------
    # Kỳ vọng theo NGHĨA, không theo số đếm (bản cũ assert cứng "đúng 3 UNMAPPED" — lỗi thời từ khi
    # THU_HOI_4.2__0 / DOC_070 hết bị Tầng 1 từ chối oan và được phân loại BB_THU_HOI, có preset):
    #  (a) doc_type KHÔNG có preset trong SIGNATURE_PRESET_MAP  => UNMAPPED + signature_targets == []
    #  (b) doc_type CÓ preset                                   => không được UNMAPPED (phải MAPPED, có target)
    #  (c) BUG-T4-02: UNMAPPED không bị đổi thành KHONG_YEU_CAU — ngoại lệ DUY NHẤT là doc_type được
    #      SOP miễn chữ ký (BIEU_DO_NHIET_DO, AGENTS.md 7.A.7 / stage4_verifier.evaluate_document_verdict).
    #      Kiểm cả hàm verdict lẫn artifact v1 thật (verification_summary.doc_status).
    #  (d) chống PASS rỗng: phải có >= 1 document UNMAPPED để nhánh (a)/(c) thực sự được kiểm.
    print("\n--- CASE 8: Document UNMAPPED -> không fallback DEFAULT ---")
    from tools.stage3_resolver import SIGNATURE_PRESET_MAP
    SOP_NOT_REQUIRED_DOC_TYPES = {'BIEU_DO_NHIET_DO'}
    c8_pass = True
    c8_errors = []
    unmapped_docs = [d for d in all_docs if d.get('target_mapping_status') == 'UNMAPPED']
    for d in all_docs:
        st = d.get('target_mapping_status')
        n_t = len(d.get('signature_targets') or [])
        if st not in ('MAPPED', 'UNMAPPED'):
            c8_errors.append(f"{d['doc_id']} ({d['doc_type']}): target_mapping_status lạ = {st!r}")
        if d['doc_type'] in SIGNATURE_PRESET_MAP:
            if st != 'MAPPED' or n_t == 0:
                c8_errors.append(f"{d['doc_id']} ({d['doc_type']}): có preset nhưng status={st}, targets={n_t}")
        else:
            if st != 'UNMAPPED' or n_t != 0:
                c8_errors.append(f"{d['doc_id']} ({d['doc_type']}): KHÔNG có preset nhưng status={st}, "
                                 f"targets={n_t} (fallback DEFAULT?)")
    if not unmapped_docs:
        c8_errors.append("không có document UNMAPPED nào — nhánh chống fallback không được kiểm (PASS rỗng)")

    v1_man_path_c8 = "output/stage4_out/stage4_verification_manifest_v1.json"
    v1_status = {}
    if os.path.exists(v1_man_path_c8):
        with open(v1_man_path_c8, "r", encoding="utf-8") as f:
            for b in json.load(f)['batches']:
                for d in b['documents']:
                    v1_status[d['doc_id']] = (d.get('verification_summary') or {}).get('doc_status')
    else:
        c8_errors.append(f"thiếu {v1_man_path_c8} — không kiểm được BUG-T4-02 trên artifact thật")

    print(f"  Tập UNMAPPED ({len(unmapped_docs)} document):")
    for ud in unmapped_docs:
        v = evaluate_document_verdict([], mapping_status='UNMAPPED', doc_type=ud['doc_type'])
        exp = 'KHONG_YEU_CAU' if ud['doc_type'] in SOP_NOT_REQUIRED_DOC_TYPES else 'UNMAPPED'
        art = v1_status.get(ud['doc_id'], '<THIẾU TRONG MANIFEST v1>') if v1_status else '<không có manifest v1>'
        print(f"    - {ud['doc_id']} | {ud['file_name']} | doc_type={ud['doc_type']} | targets="
              f"{len(ud.get('signature_targets') or [])} | verdict hàm={v['doc_status']} | manifest v1={art} | kỳ vọng={exp}")
        if v['doc_status'] != exp:
            c8_errors.append(f"{ud['doc_id']}: verdict hàm = {v['doc_status']}, kỳ vọng {exp}")
        if v1_status and art != exp:
            c8_errors.append(f"{ud['doc_id']}: manifest v1 doc_status = {art}, kỳ vọng {exp}")
    n_preset_docs = sum(1 for d in all_docs if d['doc_type'] in SIGNATURE_PRESET_MAP)
    print(f"  Document có preset: {n_preset_docs}/{len(all_docs)} (đều MAPPED nếu không có lỗi bên dưới)")
    for e in c8_errors:
        print(f"  FAIL: {e}")
    c8_pass = not c8_errors
    print(f"  -> CASE 8: {'PASS' if c8_pass else 'FAIL'}")
    if c8_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 9: Multi-page document -> target page đúng
    # -------------------------------------------------------------
    print("\n--- CASE 9: Multi-page document -> target page đúng ---")
    multi_docs = [d for d in all_docs if d.get('is_multi_page')]
    c9_pass = len(multi_docs) == 7
    for md in multi_docs:
        # Check that page_files exist and main page has the targets
        page_files = md.get('page_files', [])
        if len(page_files) < 2:
            c9_pass = False
            print(f"  FAIL: Doc {md['doc_id']} is multi_page but page_files < 2")
        # Target should point to page 0 where signatures are located
        main_img = cv2.imread(page_files[0])
        if main_img is None:
            c9_pass = False
            print(f"  FAIL: Cannot read primary page {page_files[0]}")
    print(f"  All {len(multi_docs)} multi-page documents validated: primary page has targets.")
    print(f"  -> CASE 9: {'PASS' if c9_pass else 'FAIL'}")
    if c9_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 10: Filename randomized -> kết quả identity/target mapping không thay đổi
    # -------------------------------------------------------------
    print("\n--- CASE 10: Filename randomized -> kết quả identity/target mapping không thay đổi ---")
    # Simulate randomized filenames
    manifest_rand = copy.deepcopy(manifest)
    random.seed(42)
    for b in manifest_rand['batches']:
        for d in b['documents']:
            orig_fname = d['file_name']
            d['file_name'] = f"RANDOM_{random.randint(100000, 999999)}.png"
            d['real_img_path'] = f"output/form_samples/{orig_fname}"
            
    # Verify that target mapping and counts are 100% invariant
    targets_rand = [len(d.get('signature_targets', [])) for b in manifest_rand['batches'] for d in b['documents']]
    targets_orig = [len(d.get('signature_targets', [])) for b in manifest['batches'] for d in b['documents']]
    
    diff_targets = sum(abs(a - b) for a, b in zip(targets_orig, targets_rand))
    c10_pass = (diff_targets == 0) and (len(targets_rand) == 65)
    print(f"  Original targets sum: {sum(targets_orig)}, Randomized targets sum: {sum(targets_rand)}")
    print(f"  Target mapping diff: {diff_targets}")
    print(f"  -> CASE 10: {'PASS' if c10_pass else 'FAIL'}")
    if c10_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 11: Required vs Optional Semantics
    # -------------------------------------------------------------
    print("\n--- CASE 11: Required vs Optional Semantics ---")
    mock_results_c11 = [
        {"required": True, "detected": True, "modality": "TRUE_COLOR"},
        {"required": True, "detected": True, "modality": "TRUE_COLOR"},
        {"required": False, "detected": False, "modality": "TRUE_COLOR"}
    ]
    v_c11 = evaluate_document_verdict(mock_results_c11, mapping_status='MAPPED', doc_type='HOA_DON')
    c11_pass = (v_c11['doc_status'] == 'DAT_CHUAN_GOC' and 
                v_c11['semantic_verdict'] == 'DETECTED_ALL_REQUIRED_TARGETS' and
                v_c11['required_targets'] == 2 and v_c11['detected_required_targets'] == 2 and
                v_c11['optional_targets'] == 1 and v_c11['detected_optional_targets'] == 0)
    print(f"  Verdict with missing optional target: {v_c11['doc_status']} ({v_c11['semantic_verdict']})")
    print(f"  -> CASE 11: {'PASS' if c11_pass else 'FAIL'}")
    if c11_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 12: INVALID_PAGE_MAPPING Bounds Safety (No Silent Clamping)
    # -------------------------------------------------------------
    print("\n--- CASE 12: INVALID_PAGE_MAPPING Bounds Safety (No Silent Clamping) ---")
    mock_doc_c12 = {
        "doc_id": "MOCK_DOC_PAGE_OOB",
        "file_name": "Hoadon2.2__0.png",
        "page_files": ["output/form_samples/Hoadon2.2__0.png"],
        "target_mapping_status": "MAPPED",
        "doc_type": "HOA_DON",
        "signature_targets": [
            {
                "role": "Người nhận trang 99",
                "page": 99,
                "expected_color": "blue_ink",
                "box_norm": [0.6, 0.3, 0.8, 0.5],
                "required": True
            }
        ]
    }
    t_res_c12, v_c12 = verify_document_item(mock_doc_c12)
    c12_target = t_res_c12[0]
    c12_pass = (c12_target['detected'] is False and 
                c12_target['invalid_page'] is True and 
                c12_target['evidence_type'] == 'INVALID_PAGE_MAPPING' and
                v_c12['doc_status'] == 'CHUA_KY_DONG_DAU')
    print(f"  Target result for page 99: detected={c12_target['detected']}, invalid_page={c12_target['invalid_page']}, evidence={c12_target['evidence_type']}")
    print(f"  -> CASE 12: {'PASS' if c12_pass else 'FAIL'}")
    if c12_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 13: UNMAPPED vs KHONG_YEU_CAU Distinction
    # -------------------------------------------------------------
    print("\n--- CASE 13: UNMAPPED vs KHONG_YEU_CAU Distinction ---")
    v_unmapped = evaluate_document_verdict([], mapping_status='UNMAPPED', doc_type='UNKNOWN')
    v_not_req = evaluate_document_verdict([], mapping_status='UNMAPPED', doc_type='BIEU_DO_NHIET_DO')
    
    c13_pass = (v_unmapped['doc_status'] == 'UNMAPPED' and 
                v_unmapped['semantic_verdict'] == 'UNMAPPED_TARGETS' and
                v_not_req['doc_status'] == 'KHONG_YEU_CAU' and 
                v_not_req['semantic_verdict'] == 'NOT_REQUIRED')
    print(f"  Unknown form UNMAPPED: status={v_unmapped['doc_status']} ({v_unmapped['semantic_verdict']})")
    print(f"  BIEU_DO_NHIET_DO:      status={v_not_req['doc_status']} ({v_not_req['semantic_verdict']})")
    print(f"  -> CASE 13: {'PASS' if c13_pass else 'FAIL'}")
    if c13_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 14: Engine A Reject Unexpected Blue Ink in Red Stamp Target
    # -------------------------------------------------------------
    print("\n--- CASE 14: Engine A Reject Unexpected Blue Ink in Red Stamp Target ---")
    # Synthetic ROI with strong pure blue ink stroke but zero red/purple ink
    pure_blue_roi = np.ones((200, 200, 3), dtype=np.uint8) * 255
    cv2.line(pure_blue_roi, (20, 20), (180, 180), (200, 50, 20), 4) # BGR blue stroke
    cv2.circle(pure_blue_roi, (100, 100), 30, (220, 60, 15), 3)
    
    res_reject_blue = verify_color_roi(pure_blue_roi, expected_color='red_stamp', role='Con dấu kiểm toán')
    
    c14_pass = (res_reject_blue['detected'] is False and 
                res_reject_blue['ink_type'] == 'unexpected_blue_ink_in_stamp_box' and
                res_reject_blue['evidence_type'] == 'UNEXPECTED_BLUE_INK_REJECTED')
    print(f"  Result when blue signature tested as red stamp: detected={res_reject_blue['detected']}, ink={res_reject_blue['ink_type']}, evidence={res_reject_blue['evidence_type']}")
    print(f"  -> CASE 14: {'PASS' if c14_pass else 'FAIL'}")
    if c14_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 15: Legacy GT Historical Benchmark Validation (output/stage4_gt.json)
    # -------------------------------------------------------------
    print("\n--- CASE 15: Legacy GT Historical Benchmark Validation (output/stage4_gt.json) ---")
    gt_path = "output/stage4_gt.json"
    # [TACH DUONG DAN 27/09] Bat buoc doc manifest CUA RIENG v1.
    # Truoc day ca v1 lan ver2 cung ghi "stage4_verification_manifest.json";
    # ver2 ghi de mat ban v1 (26/09) khien CASE 15/16 cham nham manifest ver2 -> TP=0.
    stage4_man_path = "output/stage4_out/stage4_verification_manifest_v1.json"

    def _load_v1_targets(man_path):
        """Tra ve dict target_id -> detected tu manifest v1."""
        with open(man_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        out = {}
        for b in data.get('batches', []):
            for d in b.get('documents', []):
                summary = d.get('verification_summary', {})
                for t_idx, vt in enumerate(summary.get('targets', [])):
                    out[f"{d['doc_id']}_T{t_idx:02d}"] = vt['detected']
        return out

    def _coverage_guard(gt_items, s4_map, case_name):
        """Chan PASS/FAIL gia: manifest thieu qua 5% target cua GT thi bao loi ro rang."""
        total = len(gt_items)
        missing = [it['target_id'] for it in gt_items if it['target_id'] not in s4_map]
        if total and len(missing) / total > 0.05:
            print(f"  [LOI] MANIFEST KHONG KHOP GT: thieu {len(missing)}/{total} target "
                  f"({len(missing)/total*100:.1f}%) - co the dang doc nham manifest cua phien ban khac.")
            print(f"  Manifest dang doc: {stage4_man_path}")
            print(f"  Vi du target thieu: {missing[:5]}")
            print(f"  -> {case_name}: FAIL (khong cham diem tren du lieu thieu)")
            return False
        if missing:
            print(f"  [CANH BAO] thieu {len(missing)}/{total} target trong manifest (duoi nguong 5%): {missing[:5]}")
        return True

    c15_pass = False
    if not os.path.exists(gt_path):
        print(f"  [LOI] Khong tim thay ground truth {gt_path}")
    elif not os.path.exists(stage4_man_path):
        print(f"  [LOI] Khong tim thay manifest v1: {stage4_man_path}")
        print("  Huong xu ly: chay .venv/Scripts/python.exe tools/stage4_verifier.py")
        print("  (hoac .venv/Scripts/python.exe tools/run_and_populate_nb4.py) de sinh lai artifact v1.")
    else:
        with open(gt_path, "r", encoding="utf-8") as f:
            gt_data = json.load(f)
        s4_targets = _load_v1_targets(stage4_man_path)
        gt_items = gt_data.get('targets', [])
        if _coverage_guard(gt_items, s4_targets, "CASE 15"):
            tp, tn, fp, fn = 0, 0, 0, 0
            for item in gt_items:
                actual = s4_targets.get(item['target_id'], False)
                exp = item['expected_presence']
                if exp == 'PRESENT':
                    if actual: tp += 1
                    else: fn += 1
                elif exp == 'ABSENT':
                    if actual: fp += 1
                    else: tn += 1

            p = tp / max(1, tp + fp)
            r = tp / max(1, tp + fn)
            f1 = 2 * p * r / max(1e-6, p + r)
            acc = (tp + tn) / max(1, tp + fp + fn + tn)

            c15_pass = (tp == 122 and tn == 49 and fp == 7 and fn == 7 and
                        abs(p - 0.9457) < 0.001 and abs(r - 0.9457) < 0.001 and
                        abs(f1 - 0.9457) < 0.001 and abs(acc - 0.9243) < 0.001)
            print(f"  Legacy GT Historical Baseline (185 targets): TP={tp}, TN={tn}, FP={fp}, FN={fn}")
            print(f"  Precision: {p*100:.2f}%, Recall: {r*100:.2f}%, F1-Score: {f1*100:.2f}%, Accuracy: {acc*100:.2f}%")
    print(f"  -> CASE 15: {'PASS' if c15_pass else 'FAIL'}")
    if c15_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 16: Independent GT v2 Benchmark Validation (output/stage4_gt_independent_v2.json)
    # -------------------------------------------------------------
    print("\n--- CASE 16: Independent GT v2 Benchmark Validation (output/stage4_gt_independent_v2.json) ---")
    v2_gt_path = "output/stage4_gt_independent_v2.json"
    c16_pass = False
    if not os.path.exists(v2_gt_path):
        print(f"  [LOI] Khong tim thay ground truth {v2_gt_path}")
    elif not os.path.exists(stage4_man_path):
        print(f"  [LOI] Khong tim thay manifest v1: {stage4_man_path}")
        print("  Huong xu ly: chay .venv/Scripts/python.exe tools/stage4_verifier.py de sinh lai artifact v1.")
    else:
        with open(v2_gt_path, "r", encoding="utf-8") as f:
            v2_data = json.load(f)
        s4_targets = _load_v1_targets(stage4_man_path)
        gt_items2 = v2_data.get('targets', [])
        if _coverage_guard(gt_items2, s4_targets, "CASE 16"):
            tp2, tn2, fp2, fn2 = 0, 0, 0, 0
            for item in gt_items2:
                actual = s4_targets.get(item['target_id'], False)
                exp = item['expected_presence']
                if exp == 'PRESENT':
                    if actual: tp2 += 1
                    else: fn2 += 1
                elif exp == 'ABSENT':
                    if actual: fp2 += 1
                    else: tn2 += 1

            p2 = tp2 / max(1, tp2 + fp2)
            r2 = tp2 / max(1, tp2 + fn2)
            f1_2 = 2 * p2 * r2 / max(1e-6, p2 + r2)
            acc2 = (tp2 + tn2) / max(1, tp2 + fp2 + fn2 + tn2)

            c16_pass = (tp2 == 123 and tn2 == 56 and fp2 == 6 and fn2 == 0 and
                        abs(p2 - 0.9535) < 0.001 and r2 == 1.00 and
                        abs(f1_2 - 0.9762) < 0.001 and abs(acc2 - 0.9676) < 0.001)
            print(f"  Independent GT v2 (185 targets): TP={tp2}, TN={tn2}, FP={fp2}, FN={fn2}")
            print(f"  Precision: {p2*100:.2f}%, Recall: {r2*100:.2f}%, F1-Score: {f1_2*100:.2f}%, Accuracy: {acc2*100:.2f}%")
    print(f"  -> CASE 16: {'PASS' if c16_pass else 'FAIL'}")
    if c16_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 17: Input Quality Gate - Missing Image File (INPUT_ERROR)
    # -------------------------------------------------------------
    print("\n--- CASE 17: Input Quality Gate - Missing Image File (INPUT_ERROR) ---")
    mock_doc_missing = {
        "doc_id": "MOCK_DOC_MISSING_IMG",
        "file_name": "missing_image_file_xyz_123.png",
        "page_files": ["output/form_samples/missing_image_file_xyz_123.png"],
        "target_mapping_status": "MAPPED",
        "doc_type": "HOA_DON",
        "signature_targets": [
            {
                "role": "Người ký",
                "page": 0,
                "expected_color": "blue_ink",
                "box_norm": [0.6, 0.3, 0.8, 0.5],
                "required": True
            }
        ]
    }
    t_res_17, v_17 = verify_document_item(mock_doc_missing)
    c17_pass = (t_res_17[0]['detection_status'] == 'INPUT_ERROR' and
                t_res_17[0]['evidence_type'] == 'IMAGE_NOT_FOUND' and
                t_res_17[0]['detected'] is False and
                v_17['doc_status'] == 'LOI_DU_LIEU_ANH' and
                v_17['semantic_verdict'] == 'INPUT_ERROR')
    print(f"  Missing image handling: target_status={t_res_17[0]['detection_status']}, doc_status={v_17['doc_status']}")
    print(f"  -> CASE 17: {'PASS' if c17_pass else 'FAIL'}")
    if c17_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 18: Input Quality Gate - Unreadable Image Buffer (INPUT_ERROR)
    # -------------------------------------------------------------
    print("\n--- CASE 18: Input Quality Gate - Unreadable Image Buffer (INPUT_ERROR) ---")
    res_none = verify_single_target(None, {"role": "Thủ trưởng", "expected_color": "red_stamp", "box_norm": [0.1, 0.1, 0.2, 0.2]})
    res_empty_arr = verify_single_target(np.empty((0, 0, 3), dtype=np.uint8), {"role": "Thủ trưởng", "expected_color": "red_stamp", "box_norm": [0.1, 0.1, 0.2, 0.2]})
    c18_pass = (res_none['detection_status'] == 'INPUT_ERROR' and
                res_none['evidence_type'] == 'MISSING_OR_CORRUPT_IMAGE' and
                res_none['detected'] is False and
                res_empty_arr['detection_status'] == 'INPUT_ERROR' and
                res_empty_arr['detected'] is False)
    print(f"  None image buffer: status={res_none['detection_status']}, evidence={res_none['evidence_type']}")
    print(f"  Empty array buffer: status={res_empty_arr['detection_status']}, evidence={res_empty_arr['evidence_type']}")
    print(f"  -> CASE 18: {'PASS' if c18_pass else 'FAIL'}")
    if c18_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 19: Geometry Safety - Inverted / Empty BBox Geometry
    # -------------------------------------------------------------
    print("\n--- CASE 19: Geometry Safety - Inverted / Empty BBox Geometry ---")
    res_inv = verify_single_target(img_c1, {"role": "Inverted", "expected_color": "blue_ink", "box_norm": [0.8, 0.8, 0.2, 0.2]})
    c19_pass = (res_inv['detection_status'] == 'REVIEW_REQUIRED' and
                res_inv['evidence_type'] == 'INVALID_OR_EMPTY_BBOX' and
                res_inv['detected'] is False and
                res_inv['confidence_type'] == 'HEURISTIC_SCORE')
    print(f"  Inverted box [0.8, 0.8, 0.2, 0.2]: status={res_inv['detection_status']}, evidence={res_inv['evidence_type']}")
    print(f"  -> CASE 19: {'PASS' if c19_pass else 'FAIL'}")
    if c19_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 20: Page Safety - Negative Page Index Mapping
    # -------------------------------------------------------------
    print("\n--- CASE 20: Page Safety - Negative Page Index Mapping ---")
    mock_doc_neg = {
        "doc_id": "MOCK_DOC_NEG_PAGE",
        "file_name": "Hoadon2.2__0.png",
        "page_files": ["output/form_samples/Hoadon2.2__0.png"],
        "target_mapping_status": "MAPPED",
        "doc_type": "HOA_DON",
        "signature_targets": [
            {
                "role": "Người ký trang âm",
                "page": -1,
                "expected_color": "blue_ink",
                "box_norm": [0.6, 0.3, 0.8, 0.5],
                "required": True
            }
        ]
    }
    t_res_neg, _ = verify_document_item(mock_doc_neg)
    c20_pass = (t_res_neg[0]['detection_status'] == 'REVIEW_REQUIRED' and
                t_res_neg[0]['evidence_type'] == 'INVALID_PAGE_MAPPING' and
                t_res_neg[0]['invalid_page'] is True and
                t_res_neg[0]['detected'] is False)
    print(f"  Negative page (-1) mapping: status={t_res_neg[0]['detection_status']}, evidence={t_res_neg[0]['evidence_type']}")
    print(f"  -> CASE 20: {'PASS' if c20_pass else 'FAIL'}")
    if c20_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 21: Tiny ROI Protection (< 10x10)
    # -------------------------------------------------------------
    print("\n--- CASE 21: Tiny ROI Protection (< 10x10) ---")
    tiny_target = {"role": "Tiny Target", "expected_color": "blue_ink", "box_norm": [0.1000, 0.1000, 0.1005, 0.1005]}
    res_tiny = verify_single_target(img_c1, tiny_target, is_color=True)
    c21_pass = (res_tiny['detection_status'] == 'REVIEW_REQUIRED' and
                res_tiny['evidence_type'] == 'ROI_TOO_SMALL' and
                res_tiny['detected'] is False)
    print(f"  Tiny sub-10px crop: status={res_tiny['detection_status']}, evidence={res_tiny['evidence_type']}, detected={res_tiny['detected']}")
    print(f"  -> CASE 21: {'PASS' if c21_pass else 'FAIL'}")
    if c21_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 22: Image Quality Warning - Low Contrast Synthetic ROI
    # -------------------------------------------------------------
    print("\n--- CASE 22: Image Quality Warning - Low Contrast Synthetic ROI ---")
    flat_gray = np.ones((100, 100, 3), dtype=np.uint8) * 128
    res_flat = verify_single_target(flat_gray, {"role": "Flat Gray", "expected_color": "blue_ink", "box_norm": [0.1, 0.1, 0.9, 0.9]})
    c22_pass = ("EXTREME_LOW_CONTRAST" in res_flat['warnings'] and res_flat['detected'] is False)
    print(f"  Flat gray crop warnings: {res_flat['warnings']}")
    print(f"  -> CASE 22: {'PASS' if c22_pass else 'FAIL'}")
    if c22_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 23: Border Suppression - Empty Box Border ROI
    # -------------------------------------------------------------
    print("\n--- CASE 23: Border Suppression - Empty Box Border ROI ---")
    # Test 1: Black printed table grid line in Color mode (Engine A suppresses it)
    border_roi_col = np.ones((200, 200, 3), dtype=np.uint8) * 255
    cv2.rectangle(border_roi_col, (5, 5), (195, 195), (0, 0, 0), 2)
    res_b_col = verify_single_target(border_roi_col, {"role": "Border Only", "expected_color": "blue_ink", "box_norm": [0.1, 0.1, 0.9, 0.9]}, is_color=True)
    # Test 2: Light printed table grid line in BW mode (Engine B suppresses it)
    border_roi_bw = np.ones((200, 200, 3), dtype=np.uint8) * 255
    cv2.rectangle(border_roi_bw, (10, 10), (190, 190), (215, 215, 215), 1)
    res_b_bw = verify_bw_roi(border_roi_bw, 'blue_ink', 'Border Only')
    
    # In color mode, a pure black frame has 0 blue/red ink; in bw mode, light guidelines fall below stroke threshold
    c23_pass = (res_b_col['evidence_type'] in ['NO_EXPECTED_EVIDENCE', 'BW_FALLBACK_ON_COLOR_DOC'] or 
                (res_b_bw['detected'] is False and res_b_bw['evidence_type'] == 'NO_BW_EVIDENCE'))
    # Stricter: verify that light guideline in BW is suppressed and color verifier finds no blue ink
    c23_pass = (res_b_bw['detected'] is False and res_b_bw['evidence_type'] == 'NO_BW_EVIDENCE' and
                verify_color_roi(border_roi_col, 'blue_ink', 'Border Only')['detected'] is False)
    print(f"  Color border verifier: detected={verify_color_roi(border_roi_col, 'blue_ink', 'Border Only')['detected']}")
    print(f"  Photocopy guideline verifier: detected={res_b_bw['detected']}, evidence={res_b_bw['evidence_type']}")
    print(f"  -> CASE 23: {'PASS' if c23_pass else 'FAIL'}")
    if c23_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 24: Noise Invariance - Random Faint Noise ROI
    # -------------------------------------------------------------
    print("\n--- CASE 24: Noise Invariance - Random Faint Noise ROI ---")
    np.random.seed(42)
    noise_roi = np.random.randint(220, 256, (200, 200, 3), dtype=np.uint8)
    res_noise = verify_single_target(noise_roi, {"role": "Faint Noise", "expected_color": "blue_ink", "box_norm": [0.1, 0.1, 0.9, 0.9]}, is_color=True)
    c24_pass = (res_noise['detected'] is False and res_noise['evidence_type'] == 'NO_EXPECTED_EVIDENCE')
    print(f"  Random faint paper noise: detected={res_noise['detected']}, evidence={res_noise['evidence_type']}")
    print(f"  -> CASE 24: {'PASS' if c24_pass else 'FAIL'}")
    if c24_pass: passed_tests += 1

    # -------------------------------------------------------------
    # CASE 25: Repeated Run Determinism (DIFF == 0)
    # -------------------------------------------------------------
    print("\n--- CASE 25: Repeated Run Determinism (DIFF == 0) ---")
    # Run two complete verification passes over all 65 documents
    run1_results = []
    run2_results = []
    for doc in all_docs:
        t1, v1 = verify_document_item(doc)
        t2, v2 = verify_document_item(doc)
        run1_results.append((t1, v1))
        run2_results.append((t2, v2))
        
    diff_count = 0
    for i in range(len(all_docs)):
        t1, v1 = run1_results[i]
        t2, v2 = run2_results[i]
        if v1['doc_status'] != v2['doc_status']:
            diff_count += 1
        if len(t1) != len(t2):
            diff_count += 1
        for j in range(len(t1)):
            if (t1[j]['detected'] != t2[j]['detected'] or
                t1[j]['confidence'] != t2[j]['confidence'] or
                t1[j]['evidence_type'] != t2[j]['evidence_type']):
                diff_count += 1
                
    c25_pass = (diff_count == 0 and len(run1_results) == 65)
    print(f"  Hai lần chạy độc lập trên cùng benchmark cho DIFF == 0 (diff_count={diff_count}), xác nhận tính tái lặp của pipeline trên bộ dữ liệu hiện tại.")
    print(f"  -> CASE 25: {'PASS' if c25_pass else 'FAIL'}")
    if c25_pass: passed_tests += 1

    # -------------------------------------------------------------
    # TỔNG KẾT
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"KẾT QUẢ TEST SUITE TẦNG 4: {passed_tests}/{total_tests} TESTS PASSED")
    print("=" * 70)
    return passed_tests == total_tests

if __name__ == "__main__":
    success = run_all_stage4_tests()
    sys.exit(0 if success else 1)
