"""
Tạo bộ Ground Truth độc lập và chuẩn mực cho Tầng 2: output/stage2_gt.json
Quy cách:
- 72 bản ghi (khớp 1-1 với 72 ảnh biểu mẫu trong output/form_samples/)
- doc_type: Nhãn chứng từ thực tế của ảnh (không phụ thuộc vào tên sheet Excel)
- page_role: 'HEADER' (trang tiêu đề) vs 'CONTINUATION' (trang bảng kê / chữ ký phụ)
- expected_fields: Các giá trị trường khóa thực tế in trên ảnh
- quality_note: 'NORMAL', 'LOW_DPI_45_REJECT', 'BW_PHOTOCOPY'
"""

import json
import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

GT_DATA = [
    # --- NHÓM 2.X (KÊNH GT - NPP & KHO NỘI BỘ) ---
    {
        "file_name": "Loading_Plan2.1__0.png",
        "sheet_origin": "Loading Plan2.1",
        "doc_type": "LOADING_PLAN",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,  # Mẫu trắng template, header để trống
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_2.1__0.png",
        "sheet_origin": "Hoadon 2.1",
        "doc_type": "HOA_DON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "129367",
            "invoice_no": "00044625",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "Hoadon_2.1__1.png",
        "sheet_origin": "Hoadon 2.1",
        "doc_type": "HOA_DON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "129367",  # Drop 2 / Liên 2 của chuyến 129367
            "invoice_no": "00044625",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "Loading_Plan_2.2__0.png",
        "sheet_origin": "Loading Plan 2.2",
        "doc_type": "LOADING_PLAN",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,  # Mẫu template để trống
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "BBBG_Hoadon2.2__0.png",
        "sheet_origin": "BBBG Hoadon2.2",
        "doc_type": "BBBG_HOADON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon2.2__0.png",
        "sheet_origin": "Hoadon2.2",
        "doc_type": "HOA_DON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "128765",  # Cùng stem chuyến xe Hoadon2.2
            "invoice_no": "00044085",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon2.2__1.png",
        "sheet_origin": "Hoadon2.2",
        "doc_type": "HOA_DON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "128765",
            "invoice_no": "00044082",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon2.2__2.png",
        "sheet_origin": "Hoadon2.2",
        "doc_type": "HOA_DON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "128765",
            "invoice_no": "00044079",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon2.2__3.png",
        "sheet_origin": "Hoadon2.2",
        "doc_type": "HOA_DON",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "128765",
            "invoice_no": "00044119",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Loading_Plan_2.3__0.png",
        "sheet_origin": "Loading Plan 2.3",
        "doc_type": "LOADING_PLAN",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "129343",
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PXKKVCNB2.3__0.png",
        "sheet_origin": "PXKKVCNB2.3",
        "doc_type": "PXKKVCNB",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "4901390900",
            "invoice_no": None,
            "po_no": None,
            "pxk_no": "00001814",
            "transfer_order_no": "4901390900"
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.1 (KÊNH MT - BÁCH HÓA XANH) ---
    {
        "file_name": "Loading_Plan3.1__0.png",
        "sheet_origin": "Loading Plan3.1",
        "doc_type": "LOADING_PLAN",
        "system": "MT_BHX",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Loading_Plan3.1__1.png",
        "sheet_origin": "Loading Plan3.1",
        "doc_type": "LOADING_PLAN",
        "system": "MT_BHX",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,  # Mẫu template để trống
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon3.1__0.png",
        "sheet_origin": "Hoadon3.1",
        "doc_type": "HOA_DON",
        "system": "MT_BHX",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "129367",
            "invoice_no": "00044950",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.1__0.png",
        "sheet_origin": "PO 3.1",
        "doc_type": "PO",
        "system": "MT_BHX",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "14017PO2506918178",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.1__1.png",
        "sheet_origin": "PO 3.1",
        "doc_type": "PO",
        "system": "MT_BHX",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "14017PO2506918178",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.2 (KÊNH MT - CO.OPMART) ---
    {
        "file_name": "Load_3.2__0.png",
        "sheet_origin": "Load 3.2",
        "doc_type": "LOADING_PLAN",
        "system": "MT_COOP",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Load_3.2__1.png",
        "sheet_origin": "Load 3.2",
        "doc_type": "LOADING_PLAN",
        "system": "MT_COOP",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,  # Mẫu template để trống
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.2__0.png",
        "sheet_origin": "Hoadon 3.2",
        "doc_type": "HOA_DON",
        "system": "MT_COOP",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "133870",
            "invoice_no": "00053432",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "Hoadon_3.2__1.png",
        "sheet_origin": "Hoadon 3.2",
        "doc_type": "HOA_DON",
        "system": "MT_COOP",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "133870",
            "invoice_no": "00053432",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "PO_3.2__0.png",
        "sheet_origin": "PO 3.2",
        "doc_type": "PO",
        "system": "MT_COOP",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "O343P1071694",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "LOW_DPI_45_REJECT"
    },

    # --- NHÓM 3.3 (KÊNH MT - BIG C / TOPS MARKET) ---
    {
        "file_name": "Load3.3__0.png",
        "sheet_origin": "Load3.3",
        "doc_type": "LOADING_PLAN",
        "system": "MT_BIGC",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.3__0.png",
        "sheet_origin": "Hoadon 3.3",
        "doc_type": "HOA_DON",
        "system": "MT_BIGC",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "130771",
            "invoice_no": "00047012",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.3__1.png",
        "sheet_origin": "Hoadon 3.3",
        "doc_type": "HOA_DON",
        "system": "MT_BIGC",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "116271",
            "invoice_no": "00047177",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.3__0.png",
        "sheet_origin": "PO 3.3",
        "doc_type": "PO",
        "system": "MT_BIGC",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.4 (KÊNH MT - LOTTE MART) ---
    {
        "file_name": "Loading_3.4__0.png",
        "sheet_origin": "Loading 3.4",
        "doc_type": "LOADING_PLAN",
        "system": "MT_LOTTE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PGH_3.4__0.png",
        "sheet_origin": "PGH 3.4",
        "doc_type": "PHIEU_GIAO_HANG",
        "system": "MT_LOTTE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoa_don_3.4__0.png",
        "sheet_origin": "Hoa don 3.4",
        "doc_type": "HOA_DON",
        "system": "MT_LOTTE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "2100199210",
            "invoice_no": "00044093",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.4__0.png",
        "sheet_origin": "PO 3.4",
        "doc_type": "PO",
        "system": "MT_LOTTE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "2506260100600123",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.5 (KÊNH MT - AEON) ---
    {
        "file_name": "Load_3.5__0.png",
        "sheet_origin": "Load 3.5",
        "doc_type": "LOADING_PLAN",
        "system": "MT_AEON",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Load_3.5__1.png",
        "sheet_origin": "Load 3.5",
        "doc_type": "LOADING_PLAN",
        "system": "MT_AEON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.5__0.png",
        "sheet_origin": "Hoadon 3.5",
        "doc_type": "HOA_DON",
        "system": "MT_AEON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "134423",
            "invoice_no": "00054132",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.5__1.png",
        "sheet_origin": "Hoadon 3.5",
        "doc_type": "HOA_DON",
        "system": "MT_AEON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "134423",
            "invoice_no": "00054133",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.5__0.png",
        "sheet_origin": "PO 3.5",
        "doc_type": "PO",
        "system": "MT_AEON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "10021001169682",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.6 (KÊNH MT - WINMART) ---
    {
        "file_name": "Load_3.6__0.png",
        "sheet_origin": "Load 3.6",
        "doc_type": "LOADING_PLAN",
        "system": "MT_WINMART",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Load_3.6__1.png",
        "sheet_origin": "Load 3.6",
        "doc_type": "LOADING_PLAN",
        "system": "MT_WINMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PGH3.6__0.png",
        "sheet_origin": "PGH3.6",
        "doc_type": "PHIEU_NHAP_KHO",
        "system": "MT_WINMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PGH3.6__1.png",
        "sheet_origin": "PGH3.6",
        "doc_type": "PHIEU_GIAO_HANG",
        "system": "MT_WINMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.6__0.png",
        "sheet_origin": "Hoadon 3.6",
        "doc_type": "HOA_DON",
        "system": "MT_WINMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": "00046193",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.6__0.png",
        "sheet_origin": "PO 3.6",
        "doc_type": "PO",
        "system": "MT_WINMART",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "4173475639",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.6__1.png",
        "sheet_origin": "PO 3.6",
        "doc_type": "PO",
        "system": "MT_WINMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "4173475639",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.7 (KÊNH MT - EMART / THISO RETAIL) ---
    {
        "file_name": "Load_3.7__0.png",
        "sheet_origin": "Load 3.7",
        "doc_type": "LOADING_PLAN",
        "system": "MT_EMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon_3.7__0.png",
        "sheet_origin": "Hoadon 3.7",
        "doc_type": "HOA_DON",
        "system": "MT_EMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "133870",
            "invoice_no": "00053428",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.7__0.png",
        "sheet_origin": "PO 3.7",
        "doc_type": "PO",
        "system": "MT_EMART",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "4501479650",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.8 (KÊNH MT - GS25) ---
    {
        "file_name": "Load_3.8__0.png",
        "sheet_origin": "Load 3.8",
        "doc_type": "LOADING_PLAN",
        "system": "MT_GS25",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PGH_3.8__0.png",
        "sheet_origin": "PGH 3.8",
        "doc_type": "PHIEU_GIAO_HANG",
        "system": "MT_GS25",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "WH0009250519944278",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoa_don_3.8__0.png",
        "sheet_origin": "Hoa don 3.8",
        "doc_type": "HOA_DON",
        "system": "MT_GS25",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "133916",
            "invoice_no": "00053414",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoa_don_3.8__1.png",
        "sheet_origin": "Hoa don 3.8",
        "doc_type": "HOA_DON",
        "system": "MT_GS25",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "133916",
            "invoice_no": "00053414",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PO_3.8__0.png",
        "sheet_origin": "PO 3.8",
        "doc_type": "PO",
        "system": "MT_GS25",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "WE09240510044278",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 3.11 (KÊNH MT - SATRA) ---
    {
        "file_name": "Load_3.11__0.png",
        "sheet_origin": "Load 3.11",
        "doc_type": "LOADING_PLAN",
        "system": "MT_SATRA",
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Load_3.11__1.png",
        "sheet_origin": "Load 3.11",
        "doc_type": "LOADING_PLAN",
        "system": "MT_SATRA",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Hoadon3.11__0.png",
        "sheet_origin": "Hoadon3.11",
        "doc_type": "HOA_DON",
        "system": "MT_SATRA",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "130189",
            "invoice_no": "00047037",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "Hoadon3.11__1.png",
        "sheet_origin": "Hoadon3.11",
        "doc_type": "HOA_DON",
        "system": "MT_SATRA",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "130189",
            "invoice_no": "00047037",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "Hoadon3.11__2.png",
        "sheet_origin": "Hoadon3.11",
        "doc_type": "HOA_DON",
        "system": "MT_SATRA",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "130189",
            "invoice_no": "00047037",
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "PO_3.11__0.png",
        "sheet_origin": "PO 3.11",
        "doc_type": "PO",
        "system": "MT_SATRA",
        # ĐÍNH CHÍNH 27/09 (căn cứ NỘI DUNG ẢNH, không căn cứ kết quả model): trang này in "Trang 2/2",
        # chỉ có bảng hàng STT 28–37 + "Tổng cộng" + khối ký; KHÔNG có tiêu đề "ĐƠN ĐẶT HÀNG", KHÔNG in
        # số PO. Trang 1/2 là PO_3.11__1 (tiêu đề + "Đơn đặt hàng số: P-000105230", STT 1–27).
        # => page_role HEADER -> CONTINUATION. po_no GIỮ P-000105230 theo cùng quy ước với PO_3.1__0 /
        # PO_3.6__0: trang tiếp nối mang số PO cấp chứng từ (kỳ vọng nhận qua đồng thuận đa trang).
        "page_role": "CONTINUATION",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "P-000105230",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "LOW_DPI_45_REJECT"
    },
    {
        "file_name": "PO_3.11__1.png",
        "sheet_origin": "PO 3.11",
        "doc_type": "PO",
        "system": "MT_SATRA",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": "P-000105230",
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 4.X (THU HỒI HÀNG HÓA) ---
    # Trục 2 (27/09, scratch/_nb/t3fix/gt_diff.log): cả nhóm 4 là kênh NPP (GT).
    # Căn cứ: Excel sheet Guideline dòng 56–57 — mục 4 "Hàng thu hồi từ NPP" bao cả
    #   4.1 "Biên bản nhận hàng - kiêm đề xuất trả hàng" (dòng 56) và 4.2 "Phiếu đề xuất thu hồi
    #   tem que LAP" (dòng 57).
    # - THU_HOI_4.2__0/__1: COMMON -> GT. Ảnh __1 có ô "Nhà Phân Phối" và "Người giao (đại diện
    #   NPP)"; ảnh __0 tiêu đề "QUY TRÌNH THU HỒI HÀNG TỪ KHO NPP VỀ CÔNG TY".
    # - DX_THUHOI4.1__0: MT_COOP -> GT. Ảnh: tiêu đề "QUY TRÌNH THU HỒI HÀNG TỪ NPP VỀ CÔNG TY",
    #   trường "MÃ NPP"/"TÊN NPP: CM Kiên Giang", mộc đỏ của NPP (Cty TNHH Kiên Trúc Mai), ô ký
    #   "NPP". Dấu vết "Coop" DUY NHẤT là tiền tố của mã "SỐ ĐỀ XUẤT: CoopKGSHD406" — đó là
    #   số chứng từ, không phải khách hàng/kênh giao nhận.
    {
        "file_name": "DX_THUHOI4.1__0.png",
        "sheet_origin": "DX THUHOI4.1",
        "doc_type": "BB_THU_HOI",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "THU_HOI_4.2__0.png",
        "sheet_origin": "THU HOI 4.2",
        "doc_type": "BB_THU_HOI",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "THU_HOI_4.2__1.png",
        "sheet_origin": "THU HOI 4.2",
        "doc_type": "BB_THU_HOI",
        "system": "GT",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM 5.X (CHUYỂN KHO NỘI BỘ & THUÊ NGOÀI) ---
    # Trục 2 tách theo SOP (Excel HUONG DAN CHUNG TU GIAO NHAN, form_catalog.json):
    #   5.1 "Hàng chuyển kho thuê CLK/AJ/Lotte/Anpha"                -> INTERNAL_KHO_THUE
    #   5.2 "Hàng trung chuyển kho Nội Bộ (Kho Quảng Nam/ Bắc Ninh)"  -> INTERNAL_KHO_NOIBO
    # Nhãn gán theo sheet nghiệp vụ, KHÔNG theo việc ảnh có đọc được dấu hiệu hay không.
    {
        "file_name": "Loadingplan_5.1__0.png",
        "sheet_origin": "Loadingplan 5.1",
        "doc_type": "LOADING_PLAN",
        "system": "INTERNAL_KHO_THUE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "121049",
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PXKKVCNB_5.1__0.png",
        "sheet_origin": "PXKKVCNB 5.1",
        "doc_type": "PXKKVCNB",
        "system": "INTERNAL_KHO_THUE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "4901316574",
            "invoice_no": None,
            "po_no": None,
            "pxk_no": "00001292",
            "transfer_order_no": "4901316574"
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "BBBGHH_5.1__0.png",
        "sheet_origin": "BBBGHH 5.1",
        "doc_type": "BBBG_HANG_HOA",
        "system": "INTERNAL_KHO_THUE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Phieu_nhap_kho_5.1__0.png",
        "sheet_origin": "Phieu nhap kho 5.1",
        "doc_type": "PHIEU_NHAP_KHO",
        "system": "INTERNAL_KHO_THUE",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Phieu_xuat_hang5.1__0.png",
        "sheet_origin": "Phieu xuat hang5.1",
        "doc_type": "PHIEU_XUAT_HANG",
        # Excel/form_catalog: CẢ dòng 5.1 lẫn dòng 5.2 ("Cho kho Bắc Ninh + Kho thuê") đều trỏ
        # form_sheet "Phieu xuat hang5.1" -> biểu mẫu dùng chung, SOP không gắn nó với một loại kho.
        "system": "INTERNAL_TRANSFER",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": "0000005",
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Loading_Plan_5.2__0.png",
        "sheet_origin": "Loading Plan 5.2",
        "doc_type": "LOADING_PLAN",
        "system": "INTERNAL_KHO_NOIBO",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "120562",
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "PXKKVCNB_5.2__0.png",
        "sheet_origin": "PXKKVCNB 5.2",
        "doc_type": "PXKKVCNB",
        "system": "INTERNAL_KHO_NOIBO",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": "4901312550",
            "invoice_no": None,
            "po_no": None,
            "pxk_no": "00001272",
            "transfer_order_no": "4901312550"
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "BBBGHH_5.2__0.png",
        "sheet_origin": "BBBGHH 5.2",
        "doc_type": "BBBG_HANG_HOA",
        "system": "INTERNAL_KHO_NOIBO",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },

    # --- NHÓM CHỨNG TỪ KHÁC (ĐIỀU XE, NHIỆT ĐỘ, PALLET, NỢ TRẢ) ---
    {
        "file_name": "L_nh_i_u_xe__0.png",
        "sheet_origin": "Lệnh điều xe",
        "doc_type": "LENH_DIEU_XE",
        "system": "COMMON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "Bieu_do_nhiet_do__0.png",
        "sheet_origin": "Bieu do nhiet do",
        "doc_type": "BIEU_DO_NHIET_DO",
        "system": "COMMON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "BW_PHOTOCOPY"
    },
    {
        "file_name": "BBBG_Pallet__0.png",
        "sheet_origin": "BBBG Pallet",
        "doc_type": "BBBG_PALLET",
        "system": "COMMON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "BB_TRA_HANG__0.png",
        "sheet_origin": "BB TRA HANG",
        "doc_type": "BB_TRA_HANG",
        "system": "COMMON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    },
    {
        "file_name": "BB_NO_HANG__0.png",
        "sheet_origin": "BB NO HANG",
        "doc_type": "BB_NO_HANG",
        "system": "COMMON",
        "page_role": "HEADER",
        "expected_fields": {
            "shipment_id": None,
            "invoice_no": None,
            "po_no": None,
            "pxk_no": None,
            "transfer_order_no": None
        },
        "quality_note": "NORMAL"
    }
]

def main():
    out_path = "output/stage2_gt.json"
    print(f"Checking {len(GT_DATA)} Ground Truth records...")
    
    # Kiểm tra tính đầy đủ so với thư mục form_samples
    files_in_samples = set(os.listdir("output/form_samples"))
    files_in_gt = {item["file_name"] for item in GT_DATA}
    
    diff_missing = files_in_samples - files_in_gt
    diff_extra = files_in_gt - files_in_samples
    
    if diff_missing:
        print(f"ERROR: Thiếu {len(diff_missing)} file trong GT: {diff_missing}")
        return
    if diff_extra:
        print(f"ERROR: Dư {len(diff_extra)} file trong GT: {diff_extra}")
        return
        
    print(f"Xác nhận 100% khớp (72/72 files)!")
    
    # Thống kê nhanh
    from collections import Counter
    doc_counts = Counter(item["doc_type"] for item in GT_DATA)
    role_counts = Counter(item["page_role"] for item in GT_DATA)
    quality_counts = Counter(item["quality_note"] for item in GT_DATA)
    
    print("\nPhân bổ Loại chứng từ:")
    for dt, cnt in doc_counts.most_common():
        print(f"  {dt:<20}: {cnt}")
        
    print("\nPhân bổ Vai trò trang (page_role):")
    for r, cnt in role_counts.items():
        print(f"  {r:<20}: {cnt}")
        
    print("\nPhân bổ Chất lượng (quality_note):")
    for q, cnt in quality_counts.items():
        print(f"  {q:<20}: {cnt}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(GT_DATA, f, ensure_ascii=False, indent=2)
    print(f"\nĐã xuất Ground Truth độc lập thành công -> {out_path}")

if __name__ == "__main__":
    main()
