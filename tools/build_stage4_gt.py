"""
Script xây dựng file Ground Truth đóng băng độc lập cho Tầng 4: output/stage4_gt.json
Được xây dựng ở cấp: document, page, target.
Chứa các trường:
- document_id
- target_id
- page
- file_name
- doc_type
- role
- target_type (signature / stamp)
- required (bool)
- expected_presence (PRESENT / ABSENT)
- expected_color (blue_ink / red_stamp)
- expected_modality (TRUE_COLOR / PHOTOCOPY_BW)
- notes (ghi chú bối cảnh nghiệp vụ)
"""

import json
import os
import sys
import cv2

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

def build_stage4_ground_truth():
    manifest_path = "output/stage3_out/stage3_batched_manifest.json"
    gt_path = "output/stage4_gt.json"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    gt_records = []
    
    # Danh sách các tài liệu mẫu trắng (blank ERP / guidance template printouts without signatures)
    # 26 targets trên Loading Plan ERP trắng:
    # Load3.3, Load_3.6, Load_3.7, Load_3.8, Loading_3.4, Loading_Plan_2.2, Loading_Plan_2.3, Loading_Plan_5.2, Loadingplan_5.1
    # 14 targets trên Hóa đơn mẫu trắng chưa ký:
    # Hoa_don_3.4, Hoa_don_3.8, Hoadon3.1, Hoadon3.11, Hoadon_2.1 (liên chưa ký), Hoadon_3.2, Hoadon_3.5
    # 8 targets trên PO mẫu chưa nhận hàng:
    # PO_3.2, PO_3.5, PO_3.8
    # 8 targets trên Phiếu giao hàng / biên bản mẫu chưa ký:
    # PGH3.6, PGH_3.4, PGH_3.8, BBBG_Hoadon2.2, BB_NO_HANG, BB_TRA_HANG, PXKKVCNB2.3
    
    for b in manifest['batches']:
        for doc in b['documents']:
            doc_id = doc['doc_id']
            doc_type = doc['doc_type']
            fname = os.path.basename(doc['file_name'])
            page_files = doc.get('page_files', [f"output/form_samples/{fname}"])
            targets = doc.get('signature_targets', [])
            
            for idx, t in enumerate(targets):
                t_id = f"{doc_id}_T{idx:02d}"
                t_page = t.get('page', 0)
                if t_page is None:
                    t_page = 0
                target_page_file = os.path.basename(page_files[min(t_page, len(page_files)-1)])
                
                expected_color = t['expected_color']
                role = t['role']
                required = t.get('required', True)
                
                # Determine target_type
                if expected_color == 'red_stamp' or any(k in role.lower() for k in ['mộc', 'con dấu', 'dấu']):
                    target_type = "stamp"
                else:
                    target_type = "signature"
                    
                # Phán quyết Ground Truth Presence:
                # Dựa trên kiểm chứng trực quan thực tế trên ảnh biểu mẫu mẫu
                # 129 targets có nét mực/mộc thực tế (PRESENT)
                # 56 targets là ô trống trên biểu mẫu ERP hướng dẫn (ABSENT)
                
                # Kiểm tra các ca ABSENT đặc thù:
                is_absent = False
                notes = "Chữ ký / con dấu có mặt thực tế trên chứng từ"
                
                # 1. Loading plan mẫu ERP trắng
                if doc_type == 'LOADING_PLAN':
                    if fname in ['Load3.3__0.png', 'Load_3.6__1.png', 'Load_3.7__0.png', 'Loading_3.4__0.png', 
                                 'Loading_Plan_2.3__0.png', 'Loading_Plan_5.2__0.png', 'Loadingplan_5.1__0.png']:
                        is_absent = True
                        notes = "Bản in SAP/ERP Loading Plan mẫu trắng chưa ký"
                    elif fname == 'Load_3.2__1.png' and role == 'Thủ kho xuất':
                        is_absent = True
                        notes = "Chỉ có lái xe và người lập ký, thủ kho chưa ký"
                    elif fname == 'Load_3.8__0.png' and role in ['Lái xe nhận hàng', 'Người lập phiếu']:
                        is_absent = True
                        notes = "Vị trí chưa ký trên mẫu Load 3.8"
                    elif fname == 'Loading_Plan_2.2__0.png' and role in ['Thủ kho xuất', 'Lái xe nhận hàng']:
                        is_absent = True
                        notes = "Vị trí chưa ký trên mẫu Loading Plan 2.2"
                        
                # 2. Hóa đơn mẫu chưa ký
                elif doc_type == 'HOA_DON':
                    if fname in ['Hoa_don_3.8__0.png', 'Hoadon3.1__0.png']:
                        is_absent = True
                        notes = "Hóa đơn điện tử mẫu trắng chưa có chữ ký / mộc tiếp nhận"
                    elif fname == 'Hoa_don_3.4__0.png' and role in ['Người mua hàng', 'Con dấu mộc đỏ']:
                        is_absent = True
                        notes = "Chỉ có chữ ký người bán, thiếu mộc và chữ ký người mua"
                    elif fname == 'Hoadon3.11__0.png' and role == 'Người mua hàng':
                        is_absent = True
                        notes = "Người mua hàng chưa ký trên Hóa đơn 3.11"
                    elif fname in ['Hoadon_2.1__0.png', 'Hoadon_2.1__1.png'] and role == 'Người mua hàng':
                        is_absent = True
                        notes = "Hóa đơn chuyển đổi, người mua chưa ký"
                    elif fname == 'Hoadon_3.2__0.png' and role == 'Người mua hàng':
                        is_absent = True
                        notes = "Bản photo Co.opmart, người mua chưa ký"
                    elif fname == 'Hoadon_3.5__0.png' and role in ['Người mua hàng', 'Con dấu mộc đỏ']:
                        is_absent = True
                        notes = "Thiếu chữ ký người mua và mộc trên mẫu 3.5"
                    elif role == 'Người mua hàng' and not is_absent:
                        # Kiểm tra xem người mua hàng có ký hay không
                        pass
                        
                # 3. PO mẫu chưa ký
                elif doc_type == 'PO':
                    if fname in ['PO_3.5__0.png', 'PO_3.8__0.png']:
                        is_absent = True
                        notes = "Đơn đặt hàng PO in từ hệ thống siêu thị chưa qua tiếp nhận"
                    elif fname == 'PO_3.2__0.png' and role in ['Người giao hàng', 'Thủ kho siêu thị / Khách hàng']:
                        is_absent = True
                        notes = "Mẫu PO 3.2 chỉ có mộc vuông, chưa có chữ ký người giao/nhận"
                        
                # 4. Phiếu giao hàng / Biên bản mẫu
                elif doc_type == 'PHIEU_GIAO_HANG':
                    if fname == 'PGH_3.4__0.png' and role in ['Người giao hàng', 'Người nhận hàng']:
                        is_absent = True
                        notes = "PGH Lotte Mart mẫu trắng chưa ký nhận"
                    elif fname in ['PGH3.6__1.png', 'PGH_3.8__0.png'] and role == 'Người nhận hàng':
                        is_absent = True
                        notes = "Khách hàng chưa ký nhận trên PGH"
                elif doc_type == 'BB_NO_HANG' and role == 'Bên nhận':
                    is_absent = True
                    notes = "Biên bản nợ hàng chỉ có bên giao ký, bên nhận chưa ký"
                elif doc_type == 'BB_TRA_HANG' and role == 'Con dấu mộc':
                    is_absent = True
                    notes = "Biên bản trả hàng chưa đóng dấu mộc"
                elif doc_type == 'BBBG_HOADON' and role == 'Người nhận hóa đơn':
                    is_absent = True
                    notes = "BBBG Hóa đơn chưa có người nhận ký"
                elif doc_type == 'PXKKVCNB' and fname == 'PXKKVCNB2.3__0.png' and role == 'Người lập phiếu':
                    is_absent = True
                    notes = "Người lập phiếu chưa ký trên PXK 2.3"
                    
                expected_presence = "ABSENT" if is_absent else "PRESENT"
                
                gt_records.append({
                    "target_id": t_id,
                    "doc_id": doc_id,
                    "batch_id": b['batch_id'],
                    "file_name": target_page_file,
                    "page": t_page,
                    "doc_type": doc_type,
                    "role": role,
                    "target_type": target_type,
                    "required": required,
                    "expected_color": expected_color,
                    "box_norm": t['box_norm'],
                    "expected_presence": expected_presence,
                    "notes": notes
                })
                
    gt_data = {
        "dataset_name": "KIDO Logistics Document Signature & Stamp Ground Truth",
        "version": "1.0.0",
        "description": "Ground Truth độc lập chú thích sự hiện diện (PRESENT/ABSENT) của chữ ký và con dấu trên 185 targets",
        "total_targets": len(gt_records),
        "present_targets": sum(1 for r in gt_records if r['expected_presence'] == 'PRESENT'),
        "absent_targets": sum(1 for r in gt_records if r['expected_presence'] == 'ABSENT'),
        "required_targets": sum(1 for r in gt_records if r['required']),
        "optional_targets": sum(1 for r in gt_records if not r['required']),
        "targets": gt_records
    }
    
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2, ensure_ascii=False)
        
    print(f"Đã tạo thành công Ground Truth độc lập Tầng 4 tại: {gt_path}")
    print(f" - Tổng số targets: {gt_data['total_targets']}")
    print(f" - Số targets có chữ ký/mộc (PRESENT): {gt_data['present_targets']} ({gt_data['present_targets']/gt_data['total_targets']*100:.1f}%)")
    print(f" - Số targets biểu mẫu trắng (ABSENT):  {gt_data['absent_targets']} ({gt_data['absent_targets']/gt_data['total_targets']*100:.1f}%)")
    print(f" - Số targets bắt buộc (required=True): {gt_data['required_targets']}")
    print(f" - Số targets tùy chọn (required=False): {gt_data['optional_targets']}")
    return gt_data

if __name__ == "__main__":
    build_stage4_ground_truth()
