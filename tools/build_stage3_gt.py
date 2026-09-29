"""
build_stage3_gt.py
------------------
Xây dựng Ground Truth Độc Lập cho Tầng 3 (output/stage3_gt.json)
Dựa trên tài liệu nghiệp vụ KIDO gốc (Copy of HUONG DAN CHUNG TU GIAO NHAN.xlsx
và output/form_catalog.json).
"""
import json
import sys
import io
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def build_stage3_ground_truth():
    gt = {
        "version": "3.3.0",
        "description": "Ground Truth Độc Lập cho Tầng 3 - Gom Lô & Đối Soát Chứng Từ KIDO",
        "total_images": 72,
        "total_documents": 65,
        "total_multipage_groups": 7,
        "expected_batch_count": 19,
        "expected_dossier_count": 60,
        
        # 1. Multi-page Ground Truth (7 cặp)
        "multipage_gt": [
            {
                "parent_file": "Load_3.11__1.png",
                "continuation_files": ["Load_3.11__0.png"],
                "doc_type": "LOADING_PLAN",
                "system": "SATRA",
                "reason": "Loading Plan Satra gồm 2 trang, trang 1 chứa tiêu đề & mã chuyến, trang 2 chứa bảng hàng"
            },
            {
                "parent_file": "Load_3.2__1.png",
                "continuation_files": ["Load_3.2__0.png"],
                "doc_type": "LOADING_PLAN",
                "system": "COOP",
                "reason": "Loading Plan Co.opmart gồm 2 trang"
            },
            {
                "parent_file": "Load_3.5__1.png",
                "continuation_files": ["Load_3.5__0.png"],
                "doc_type": "LOADING_PLAN",
                "system": "AEON",
                "reason": "Loading Plan Aeon gồm 2 trang"
            },
            {
                "parent_file": "Load_3.6__1.png",
                "continuation_files": ["Load_3.6__0.png"],
                "doc_type": "LOADING_PLAN",
                "system": "WINMART",
                "reason": "Loading Plan WinMart gồm 2 trang"
            },
            {
                "parent_file": "Loading_Plan3.1__1.png",
                "continuation_files": ["Loading_Plan3.1__0.png"],
                "doc_type": "LOADING_PLAN",
                "system": "BHX",
                "reason": "Loading Plan Bách Hóa Xanh gồm 2 trang"
            },
            {
                "parent_file": "PO_3.1__1.png",
                "continuation_files": ["PO_3.1__0.png"],
                "doc_type": "PO",
                "system": "BHX",
                "po_no": "14017PO2506918178",
                "reason": "Đơn đặt hàng BHX gồm 2 trang chia sẻ chung số PO 14017PO2506918178"
            },
            {
                "parent_file": "PO_3.6__1.png",
                "continuation_files": ["PO_3.6__0.png"],
                "doc_type": "PO",
                "system": "WINMART",
                "po_no": "4173475639",
                "reason": "Đơn đặt hàng WinMart gồm 2 trang chia sẻ chung số PO 4173475639"
            }
        ],

        # 2. Định danh Lô Chuyến Xe (19 Lô Ground Truth)
        "shipment_batches_gt": {
            "SHIP_129367_NPP": {
                "order_code": "2.1",
                "system": "NPP",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "129367",
                "doc_files": ["Loading_Plan2.1__0.png", "Hoadon_2.1__0.png", "Hoadon_2.1__1.png"]
            },
            "SHIP_128765_NPP": {
                "order_code": "2.2",
                "system": "NPP",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "128765",
                "doc_files": ["Loading_Plan_2.2__0.png", "BBBG_Hoadon2.2__0.png", "Hoadon2.2__0.png", "Hoadon2.2__1.png", "Hoadon2.2__2.png", "Hoadon2.2__3.png"]
            },
            "SHIP_4901390900_NPP": {
                "order_code": "2.3",
                "system": "NPP",
                "identity_type": "TRANSFER_ORDER",
                "identity_value": "4901390900",
                "doc_files": ["Loading_Plan_2.3__0.png", "PXKKVCNB2.3__0.png"]
            },
            "BATCH_3.1_BHX": {
                "order_code": "3.1",
                "system": "BHX",
                "identity_type": "BUSINESS_KEY",
                "identity_value": "14017PO2506918178",
                "doc_files": ["Loading_Plan3.1__1.png", "Hoadon3.1__0.png", "PO_3.1__1.png"]
            },
            "SHIP_133870_COOP": {
                "order_code": "3.2",
                "system": "COOP",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "133870",
                "doc_files": ["Load_3.2__1.png", "Hoadon_3.2__0.png", "Hoadon_3.2__1.png", "PO_3.2__0.png"]
            },
            "SHIP_130771_BIGC": {
                "order_code": "3.3",
                "system": "BIGC",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "130771",
                "doc_files": ["Load3.3__0.png", "Hoadon_3.3__0.png", "Hoadon_3.3__1.png", "PO_3.3__0.png"]
            },
            "SHIP_2100199210_LOTTE": {
                "order_code": "3.4",
                "system": "LOTTE",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "2100199210",
                "doc_files": ["Loading_3.4__0.png", "PGH_3.4__0.png", "Hoa_don_3.4__0.png", "PO_3.4__0.png"]
            },
            "SHIP_134423_AEON": {
                "order_code": "3.5",
                "system": "AEON",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "134423",
                "doc_files": ["Load_3.5__1.png", "Hoadon_3.5__0.png", "Hoadon_3.5__1.png", "PO_3.5__0.png"]
            },
            "BATCH_3.6_WINMART": {
                "order_code": "3.6",
                "system": "WINMART",
                "identity_type": "BUSINESS_KEY",
                "identity_value": "4173475639",
                "doc_files": ["Load_3.6__1.png", "PGH3.6__0.png", "PGH3.6__1.png", "Hoadon_3.6__0.png", "PO_3.6__1.png"]
            },
            "BATCH_3.7_EMART": {
                "order_code": "3.7",
                "system": "EMART",
                "identity_type": "BUSINESS_KEY",
                "identity_value": "4501479650",
                "doc_files": ["Load_3.7__0.png", "Hoadon_3.7__0.png", "PO_3.7__0.png"]
            },
            "SHIP_133916_GS25": {
                "order_code": "3.8",
                "system": "GS25",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "133916",
                "doc_files": ["Load_3.8__0.png", "PGH_3.8__0.png", "Hoa_don_3.8__0.png", "Hoa_don_3.8__1.png", "PO_3.8__0.png"]
            },
            "SHIP_130189_SATRA": {
                "order_code": "3.11",
                "system": "SATRA",
                "identity_type": "SHIPMENT_ID",
                "identity_value": "130189",
                "doc_files": ["Load_3.11__1.png", "Hoadon3.11__0.png", "Hoadon3.11__1.png", "Hoadon3.11__2.png", "PO_3.11__0.png", "PO_3.11__1.png"]
            },
            "BATCH_4.1_COOP": {
                "order_code": "4.1",
                "system": "COOP",
                "identity_type": "BUSINESS_DOC",
                "identity_value": "4.1",
                "doc_files": ["DX_THUHOI4.1__0.png"]
            },
            "BATCH_4.2_NPP": {
                "order_code": "4.2",
                "system": "NPP",
                "identity_type": "BUSINESS_DOC",
                "identity_value": "4.2",
                "doc_files": ["THU_HOI_4.2__0.png", "THU_HOI_4.2__1.png"]
            },
            "SHIP_4901316574_KHO_THUE": {
                "order_code": "5.1",
                "system": "KHO_THUE",
                "identity_type": "TRANSFER_ORDER",
                "identity_value": "4901316574",
                "doc_files": ["Loadingplan_5.1__0.png", "PXKKVCNB_5.1__0.png", "Phieu_nhap_kho_5.1__0.png", "Phieu_xuat_hang5.1__0.png", "BBBGHH_5.1__0.png"]
            },
            "SHIP_4901312550_KHO_NOIBO": {
                "order_code": "5.2",
                "system": "KHO_NOIBO",
                "identity_type": "TRANSFER_ORDER",
                "identity_value": "4901312550",
                "doc_files": ["Loading_Plan_5.2__0.png", "PXKKVCNB_5.2__0.png", "BBBGHH_5.2__0.png"]
            },
            "BATCH_6.x_GENERAL": {
                "order_code": "6.x",
                "system": "GENERAL",
                "identity_type": "BUSINESS_DOC",
                "identity_value": "6.x",
                "doc_files": ["BB_NO_HANG__0.png", "BB_TRA_HANG__0.png"]
            },
            "BATCH_PALLET_GENERAL": {
                "order_code": "PALLET",
                "system": "GENERAL",
                "identity_type": "BUSINESS_DOC",
                "identity_value": "PALLET",
                "doc_files": ["BBBG_Pallet__0.png"]
            },
            "BATCH_CHUNG_GENERAL": {
                "order_code": "CHUNG",
                "system": "GENERAL",
                "identity_type": "BUSINESS_DOC",
                "identity_value": "CHUNG",
                "doc_files": ["L_nh_i_u_xe__0.png", "Bieu_do_nhiet_do__0.png"]
            }
        },

        # 3. Ground Truth Hồ Sơ Đơn Hàng (60 OrderDossiers)
        # Các hóa đơn cùng số hóa đơn ghép chung 1 hồ sơ (4 nhóm đa liên: 00044625, 00053432, 00053414, 00047037)
        # Các chứng từ còn lại hình thành 56 hồ sơ đơn lẻ (tổng cộng 60 dossiers)
        "order_dossiers_gt": {
            # Multi-document dossiers (4 nhóm chia sẻ invoice_no)
            "DOSS_GT_INV_00044625": {
                "dossier_type": "INVOICE_SET",
                "key_value": "00044625",
                "doc_files": ["Hoadon_2.1__0.png", "Hoadon_2.1__1.png"]
            },
            "DOSS_GT_INV_00053432": {
                "dossier_type": "INVOICE_SET",
                "key_value": "00053432",
                "doc_files": ["Hoadon_3.2__0.png", "Hoadon_3.2__1.png"]
            },
            "DOSS_GT_INV_00053414": {
                "dossier_type": "INVOICE_SET",
                "key_value": "00053414",
                "doc_files": ["Hoa_don_3.8__0.png", "Hoa_don_3.8__1.png"]
            },
            "DOSS_GT_INV_00047037": {
                "dossier_type": "INVOICE_SET",
                "key_value": "00047037",
                "doc_files": ["Hoadon3.11__0.png", "Hoadon3.11__1.png", "Hoadon3.11__2.png"]
            }
        },

        # 4. Minh chứng Đối soát Trường dữ liệu (Reconciliation Rules trên 5 trường khóa)
        "reconciliation_gt": [
            {
                "rule_name": "MATCH_SHIPMENT_NPP_2_1",
                "dossier_key": "129367",
                "source_doc_type": "HOA_DON",
                "target_doc_type": "HOA_DON",
                "field": "shipment_id",
                "expected_status": "MATCH"
            },
            {
                "rule_name": "MATCH_INVOICE_COOP_3_2",
                "dossier_key": "00053432",
                "source_doc_type": "HOA_DON",
                "target_doc_type": "HOA_DON",
                "field": "invoice_no",
                "expected_status": "MATCH"
            },
            {
                "rule_name": "MATCH_INVOICE_GS25_3_8",
                "dossier_key": "00053414",
                "source_doc_type": "HOA_DON",
                "target_doc_type": "HOA_DON",
                "field": "invoice_no",
                "expected_status": "MATCH"
            },
            {
                "rule_name": "MATCH_INVOICE_SATRA_3_11",
                "dossier_key": "00047037",
                "source_doc_type": "HOA_DON",
                "target_doc_type": "HOA_DON",
                "field": "invoice_no",
                "expected_status": "MATCH"
            },
            {
                "rule_name": "PARTIAL_MATCH_PO_WINMART_3_6",
                "dossier_key": "4173475639",
                "source_doc_type": "PO",
                "target_doc_type": "PHIEU_GIAO_HANG",
                "field": "po_no",
                "expected_status": "PARTIAL_MATCH"
            },
            {
                "rule_name": "MISSING_TARGET_PO_BHX_3_1",
                "dossier_key": "14017PO2506918178",
                "source_doc_type": "PO",
                "target_doc_type": "HOA_DON",
                "field": "po_no",
                "expected_status": "MISSING_TARGET"
            },
            {
                "rule_name": "MISSING_TARGET_PO_LOTTE_3_4",
                "dossier_key": "PO-4501484734",
                "source_doc_type": "PO",
                "target_doc_type": "HOA_DON",
                "field": "po_no",
                "expected_status": "MISSING_TARGET"
            },
            {
                "rule_name": "MISMATCH_TRANSFER_VS_SHIPMENT_5_1",
                "dossier_key": "4901316574",
                "source_doc_type": "LOADING_PLAN",
                "target_doc_type": "PXKKVCNB",
                "field": "transfer_order_no",
                "expected_status": "MISMATCH"
            }
        ],

        # 5. Quy chuẩn Checklist KIDO
        "checklist_semantics_gt": {
            "copy_count_status": "DEMO_SINGLE_SAMPLE",
            "rule": "Trong bộ dữ liệu demo từ file Excel, mỗi chứng từ được quan sát qua 1 ảnh mẫu (copy_count=1). Việc document_count < target_copies phản ánh giới hạn quan sát của file demo, không khẳng định tài xế thiếu liên vật lý ngoài đời thực."
        }
    }

    # Bổ sung 56 đơn lẻ vào order_dossiers_gt
    all_multi_files = set()
    for dinfo in gt["order_dossiers_gt"].values():
        all_multi_files.update(dinfo["doc_files"])

    single_idx = 1
    for binfo in gt["shipment_batches_gt"].values():
        for fn in binfo["doc_files"]:
            if fn not in all_multi_files:
                d_id = f"DOSS_GT_SINGLE_{single_idx:02d}"
                gt["order_dossiers_gt"][d_id] = {
                    "dossier_type": "SINGLE_DOC",
                    "key_value": fn,
                    "doc_files": [fn]
                }
                single_idx += 1
    
    out_path = Path("output/stage3_gt.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)
    print(f"[OK] Đã xuất Stage 3 Ground Truth độc lập tại {out_path} ({len(gt['shipment_batches_gt'])} Lô, {len(gt['multipage_gt'])} đa trang, {len(gt['order_dossiers_gt'])} Dossiers, {len(gt['reconciliation_gt'])} đối soát).")

if __name__ == "__main__":
    build_stage3_ground_truth()
