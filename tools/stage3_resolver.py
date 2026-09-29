"""
tools/stage3_resolver.py
========================
Module Lõi Tầng 3: Ghép Nối Đa Trang, Định Danh Lô Chuyến Xe Theo Bằng Chứng,
Xây Dựng Đồ Thị Hồ Sơ Đơn Hàng & Đối Soát Quy Chuẩn KIDO (Stage 3 v3.2 Production-Hardened).

Triệt tiêu 100% Filename Leakage. Tách rời tầng cấu hình config/stage3_business_rules.json.
"""

import os
import re
import sys
import io
import json
import copy
import random
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set

# --- 1. DOMAIN MODELS CHUẨN NGHIỆP VỤ ---

# Nhãn chuyển kho của Tầng 2 -> system nghiệp vụ Tầng 3 (khớp system_metadata trong config).
INTERNAL_SYSTEM_MAP = {
    "INTERNAL_KHO_THUE": "KHO_THUE",
    "INTERNAL_KHO_NOIBO": "KHO_NOIBO",
    "INTERNAL_TRANSFER": "KHO_CHUA_RO",
}

class ReconciliationEvidence:
    """Minh chứng đối soát chéo từng cặp trường dữ liệu giữa các chứng từ."""
    def __init__(self, field: str, source_doc: str, target_doc: str,
                 source_val: Any, target_val: Any, status: str, notes: str = ""):
        self.field = field
        self.source_doc = source_doc
        self.target_doc = target_doc
        self.source_val = source_val
        self.target_val = target_val
        self.status = status  # MATCH, PARTIAL_MATCH, MISMATCH, MISSING_SOURCE, MISSING_TARGET, NOT_APPLICABLE
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "source_doc": self.source_doc,
            "target_doc": self.target_doc,
            "source_val": self.source_val,
            "target_val": self.target_val,
            "status": self.status,
            "notes": self.notes
        }

class DocumentItem:
    """Thực thể chứng từ độc lập sau khi đã ghép nối đa trang."""
    def __init__(self, doc_id: str, file_name: str, doc_type: str, system: str,
                 confidence: float, status: str, action: str, key_fields: Dict[str, Any],
                 image_path: str, page_files: List[str], is_multi_page: bool = False,
                 page_count: int = 1, scan_index: int = 0, evidence: Optional[Dict[str, Any]] = None):
        self.doc_id = doc_id
        self.file_name = file_name  # Chỉ lưu vết source_file, TUYỆT ĐỐI không dùng suy luận
        self.doc_type = doc_type
        self.system_raw = system
        if system == "GT":
            self.system = "NPP"
        elif system and system.startswith("MT_"):
            self.system = system[3:]
        elif system in INTERNAL_SYSTEM_MAP:
            # Ánh xạ TƯỜNG MINH. Trước đây mọi INTERNAL_TRANSFER bị ép thành KHO_NOIBO (silent
            # default) -> chứng từ kho thuê 5.1 bị gom nhầm vào lô kho nội bộ 5.2 (2 FP Tầng 3).
            # Tầng 2 không xác định được loại kho -> KHO_CHUA_RO, KHÔNG đoán.
            self.system = INTERNAL_SYSTEM_MAP[system]
        else:
            self.system = system
        self.confidence = confidence
        self.status = status
        self.action = action
        self.key_fields = key_fields
        self.image_path = image_path
        self.page_files = page_files
        self.is_multi_page = is_multi_page
        self.page_count = page_count
        self.scan_index = scan_index
        self.evidence = evidence or {}
        self.signature_targets: List[Dict[str, Any]] = []
        self.target_mapping_status: str = "UNMAPPED"
        self.preset_source: Optional[str] = None
        self.preset_version: Optional[str] = None
        # Dấu vết gom lô cấp CHỨNG TỪ (pass nào, phương pháp gì, độ tin cậy, cảnh báo).
        # batch_meta cấp lô chỉ giữ 1 định danh HIGH nên trước đây không thấy được chứng từ
        # nào vào lô nhờ lan truyền ngữ cảnh (MEDIUM) hay bị cách ly vì lý do gì.
        self.batch_assignment: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "file_name": self.file_name,
            "source_file": self.file_name,
            "doc_type": self.doc_type,
            "system": self.system,
            "confidence": self.confidence,
            "status": self.status,
            "action": self.action,
            "key_fields": self.key_fields,
            "is_multi_page": self.is_multi_page,
            "page_count": self.page_count,
            "page_files": self.page_files,
            "target_mapping_status": self.target_mapping_status,
            "preset_source": self.preset_source,
            "preset_version": self.preset_version,
            "batch_assignment": self.batch_assignment,
            "signature_targets": self.signature_targets
        }

class OrderDossier:
    """Hồ sơ đơn hàng con chứa các chứng từ liên quan (PO, Hóa đơn, PGH...)."""
    def __init__(self, dossier_id: str, po_no: Optional[str] = None,
                 invoice_no: Optional[str] = None, pxk_no: Optional[str] = None):
        self.dossier_id = dossier_id
        self.po_no = po_no
        self.invoice_no = invoice_no
        self.pxk_no = pxk_no
        self.documents: List[DocumentItem] = []
        self.reconciliation: List[ReconciliationEvidence] = []
        self.match_status: str = "CHUA_DOI_SOAT"
        self.match_notes: str = ""
        # Khóa có >=2 giá trị khác nhau trong cùng cụm dossier: {field: [giá trị đã sort]}.
        self.ambiguous_keys: Dict[str, List[str]] = {}

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "dossier_id": self.dossier_id,
            "po_no": self.po_no,
            "invoice_no": self.invoice_no,
            "pxk_no": self.pxk_no,
            "document_ids": [d.doc_id for d in self.documents],
            "match_status": self.match_status,
            "match_notes": self.match_notes,
            "reconciliation": [r.to_dict() for r in self.reconciliation]
        }
        # Chỉ xuất khi thực sự có nhập nhằng (tập demo hiện có: 0 ca) -> schema manifest
        # hiện tại không đổi; khi xảy ra thì Tầng 4 / người kiểm tra thấy được, không im lặng.
        if self.ambiguous_keys:
            out["ambiguous_keys"] = self.ambiguous_keys
        return out

class ShipmentBatch:
    """Lô chứng từ theo chuyến xe giao nhận hoặc phân bổ kênh KIDO."""
    def __init__(self, batch_id: str, order_code: str, system: str,
                 identity_type: str, identity_value: str, confidence: str = "HIGH"):
        self.batch_id = batch_id
        self.order_code = order_code
        self.system = system
        self.shipment_identity = {
            "type": identity_type,
            "value": identity_value,
            "confidence": confidence
        }
        self.business_context = {
            "order_code": order_code,
            "system": system
        }
        self.documents: List[DocumentItem] = []
        self.order_dossiers: List[OrderDossier] = []
        self.checklist_audit: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "order_code": self.order_code,
            "system": self.system,
            "channel": self.system,
            "shipment_identity": self.shipment_identity,
            "business_context": self.business_context,
            "document_count": len(self.documents),
            "page_count": sum(d.page_count for d in self.documents),
            "documents": [d.to_dict() for d in self.documents],
            "order_dossiers": [od.to_dict() for od in self.order_dossiers],
            "checklist_audit": self.checklist_audit
        }

# --- 2. MULTI-PAGE RESOLVER (100% FILENAME LEAKAGE FREE) ---

def resolve_multipage_documents(records: List[Dict[str, Any]]) -> Tuple[List[DocumentItem], List[Tuple[str, List[str], str]]]:
    """
    Ghép nối đa trang tuần tự & vai trò (Sequence & Role Multi-Page Stitcher):
    - Dựa trên: page_role, doc_type, key_fields, thứ tự quét (scan_index), và system specificity.
    - TUYỆT ĐỐI không dùng tên file hay regex trên file_name.
    - Continuation không có parent tương thích được gắn cờ UNRESOLVED_CONTINUATION.
    """
    headers = [dict(r) for r in records if r.get('page_role') != 'CONTINUATION']
    conts = [dict(r) for r in records if r.get('page_role') == 'CONTINUATION']

    parent_map = defaultdict(list)
    unresolved_conts = []

    for c in conts:
        c_idx = c.get('scan_index', 0)
        ckf = c.get('key_fields') or {}
        c_dt = c.get('doc_type')
        c_sys = c.get('system', 'COMMON')

        valid_candidates = []
        for h in headers:
            if h.get('doc_type') != c_dt:
                continue
            h_idx = h.get('scan_index', 0)
            dist = abs(c_idx - h_idx)
            if dist > 5:
                continue

            hkf = h.get('key_fields') or {}
            h_sys = h.get('system', 'COMMON')

            # 1. Conflict check (Rule 2.3)
            is_conflict = False
            for k in ['po_no', 'shipment_id', 'invoice_no', 'transfer_order_no', 'pxk_no']:
                if ckf.get(k) and hkf.get(k) and str(ckf[k]).strip() != str(hkf[k]).strip():
                    is_conflict = True
                    break
            if is_conflict:
                continue

            # Check system conflict
            if c_sys != 'COMMON' and h_sys != 'COMMON' and c_sys != h_sys:
                continue

            # 2. Evidence calculation
            strong_matches = [k for k in ['po_no', 'shipment_id', 'invoice_no', 'transfer_order_no', 'pxk_no']
                              if ckf.get(k) and hkf.get(k) and str(ckf[k]).strip() == str(hkf[k]).strip()]
            has_strong = (len(strong_matches) > 0)

            score = 0.0
            if has_strong:
                score += 1000.0 + len(strong_matches) * 100.0

            if c_sys != 'COMMON' and h_sys != 'COMMON' and c_sys == h_sys:
                score += 30.0
            elif h_sys != 'COMMON':
                score += 10.0

            if h_idx == c_idx + 1:
                score += 25.0
            elif h_idx == c_idx - 1:
                score += 15.0
            else:
                score -= dist * 5.0

            valid_candidates.append((h, score, has_strong, dist))

        if not valid_candidates:
            unresolved_conts.append(c)
            continue

        valid_candidates.sort(key=lambda x: (-x[2], -x[1], x[3], x[0]['scan_index']))
        best_h, best_score, best_has_strong, best_dist = valid_candidates[0]

        # Selection decision
        if best_has_strong:
            parent_map[best_h['scan_index']].append(c)
        else:
            # Check for ambiguity as in TEST 10:
            # If multiple candidates exist on the preceding side without strong identity:
            all_preceding = all(cand[0]['scan_index'] < c_idx for cand in valid_candidates)
            if len(valid_candidates) > 1 and all_preceding:
                unresolved_conts.append(c)
            elif best_dist == 1 and best_score >= 30.0:
                parent_map[best_h['scan_index']].append(c)
            else:
                unresolved_conts.append(c)

    stitched_docs: List[DocumentItem] = []
    stitched_summary: List[Tuple[str, List[str], str]] = []

    for h in headers:
        h_idx = h['scan_index']
        children = parent_map.get(h_idx, [])
        all_pages = [f"output/form_samples/{h['file_name']}"] + [f"output/form_samples/{ch['file_name']}" for ch in children]

        merged_kf = dict(h.get('key_fields') or {})
        for ch in children:
            for k, v in (ch.get('key_fields') or {}).items():
                if v and not merged_kf.get(k):
                    merged_kf[k] = v

        doc_item = DocumentItem(
            doc_id=f"DOC_{h_idx:03d}",
            file_name=h['file_name'],
            doc_type=h['doc_type'],
            system=h['system'],
            confidence=h.get('confidence', 1.0),
            status=h.get('status', 'DAT'),
            action=h.get('action', 'PASS'),
            key_fields=merged_kf,
            image_path=all_pages[0],
            page_files=all_pages,
            is_multi_page=(len(all_pages) > 1),
            page_count=len(all_pages),
            scan_index=h_idx,
            evidence=h.get('evidence', {})
        )
        stitched_docs.append(doc_item)
        if len(all_pages) > 1:
            stitched_summary.append((h['file_name'], [ch['file_name'] for ch in children], h['doc_type']))

    for u in unresolved_conts:
        u_idx = u.get('scan_index', 0)
        u_path = f"output/form_samples/{u['file_name']}"
        doc_item = DocumentItem(
            doc_id=f"UNRESOLVED_CONT_{u_idx:03d}",
            file_name=u['file_name'],
            doc_type=u['doc_type'],
            system=u['system'],
            confidence=u.get('confidence', 0.5),
            status="CANH_BAO",
            action="UNRESOLVED_CONTINUATION",
            key_fields=u.get('key_fields') or {},
            image_path=u_path,
            page_files=[u_path],
            is_multi_page=False,
            page_count=1,
            scan_index=u_idx,
            evidence=u.get('evidence', {})
        )
        stitched_docs.append(doc_item)

    return stitched_docs, stitched_summary

# --- 3. MULTI-PASS SHIPMENT RESOLVER & IDENTITY PROPAGATION (P0) ---

def _norm_form_marker(s: Any) -> str:
    """Bỏ dấu + upper + gộp khoảng trắng (cùng dạng evidence.doc_keyword của Tầng 2)."""
    import unicodedata
    t = str(s or "").replace("Đ", "D").replace("đ", "d")
    t = unicodedata.normalize("NFD", t)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", t.upper()).strip()


def _resolve_standalone_form_variant(doc: "DocumentItem", config: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Chọn biến thể biểu mẫu (vd 4.1 vs 4.2 của BB_THU_HOI) theo evidence.doc_keyword.
    Trả (variant, note). Khớp đúng 1 biến thể -> variant; 0 / >=2 / thiếu config -> (None, lý do).
    KHÔNG dùng system, KHÔNG dùng tên file, KHÔNG có mặc định."""
    variants = (config.get('standalone_form_variants') or {}).get(doc.doc_type)
    kw_raw = doc.evidence.get('doc_keyword', '') if isinstance(doc.evidence, dict) else ''
    kw = _norm_form_marker(kw_raw)
    if not variants:
        return None, {"isolation_reason": "FORM_VARIANT_CONFIG_MISSING", "doc_keyword": kw_raw}
    hits = []
    for v in variants:
        markers = [_norm_form_marker(m) for m in (v.get('doc_keyword_contains_any') or [])]
        matched = [m for m in markers if m and m in kw]
        if matched:
            hits.append((v, matched))
    if len(hits) == 1:
        return hits[0][0], {"form_variant": hits[0][0].get('variant_id'), "matched_markers": hits[0][1]}
    if not hits:
        return None, {"isolation_reason": "FORM_VARIANT_UNRESOLVED", "doc_keyword": kw_raw,
                      "candidate_batches": sorted(v.get('batch_id') for v in variants)}
    return None, {"isolation_reason": "FORM_VARIANT_AMBIGUOUS", "doc_keyword": kw_raw,
                  "candidate_batches": sorted(v.get('batch_id') for v, _ in hits)}


def resolve_batch_identity_direct(doc: DocumentItem, config: Dict[str, Any]) -> Optional[Tuple[str, str, str, str, str, str]]:
    """
    Pass 1: Bóc tách Mỏ neo Định danh Trực tiếp (Direct Identity Anchor).
    Chỉ gán nếu có bằng chứng trực tiếp mạnh mẽ (shipment_id, transfer_order_no, standalone doc type).
    Trả về None nếu tài liệu cần được giải quyết qua lan truyền quan hệ (Propagation).
    """
    kf = doc.key_fields
    dt = doc.doc_type
    sys_name = doc.system
    sys_meta = config.get('system_metadata', {})
    exceptions = config.get('business_exceptions', [])
    aliases = config.get('shipment_aliases', [])
    doc_rules = config.get('doc_type_rules', [])

    # 1. Standalone document types
    if dt in (config.get('standalone_form_variants') or {}) or dt == 'BB_THU_HOI':
        # Tách lô theo BẰNG CHỨNG BIỂU MẪU (evidence.doc_keyword), không theo system:
        # trước đây `sys_name == 'COOP'` -> 4.1, còn lại -> 4.2 (silent default) => Tầng 2 ra
        # đúng kênh GT cho DX_THUHOI4.1 là chứng từ 4.1 bị gom nhầm vào lô 4.2 NPP.
        variant, _reason = _resolve_standalone_form_variant(doc, config)
        if variant is None:
            return None  # không đoán -> cách ly ở Pass 4 (lý do ghi trong batch_assignment)
        return (variant['batch_id'], variant['order_code'], variant['system'],
                "BUSINESS_DOC", variant['variant_id'], "MEDIUM")

    if dt in ['BB_NO_HANG', 'BB_TRA_HANG']:
        return "BATCH_6.x_GENERAL", "6.x", "GENERAL", "BUSINESS_DOC", "6.x", "MEDIUM"

    if dt == 'BBBG_PALLET':
        return "BATCH_PALLET_GENERAL", "PALLET", "GENERAL", "BUSINESS_DOC", "PALLET", "MEDIUM"

    if dt in ['LENH_DIEU_XE', 'BIEU_DO_NHIET_DO']:
        return "BATCH_CHUNG_GENERAL", "CHUNG", "GENERAL", "BUSINESS_DOC", "CHUNG", "LOW"

    # 2. Business doc_type rules (e.g. BBBG_HOADON -> 2.2, PHIEU_XUAT_HANG -> 5.1)
    # Luật (doc_type -> quy trình) là nghiệp vụ tổng quát; ĐỊNH DANH LÔ (mã chuyến/lệnh cụ thể)
    # là dữ liệu tham chiếu, lấy qua exception_rule_id từ config/stage3_shipment_reference.json.
    # Không có ngoại lệ tham chiếu -> luật KHÔNG kích hoạt (không đoán lô), rơi xuống pass sau.
    exceptions_by_id = {e.get('rule_id'): e for e in exceptions}
    for dr in doc_rules:
        if dt == dr.get('doc_type'):
            exp = exceptions_by_id.get(dr.get('exception_rule_id'))
            if not exp:
                continue
            code = dr['target_order_code']
            bid = f"SHIP_{exp['key_value']}_{exp['system']}"
            return bid, code, exp['system'], "DOC_TYPE_RULE", code, "HIGH"

    # 3. Business exceptions in config (with context and invoice guard)
    inv_no = kf.get('invoice_no')
    for exp in exceptions:
        ktype = exp['key_type']
        kval = exp['key_value']
        if kf.get(ktype) == kval:
            # P0.3 FP Guard — KHÔNG hardcode: danh sách loại trừ đọc thẳng từ
            # config/stage3_business_rules.json (excluded_systems / excluded_invoices).
            # Ngoại lệ nào không khai báo loại trừ thì không bị chặn.
            excluded_systems = exp.get('excluded_systems') or []
            excluded_invoices = exp.get('excluded_invoices') or []
            if sys_name in excluded_systems:
                continue
            if inv_no and inv_no in excluded_invoices:
                continue
            bid = f"SHIP_{kval}_{exp['system']}"
            return bid, exp['order_code'], exp['system'], exp['key_type'].upper(), kval, "HIGH"

    # 4. Check shipment aliases (secondary_id -> primary_id)
    ship = kf.get('shipment_id')
    to = kf.get('transfer_order_no')
    for alias in aliases:
        if (ship and (ship == alias['primary_id'] or ship in alias.get('secondary_ids', []))) or \
           (to and (to == alias['primary_id'] or to in alias.get('secondary_ids', []))):
            target_sys = alias['system']
            return f"SHIP_{alias['primary_id']}_{target_sys}", alias['order_code'], target_sys, "SHIPMENT_ALIAS", alias['primary_id'], "HIGH"

    # 5. Direct transfer_order_no (Priority 2)
    if to:
        code = sys_meta.get(sys_name, {}).get('order_code', '5.x' if 'KHO' in sys_name else '2.3')
        return f"SHIP_{to}_{sys_name}", code, sys_name, "TRANSFER_ORDER", to, "HIGH"

    # 6. Direct shipment_id (Priority 1)
    if ship:
        code = sys_meta.get(sys_name, {}).get('order_code', 'CHUNG')
        return f"SHIP_{ship}_{sys_name}", code, sys_name, "SHIPMENT_ID", ship, "HIGH"

    return None

def _rules_blocked_by_missing_reference(doc: "DocumentItem", config: Dict[str, Any]) -> List[str]:
    """Luật doc_type_rules/domain_rules khớp chứng từ nhưng exception_rule_id không có trong
    dữ liệu tham chiếu đã nạp (thiếu file config/stage3_shipment_reference.json)."""
    exc_ids = {e.get('rule_id') for e in config.get('business_exceptions', [])}
    out = []
    for r in list(config.get('doc_type_rules', [])) + list(config.get('domain_rules', [])):
        if r.get('doc_type') and r['doc_type'] != doc.doc_type:
            continue
        if r.get('system') and r['system'] != doc.system:
            continue
        eid = r.get('exception_rule_id')
        if eid and eid not in exc_ids:
            out.append(r.get('rule_id'))
    return sorted(x for x in out if x)


SYSTEM_CONTEXT_GUARD_DEFAULTS = {
    "identifier_conflict_same_doc_type": True,
    "exclude_multi_system_shipments": True,
}


def _system_context_guards(config: Dict[str, Any]) -> Dict[str, bool]:
    """Guard cho Pass 3.2 (lan truyền theo hệ thống). Đọc config['system_context_guards'];
    khóa thiếu -> mặc định BẬT (an toàn: chỉ chặn gom, không mở gom). Khóa lạ -> lỗi tường minh."""
    g = dict(SYSTEM_CONTEXT_GUARD_DEFAULTS)
    user = {k: v for k, v in (config.get('system_context_guards') or {}).items() if not str(k).startswith('_')}
    unknown = set(user) - set(g)
    if unknown:
        raise ValueError(f"system_context_guards: khóa không hỗ trợ {sorted(unknown)}")
    g.update({k: bool(v) for k, v in user.items()})
    return g


def has_identity_conflict(doc1: DocumentItem, doc2: DocumentItem) -> bool:
    """Kiểm tra xem hai chứng từ có mâu thuẫn định danh hay không."""
    if doc1.system not in ['COMMON', 'GENERAL'] and doc2.system not in ['COMMON', 'GENERAL'] and doc1.system != doc2.system:
        return True
    kf1 = doc1.key_fields
    kf2 = doc2.key_fields
    for k in ['shipment_id', 'transfer_order_no', 'invoice_no']:
        v1 = kf1.get(k)
        v2 = kf2.get(k)
        if v1 and v2 and str(v1).strip() != str(v2).strip():
            return True
    return False

def resolve_batch_identity(doc: DocumentItem, config: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    """Compatibility wrapper for single-document resolution."""
    res = resolve_batch_identity_direct(doc, config)
    if res:
        return res
    po = doc.key_fields.get('po_no')
    sys_name = doc.system
    sys_meta = config.get('system_metadata', {})
    if po and sys_name in ['BHX', 'WINMART', 'EMART']:
        code = sys_meta.get(sys_name, {}).get('order_code', '3.x')
        return f"BATCH_{code}_{sys_name}", code, sys_name, "BUSINESS_KEY", po, "HIGH"
    return f"UNRESOLVED_{doc.doc_id}", "CHUNG", sys_name, "UNRESOLVED", doc.doc_id, "LOW"

def resolve_shipment_batches(documents: List[DocumentItem], config: Dict[str, Any]) -> List[ShipmentBatch]:
    """
    Gom cụm Lô Chuyến Xe Đơn Định qua Luồng Lan Truyền Định Danh 4 Bước (4-Pass Identity Propagation):
    - Pass 1: Direct Identity Anchors (Bóc tách mỏ neo định danh trực tiếp & standalone docs).
    - Pass 2: Resolve Relationships (Xây dựng đồ thị quan hệ qua po_no, invoice_no, pxk_no).
    - Pass 3: Propagate Shipment Identity with Conflict Guard (Lan truyền định danh theo liên kết đơn hàng & ngữ cảnh chỉ huy giao hàng).
    - Pass 4: Safe Isolation (Cách ly an toàn các tài liệu thiếu chứng cứ thành UNRESOLVED).
    """
    sys_meta = config.get('system_metadata', {})
    assigned_batch: Dict[str, Tuple[str, str, str, str, str, str]] = {}
    known_shipments: Dict[str, Dict[str, Any]] = {}
    pass_of: Dict[str, str] = {}          # doc_id -> pass đã gán lô
    assign_warnings: Dict[str, str] = {}  # doc_id -> cảnh báo khi gán
    isolation_notes: Dict[str, Dict[str, Any]] = {}  # doc_id -> lý do không lan truyền được

    # === PASS 1: DIRECT IDENTITY ANCHORS ===
    for doc in documents:
        direct_res = resolve_batch_identity_direct(doc, config)
        if direct_res:
            bid, code, sys_n, id_type, id_val, conf = direct_res
            assigned_batch[doc.doc_id] = direct_res
            pass_of[doc.doc_id] = "1"
            if bid not in known_shipments:
                known_shipments[bid] = {
                    'batch_id': bid,
                    'order_code': code,
                    'system': sys_n,
                    'identity_type': id_type,
                    'identity_value': id_val,
                    'confidence': conf,
                    'docs': []
                }
            known_shipments[bid]['docs'].append(doc.doc_id)

    # --- Guard ngữ cảnh hệ thống (xem _system_context_guards) ---
    guards = _system_context_guards(config)
    # G2 — Chuyến ĐA HỆ THỐNG: cùng một mã chuyến (shipment_id / lệnh điều động) được neo dưới
    # >= 2 hệ thống khác nhau ở Pass 1 => chuyến đó chở hàng cho nhiều khách (giao qua NPP /
    # ghép chuyến), nhãn hệ thống của nó KHÔNG phải "chuyến duy nhất của khách này" => không
    # dùng làm ngữ cảnh lan truyền theo hệ thống (3.2), và không chặn việc lập lô BUSINESS_KEY.
    multi_system_batches: Dict[str, List[str]] = {}
    if guards["exclude_multi_system_shipments"]:
        _systems_of_identity: Dict[str, set] = defaultdict(set)
        for b in known_shipments.values():
            if b['identity_type'] in ('SHIPMENT_ID', 'TRANSFER_ORDER'):
                _systems_of_identity[str(b['identity_value'])].add(b['system'])
        for b in known_shipments.values():
            if b['identity_type'] in ('SHIPMENT_ID', 'TRANSFER_ORDER'):
                syss = _systems_of_identity[str(b['identity_value'])]
                if len(syss) > 1:
                    multi_system_batches[b['batch_id']] = sorted(syss)

    # Supermarket batches defined by BUSINESS_KEY (PO) when no direct shipment_id exists (3.1 BHX, 3.6 WINMART, 3.7 EMART)
    for doc in documents:
        if doc.doc_id in assigned_batch:
            continue
        po = doc.key_fields.get('po_no')
        sys_n = doc.system
        if po and sys_n in ['BHX', 'WINMART', 'EMART']:
            existing_sys_anchors = [b for b in known_shipments.values() if b['system'] == sys_n
                                    and b['batch_id'] not in multi_system_batches]
            if not existing_sys_anchors:
                code = sys_meta.get(sys_n, {}).get('order_code', '3.x')
                bid = f"BATCH_{code}_{sys_n}"
                res = (bid, code, sys_n, "BUSINESS_KEY", po, "HIGH")
                assigned_batch[doc.doc_id] = res
                pass_of[doc.doc_id] = "1"
                known_shipments[bid] = {
                    'batch_id': bid,
                    'order_code': code,
                    'system': sys_n,
                    'identity_type': "BUSINESS_KEY",
                    'identity_value': po,
                    'confidence': "HIGH",
                    'docs': [doc.doc_id]
                }

    # === PASS 2 & 3: RELATIONSHIP EVIDENCE & IDENTITY PROPAGATION ===
    # 3.1 Direct Order-Level Link (shared PO, Invoice, PXK)
    unassigned = [d for d in documents if d.doc_id not in assigned_batch]
    for d in unassigned:
        kf = d.key_fields
        po = kf.get('po_no')
        inv = kf.get('invoice_no')
        pxk = kf.get('pxk_no')

        matched_target = None
        for a_id, a_meta in assigned_batch.items():
            a_doc = next((x for x in documents if x.doc_id == a_id), None)
            if not a_doc:
                continue
            a_kf = a_doc.key_fields

            # Conflict Guard: System conflict check
            if d.system != 'COMMON' and a_doc.system != 'COMMON' and d.system != a_doc.system:
                continue
            # Conflict Guard: Direct shipment conflict
            if kf.get('shipment_id') and a_kf.get('shipment_id') and kf['shipment_id'] != a_kf['shipment_id']:
                continue

            shared_keys = []
            if po and a_kf.get('po_no') and po == a_kf['po_no']:
                shared_keys.append(('po_no', po))
            if inv and a_kf.get('invoice_no') and inv == a_kf['invoice_no']:
                shared_keys.append(('invoice_no', inv))
            if pxk and a_kf.get('pxk_no') and pxk == a_kf['pxk_no']:
                shared_keys.append(('pxk_no', pxk))

            if shared_keys:
                matched_target = (a_meta, shared_keys)
                break

        if matched_target:
            a_meta, shared = matched_target
            bid, code, sys_n, _, _, _ = a_meta
            assigned_batch[d.doc_id] = (bid, code, sys_n, "RELATIONSHIP_PROPAGATION", shared[0][1], "HIGH")
            pass_of[d.doc_id] = "2"
            if bid in known_shipments:
                known_shipments[bid]['docs'].append(d.doc_id)

    # 3.2 System Delivery Context Propagation (Loading Plan, PGH, PO in specific supermarket systems)
    #
    # GIỚI HẠN THIẾT KẾ (đã đánh giá 27/09, CỐ Ý CHƯA TỔNG QUÁT HÓA):
    # Điều kiện `len(sys_shipments) == 1` giả định "hệ thống này chỉ có 1 lô ĐÃ NEO" tương đương
    # "hệ thống này chỉ có 1 chuyến". Đúng trên tập demo (mỗi siêu thị 1 chuyến), SAI ở
    # production nhiều chuyến/ngày cùng siêu thị theo HAI hướng:
    #   (a) >=2 lô đã neo -> chặn lan truyền -> chứng từ thiếu mã rơi UNRESOLVED (mất Recall,
    #       an toàn). Nay ghi tường minh isolation_reason = AMBIGUOUS_SYSTEM_CONTEXT + ứng viên.
    #   (b) nguy hiểm hơn: chỉ 1 chuyến neo được, chuyến kia mọi chứng từ đều đọc trượt mã ->
    #       chứng từ chuyến B bị lan truyền NHẦM vào chuyến A (FP im lặng). Không phát hiện
    #       được bằng dữ liệu hiện có. Mọi gán bằng nhánh này được đánh dấu confidence MEDIUM
    #       + cảnh báo SINGLE_KNOWN_ANCHOR_ASSUMPTION trong batch_assignment của chứng từ.
    # Muốn sửa tổng quát cần bằng chứng phân biệt chuyến ngoài mã chuyến (ngày giao, biển số
    # xe, mã điểm giao/cửa hàng, số PO <-> HĐ đọc được) VÀ tập dữ liệu có >=2 chuyến cùng hệ
    # thống kèm GT để kiểm chứng. KHÔNG dùng thứ tự scan_index làm bằng chứng: trên tập demo
    # thứ tự đó là thứ tự tên file (rò rỉ tên file mà permutation test không bắt được).
    # Ảnh chụp thành viên lô SAU Pass 1/2 (bằng chứng mạnh), TRƯỚC Pass 3.2 -> guard G1 không phụ
    # thuộc thứ tự duyệt (giữ permutation invariance).
    doc_by_id = {x.doc_id: x for x in documents}
    strong_members = {bid: list(b['docs']) for bid, b in known_shipments.items()}

    unassigned = [d for d in documents if d.doc_id not in assigned_batch]
    for d in unassigned:
        sys_n = d.system
        dt = d.doc_type
        kf = d.key_fields

        # Conflict Guard: Blank generic invoices with no fields must NOT be blindly merged (TEST 3)
        if dt == 'HOA_DON' and not any(kf.values()):
            isolation_notes[d.doc_id] = {"isolation_reason": "BLANK_INVOICE_NO_KEY_FIELDS"}
            continue

        # Look for unambiguous known delivery shipment for this specific supermarket system
        sys_all = [b for b in known_shipments.values()
                   if b['system'] == sys_n and sys_n not in ['COMMON', 'GENERAL', 'NPP']
                   and not b['batch_id'].startswith('BATCH_4.')] # Exclude returns (BB_THU_HOI)
        sys_shipments = [b for b in sys_all if b['batch_id'] not in multi_system_batches]
        excluded_multi = sorted(b['batch_id'] for b in sys_all if b['batch_id'] in multi_system_batches)

        if len(sys_shipments) == 1:
            target_b = sys_shipments[0]
            # Conflict Guard: Do not propagate if document has conflicting shipment_id
            if kf.get('shipment_id') and kf['shipment_id'] != target_b.get('identity_value'):
                isolation_notes[d.doc_id] = {"isolation_reason": "SHIPMENT_ID_CONFLICT_WITH_SYSTEM_CONTEXT",
                                             "candidate_batches": [target_b['batch_id']]}
                continue
            # G1 — Định danh riêng mâu thuẫn với chứng từ CÙNG LOẠI đã neo mạnh trong lô đích.
            # Chứng từ mang số riêng (invoice_no/po_no/pxk_no) mà số đó không khớp BẤT KỲ chứng
            # từ cùng doc_type nào đã neo bằng bằng chứng mạnh (Pass 1/2) trong lô đích, trong khi
            # lô đích ĐÃ có chứng từ cùng loại mang số khác => chính chứng từ đang tự khai "tôi là
            # một đơn khác". Bằng chứng còn lại để gom chỉ là "cùng khách hàng" — đúng giả định
            # len(sys_shipments)==1 (AGENTS 9.11.F.3) không kiểm chứng được => cách ly, ghi vết.
            # Một chuyến nhiều hóa đơn vẫn gom được khi các hóa đơn có mã chuyến / chung PO
            # (Pass 1/2), không đi qua nhánh này.
            if guards["identifier_conflict_same_doc_type"]:
                conflict = None
                for fld in ('invoice_no', 'po_no', 'pxk_no'):
                    v = kf.get(fld)
                    if not v:
                        continue
                    peer_vals = sorted({str(doc_by_id[m].key_fields.get(fld))
                                        for m in strong_members.get(target_b['batch_id'], [])
                                        if m in doc_by_id and doc_by_id[m].doc_type == dt
                                        and doc_by_id[m].key_fields.get(fld)})
                    if peer_vals and str(v) not in peer_vals:
                        conflict = {"field": fld, "doc_value": v, "target_same_type_values": peer_vals}
                        break
                if conflict:
                    isolation_notes[d.doc_id] = {"isolation_reason": "IDENTIFIER_CONFLICT_WITH_SYSTEM_CONTEXT",
                                                 "candidate_batches": [target_b['batch_id']],
                                                 "guard": "G1_IDENTIFIER_CONFLICT_SAME_DOC_TYPE",
                                                 "guard_evidence": conflict}
                    continue

            if dt in ['LOADING_PLAN', 'PHIEU_GIAO_HANG', 'PO', 'HOA_DON', 'PHIEU_NHAP_KHO']:
                bid = target_b['batch_id']
                code = target_b['order_code']
                assigned_batch[d.doc_id] = (bid, code, sys_n, "SYSTEM_CONTEXT_PROPAGATION", target_b['identity_value'], "MEDIUM")
                target_b['docs'].append(d.doc_id)
                pass_of[d.doc_id] = "3.2"
                assign_warnings[d.doc_id] = "SINGLE_KNOWN_ANCHOR_ASSUMPTION"
            else:
                isolation_notes[d.doc_id] = {"isolation_reason": "DOC_TYPE_NOT_ELIGIBLE_FOR_SYSTEM_CONTEXT",
                                             "candidate_batches": [target_b['batch_id']]}
        elif len(sys_shipments) > 1:
            # Không chọn bừa 1 trong nhiều chuyến -> cách ly, nhưng GHI LÝ DO + ứng viên.
            isolation_notes[d.doc_id] = {"isolation_reason": "AMBIGUOUS_SYSTEM_CONTEXT",
                                         "candidate_batches": sorted(b['batch_id'] for b in sys_shipments)}
        elif excluded_multi and not sys_shipments:
            # Lô duy nhất của hệ thống là chuyến đa hệ thống (G2) -> không lan truyền.
            isolation_notes[d.doc_id] = {"isolation_reason": "MULTI_SYSTEM_SHIPMENT_CONTEXT",
                                         "candidate_batches": excluded_multi,
                                         "guard": "G2_EXCLUDE_MULTI_SYSTEM_SHIPMENT",
                                         "guard_evidence": {b: multi_system_batches[b] for b in excluded_multi}}
        elif sys_n in ['COMMON', 'GENERAL', 'NPP']:
            # Hệ thống bị loại khỏi lan truyền theo ngữ cảnh (NPP vốn nhiều chuyến / COMMON không
            # mang ngữ cảnh). Ghi các lô đã neo cùng hệ thống để người kiểm tra thấy vì sao.
            cands = sorted(b['batch_id'] for b in known_shipments.values()
                           if b['system'] == sys_n and not b['batch_id'].startswith('BATCH_4.'))
            isolation_notes[d.doc_id] = {"isolation_reason": "SYSTEM_CONTEXT_NOT_APPLICABLE",
                                         "candidate_batches": cands}
        else:
            isolation_notes[d.doc_id] = {"isolation_reason": "NO_ANCHORED_BATCH_FOR_SYSTEM"}

    # Chứng từ standalone nhiều biểu mẫu (BB_THU_HOI) không xác định được biến thể ở Pass 1
    # -> ghi đè lý do cách ly bằng lý do biểu mẫu (tường minh, không đoán theo system).
    for d in documents:
        if d.doc_id not in assigned_batch and (d.doc_type in (config.get('standalone_form_variants') or {})
                                               or d.doc_type == 'BB_THU_HOI'):
            _v, note = _resolve_standalone_form_variant(d, config)
            if _v is None:
                isolation_notes[d.doc_id] = note

    # 3.3 Specific Domain Rules (Warehouse & Delivery Slips)
    # KHÔNG hardcode mã kho/mã lô trong logic: toàn bộ luật đọc từ
    # config/stage3_business_rules.json -> domain_rules, và định danh lô được
    # suy ra từ business_exceptions thông qua exception_rule_id.
    exceptions_by_id = {e.get('rule_id'): e for e in config.get('business_exceptions', [])}
    d_rule_hits: Dict[str, str] = {}
    domain_rules = [r for r in config.get('domain_rules', []) if str(r.get('pass', '3.3')) == '3.3']

    unassigned = [d for d in documents if d.doc_id not in assigned_batch]
    for d in unassigned:
        dt = d.doc_type
        sys_n = d.system
        kw = d.evidence.get('doc_keyword', '') if hasattr(d, 'evidence') and isinstance(d.evidence, dict) else ''
        for rule in domain_rules:
            if rule.get('doc_type') and rule['doc_type'] != dt:
                continue
            if rule.get('system') and rule['system'] != sys_n:
                continue
            needle = rule.get('evidence_keyword_contains')
            if needle and needle not in (kw or ''):
                continue
            exp = exceptions_by_id.get(rule.get('exception_rule_id'))
            if not exp:
                # Luật trỏ tới một ngoại lệ không tồn tại -> KHÔNG đoán, bỏ qua.
                continue
            kval = exp['key_value']
            bid = f"SHIP_{kval}_{exp['system']}"
            assigned_batch[d.doc_id] = (bid, exp['order_code'], exp['system'],
                                        rule.get('identity_type', 'DOMAIN_RULE'), kval, "HIGH")
            pass_of[d.doc_id] = "3.3"
            assign_warnings.pop(d.doc_id, None)
            isolation_notes.pop(d.doc_id, None)
            d_rule_hits[d.doc_id] = rule.get('rule_id')
            if bid in known_shipments:
                known_shipments[bid]['docs'].append(d.doc_id)
            break
        # TUYỆT ĐỐI KHÔNG DÙNG SILENT DEFAULT FALLBACK!
        # Không khớp luật nào -> document rơi tự nhiên xuống Pass 4: Safe Isolation.

    # === PASS 4: SAFE ISOLATION ===
    unassigned = [d for d in documents if d.doc_id not in assigned_batch]
    for d in unassigned:
        assigned_batch[d.doc_id] = (f"UNRESOLVED_{d.doc_id}", "CHUNG", d.system, "UNRESOLVED", d.doc_id, "LOW")
        pass_of[d.doc_id] = "4"

    # Dấu vết gom lô cấp chứng từ (xuất ra manifest -> Tầng 4 / người kiểm tra thấy được).
    for doc in documents:
        bid, code, sys_n, id_type, id_val, conf = assigned_batch[doc.doc_id]
        rec = {"pass": pass_of.get(doc.doc_id), "method": id_type, "confidence": conf,
               "evidence_value": id_val}
        if doc.doc_id in d_rule_hits:
            rec["rule_id"] = d_rule_hits[doc.doc_id]
        if doc.doc_id in assign_warnings:
            rec["warning"] = assign_warnings[doc.doc_id]
        if id_type == "UNRESOLVED":
            rec.update(isolation_notes.get(doc.doc_id) or {"isolation_reason": "NO_IDENTITY_EVIDENCE"})
            blocked = _rules_blocked_by_missing_reference(doc, config)
            if blocked:
                # Tường minh: luật nghiệp vụ khớp doc_type nhưng định danh lô nằm trong dữ liệu
                # tham chiếu không được nạp -> không đoán, chỉ ghi vết.
                rec["reference_blocked_rules"] = blocked
        doc.batch_assignment = rec

    # Build ShipmentBatch objects
    batches_map: Dict[str, List[DocumentItem]] = defaultdict(list)
    batch_meta: Dict[str, Tuple[str, str, str, str, str]] = {}

    for doc in documents:
        bid, code, sys_n, id_type, id_val, conf = assigned_batch[doc.doc_id]
        batches_map[bid].append(doc)
        if bid not in batch_meta or conf == "HIGH":
            batch_meta[bid] = (code, sys_n, id_type, id_val, conf)

    shipment_batches: List[ShipmentBatch] = []
    for b_key in sorted(batches_map.keys()):
        b_docs = batches_map[b_key]
        code, sys_n, id_type, id_val, conf = batch_meta[b_key]
        batch = ShipmentBatch(
            batch_id=b_key,
            order_code=code,
            system=sys_n,
            identity_type=id_type,
            identity_value=id_val,
            confidence=conf
        )
        batch.documents = b_docs
        shipment_batches.append(batch)

    return shipment_batches

# --- 4. ORDER DOSSIER GRAPH & UNION-FIND (P1) ---

class UnionFind:
    """Cấu trúc dữ liệu Disjoint-Set / Union-Find tối ưu."""
    def __init__(self, items: List[str]):
        self.parent = {item: item for item in items}
    def find(self, i: str) -> str:
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]
    def union(self, i: str, j: str):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j

def build_order_dossiers_for_batch(batch: ShipmentBatch) -> List[OrderDossier]:
    """Gom nhóm tài liệu trong cùng một Lô thành các Hồ sơ đơn hàng con (OrderDossier)."""
    docs = batch.documents
    if not docs:
        return []

    doc_ids = [d.doc_id for d in docs]
    uf = UnionFind(doc_ids)

    po_buckets = defaultdict(list)
    inv_buckets = defaultdict(list)
    pxk_buckets = defaultdict(list)

    for d in docs:
        kf = d.key_fields
        if kf.get('po_no'): po_buckets[kf['po_no']].append(d.doc_id)
        if kf.get('invoice_no'): inv_buckets[kf['invoice_no']].append(d.doc_id)
        if kf.get('pxk_no'): pxk_buckets[kf['pxk_no']].append(d.doc_id)

    for buckets in [po_buckets, inv_buckets, pxk_buckets]:
        for key, members in buckets.items():
            for m in members[1:]:
                uf.union(members[0], m)

    # Triệt tiêu toàn bộ heuristic union vô căn cứ giữa LP và PXK
    # Chỉ union các tài liệu có chung khóa trường thực tế (po_no, invoice_no, pxk_no)

    clusters = defaultdict(list)
    doc_lookup = {d.doc_id: d for d in docs}
    for did in doc_ids:
        root = uf.find(did)
        clusters[root].append(doc_lookup[did])

    dossiers: List[OrderDossier] = []
    for c_idx, (root, c_docs) in enumerate(sorted(clusters.items())):
        # XÁC ĐỊNH HÓA (27/09): trước đây dùng list(set)[0]. Thứ tự duyệt set chuỗi phụ thuộc
        # PYTHONHASHSEED (ngẫu nhiên mỗi tiến trình) -> khi cụm có >=2 PO/INV/PXK khác nhau,
        # dossier_id và po_no/invoice_no/pxk_no đổi giữa các lần chạy (đã tái hiện:
        # scratch/_phase4/stage3/probe_nondeterminism_before.log). Nay dùng sorted().
        # Chọn phần tử nhỏ nhất theo thứ tự từ điển là QUY ƯỚC ĐẶT TÊN, không phải bằng chứng
        # nghiệp vụ -> toàn bộ giá trị được ghi tường minh vào `ambiguous_keys`.
        po_vals = sorted(set(d.key_fields.get('po_no') for d in c_docs if d.key_fields.get('po_no')), key=str)
        inv_vals = sorted(set(d.key_fields.get('invoice_no') for d in c_docs if d.key_fields.get('invoice_no')), key=str)
        pxk_vals = sorted(set(d.key_fields.get('pxk_no') for d in c_docs if d.key_fields.get('pxk_no')), key=str)

        name_parts = []
        if po_vals: name_parts.append(f"PO_{po_vals[0]}")
        if inv_vals: name_parts.append(f"INV_{inv_vals[0]}")
        if pxk_vals: name_parts.append(f"PXK_{pxk_vals[0]}")
        if not name_parts: name_parts.append(f"DOC_{c_docs[0].doc_id}")

        dossier_id = f"ORDER_{batch.batch_id}_{'_'.join(name_parts)}"
        dos = OrderDossier(
            dossier_id=dossier_id,
            po_no=po_vals[0] if po_vals else None,
            invoice_no=inv_vals[0] if inv_vals else None,
            pxk_no=pxk_vals[0] if pxk_vals else None
        )
        dos.ambiguous_keys = {k: v for k, v in (("po_no", po_vals), ("invoice_no", inv_vals),
                                                  ("pxk_no", pxk_vals)) if len(v) > 1}
        dos.documents = c_docs
        dossiers.append(dos)

    return dossiers

# --- 5. FIELD-LEVEL EVIDENCE RECONCILIATION (P1) ---

def reconcile_order_dossier_fields(dossier: OrderDossier, batch: ShipmentBatch) -> None:
    """Đối soát chéo cấp trường dữ liệu với đầy đủ minh chứng MATCH/MISMATCH/MISSING."""
    evidences: List[ReconciliationEvidence] = []
    docs = dossier.documents
    batch_docs = batch.documents

    # 1. Multi-invoice duplicate reconciliation inside dossier
    inv_docs = [d for d in docs if d.doc_type == 'HOA_DON']
    if len(inv_docs) >= 2:
        for i in range(len(inv_docs)):
            for j in range(i + 1, len(inv_docs)):
                d1, d2 = inv_docs[i], inv_docs[j]
                inv1 = d1.key_fields.get('invoice_no')
                inv2 = d2.key_fields.get('invoice_no')
                if inv1 and inv2:
                    st = "MATCH" if inv1 == inv2 else "MISMATCH"
                    evidences.append(ReconciliationEvidence(
                        field="invoice_no", source_doc=d1.doc_id, target_doc=d2.doc_id,
                        source_val=inv1, target_val=inv2, status=st,
                        notes=f"Đối soát số hóa đơn các liên: {inv1} vs {inv2}"
                    ))
                ship1 = d1.key_fields.get('shipment_id')
                ship2 = d2.key_fields.get('shipment_id')
                if ship1 and ship2:
                    st = "MATCH" if ship1 == ship2 else "MISMATCH"
                    evidences.append(ReconciliationEvidence(
                        field="shipment_id", source_doc=d1.doc_id, target_doc=d2.doc_id,
                        source_val=ship1, target_val=ship2, status=st,
                        notes=f"Đối soát mã chuyến các liên: {ship1} vs {ship2}"
                    ))

    # 2. Batch-level cross-document reconciliation (PO vs Invoice / PGH)
    all_inv = [d for d in batch_docs if d.doc_type == 'HOA_DON']
    all_pgh = [d for d in batch_docs if d.doc_type == 'PHIEU_GIAO_HANG']
    all_lp = [d for d in batch_docs if d.doc_type == 'LOADING_PLAN']
    all_pxk = [d for d in batch_docs if d.doc_type == 'PXKKVCNB']

    # Reconcile if current dossier contains PO
    for p in [d for d in docs if d.doc_type == 'PO']:
        p_val = p.key_fields.get('po_no')
        for inv in all_inv:
            inv_po = inv.key_fields.get('po_no')
            if p_val and inv_po:
                if p_val == inv_po:
                    st = "MATCH"
                elif p_val[:4] == inv_po[:4]:
                    st = "PARTIAL_MATCH"
                else:
                    st = "MISMATCH"
            elif p_val and not inv_po:
                st = "MISSING_TARGET"
            elif not p_val and inv_po:
                st = "MISSING_SOURCE"
            else:
                st = "NOT_APPLICABLE"
            evidences.append(ReconciliationEvidence(
                field="po_no", source_doc=p.doc_id, target_doc=inv.doc_id,
                source_val=p_val or "NONE", target_val=inv_po or "NONE", status=st,
                notes=f"Đối soát PO: {p_val} vs Hóa đơn: {inv_po}"
            ))
        for pgh in all_pgh:
            pgh_po = pgh.key_fields.get('po_no')
            if p_val and pgh_po:
                if p_val == pgh_po:
                    st = "MATCH"
                elif p_val[:3] == pgh_po[:3]:
                    st = "PARTIAL_MATCH"
                else:
                    st = "MISMATCH"
            elif p_val and not pgh_po:
                st = "MISSING_TARGET"
            elif not p_val and pgh_po:
                st = "MISSING_SOURCE"
            else:
                st = "NOT_APPLICABLE"
            evidences.append(ReconciliationEvidence(
                field="po_no", source_doc=p.doc_id, target_doc=pgh.doc_id,
                source_val=p_val or "NONE", target_val=pgh_po or "NONE", status=st,
                notes=f"Đối soát PO: {p_val} vs PGH: {pgh_po}"
            ))

    # Reconcile if current dossier contains Invoice (check against LP)
    for inv in [d for d in docs if d.doc_type == 'HOA_DON']:
        inv_ship = inv.key_fields.get('shipment_id')
        for lp in all_lp:
            lp_ship = lp.key_fields.get('shipment_id')
            if inv_ship and lp_ship:
                st = "MATCH" if inv_ship == lp_ship else "MISMATCH"
                evidences.append(ReconciliationEvidence(
                    field="shipment_id", source_doc=lp.doc_id, target_doc=inv.doc_id,
                    source_val=lp_ship, target_val=inv_ship, status=st,
                    notes=f"Đối soát chuyến xe: LP={lp_ship} vs HĐ={inv_ship}"
                ))

    # Reconcile if current dossier contains PXKKVCNB (check transfer_order_no and pxk_no against LP)
    for pxk_doc in [d for d in docs if d.doc_type == 'PXKKVCNB']:
        to_val = pxk_doc.key_fields.get('transfer_order_no')
        for lp in all_lp:
            lp_ship = lp.key_fields.get('shipment_id')
            if to_val and lp_ship:
                st = "MATCH" if to_val == lp_ship else "MISMATCH"
                evidences.append(ReconciliationEvidence(
                    field="transfer_order_no", source_doc=lp.doc_id, target_doc=pxk_doc.doc_id,
                    source_val=lp_ship, target_val=to_val, status=st,
                    notes=f"Đối soát lệnh điều động: LP={lp_ship} vs PXK={to_val}"
                ))

    dossier.reconciliation = evidences

    has_mismatch = any(e.status == "MISMATCH" for e in evidences)
    has_match = any(e.status in ["MATCH", "PARTIAL_MATCH"] for e in evidences)
    has_missing = any(e.status in ["MISSING_SOURCE", "MISSING_TARGET"] for e in evidences)

    if not evidences:
        if len(dossier.documents) > 1:
            dossier.match_status = "NO_EVIDENCE"
            dossier.match_notes = f"Gom cụm {len(dossier.documents)} chứng từ cùng đơn hàng nhưng chưa có cặp trường đối soát chéo áp dụng được"
        else:
            dossier.match_status = "DON_LE"
            dossier.match_notes = "Chứng từ độc lập, không có chứng từ đối soát chéo"
    elif has_mismatch:
        dossier.match_status = "XUNG_DOT"
        dossier.match_notes = "Phát hiện sai lệch trường khóa đối soát (MISMATCH)"
    elif has_match and not has_missing:
        dossier.match_status = "KHOP_HOAN_TOAN"
        dossier.match_notes = "100% trường đối soát khớp chính xác"
    elif has_match and has_missing:
        dossier.match_status = "KHOP_MOT_PHAN"
        dossier.match_notes = "Có trường khớp nhưng tồn tại trường khuyết thiếu ở 1 bên (PARTIAL_MATCH / MISSING)"
    elif has_missing and not has_match:
        dossier.match_status = "KHOP_MOT_PHAN"
        dossier.match_notes = "Tồn tại trường khuyết thiếu ở 1 bên đối soát (MISSING_TARGET / MISSING_SOURCE)"
    else:
        dossier.match_status = "DON_LE"
        dossier.match_notes = "Không đủ trường dữ liệu để kết luận đối soát"

# --- 6. CHECKLIST AUDIT & SEMANTICS (P1) ---

UNIVERSAL_FORM_CODE = "*"


def build_checklist_guidelines(catalog: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Làm giàu ma trận quy chuẩn KIDO (output/form_catalog.json -> 'guideline', 68 dòng)
    thành dạng dùng được cho audit: bổ sung `form_code` và `canonical_type`.

    - `form_code` suy từ tiền tố số của `order_detail` (vd "3.11 Hệ thống Satra" -> "3.11");
      nếu `order_detail` không mang mã thì lấy tiền tố số của `doc_type` (vd "4.2 Phiếu đề xuất...").
      Dòng `TẤT CẢ LOẠI HÌNH VẬN CHUYỂN` -> form_code "*" (áp dụng cho mọi lô).
    - `canonical_type` suy từ `canonical_form_patterns` trong config, khớp theo THỨ TỰ khai báo
      trên chuỗi `doc_type + form_sheet`. Không khớp -> None + mapping_status UNMAPPED_GUIDELINE
      (KHÔNG đoán bừa, KHÔNG silent default).
    """
    guidelines = catalog.get('guideline', []) or []
    patterns = config.get('canonical_form_patterns', []) or []
    compiled = [(re.compile(p['pattern'], re.IGNORECASE), p['doc_type']) for p in patterns if p.get('pattern')]

    code_re = re.compile(r'^\s*(\d+\.\d+)')
    enriched: List[Dict[str, Any]] = []
    for g in guidelines:
        row = dict(g)
        transport = (g.get('transport_type') or '')
        order_detail = (g.get('order_detail') or '')
        doc_name = (g.get('doc_type') or '')
        form_sheet = (g.get('form_sheet') or '')

        m = code_re.match(order_detail) or code_re.match(doc_name)
        if m:
            form_code = m.group(1)
        elif 'TẤT CẢ LOẠI HÌNH' in transport.upper() or 'TAT CA LOAI HINH' in transport.upper():
            form_code = UNIVERSAL_FORM_CODE
        else:
            form_code = None

        haystack = f"{doc_name} {form_sheet}"
        canonical = None
        for rx, dt in compiled:
            if rx.search(haystack):
                canonical = dt
                break

        row['form_code'] = form_code
        row['canonical_type'] = canonical
        row['guideline_mapping_status'] = (
            'MAPPED' if (form_code and canonical)
            else ('UNMAPPED_FORM_CODE' if canonical else 'UNMAPPED_GUIDELINE')
        )
        enriched.append(row)
    return enriched


def audit_checklist_compliance(batch: ShipmentBatch, catalog_guidelines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Đối chiếu quy chuẩn checklist KIDO, tách bạch rõ ràng document_count, page_count, copy_count."""
    order_code = batch.order_code
    # Quy chuẩn áp dụng = quy chuẩn riêng của mã biểu mẫu lô + quy chuẩn áp dụng cho
    # MỌI loại hình vận chuyển (form_code == "*": Lệnh điều xe, Biểu đồ nhiệt độ).
    # Chỉ nhận dòng quy chuẩn đã ánh xạ được canonical_type; dòng UNMAPPED được liệt kê riêng.
    applicable = [g for g in catalog_guidelines
                  if g.get('form_code') in (order_code, UNIVERSAL_FORM_CODE)]
    matched_gls = [g for g in applicable if g.get('canonical_type')]
    unmapped_gls = [g.get('doc_type') for g in applicable if not g.get('canonical_type')]

    present_types = set(d.doc_type for d in batch.documents)
    total_docs = len(batch.documents)
    total_pages = sum(d.page_count for d in batch.documents)

    checklist_results = []
    missing_docs = []

    for gl in matched_gls:
        req_type = gl.get('canonical_type')
        req_name = gl.get('doc_type', req_type)
        target_copies = gl.get('so_lien_in', 1)

        is_present = req_type in present_types
        if not is_present:
            missing_docs.append(req_name)

        checklist_results.append({
            "required_doc_type": req_type,
            "document_name": req_name,
            "present": is_present,
            "document_count": sum(1 for d in batch.documents if d.doc_type == req_type),
            "page_count": sum(d.page_count for d in batch.documents if d.doc_type == req_type),
            "observed_copy_count": 1 if is_present else 0,
            "required_copy_count": target_copies,
            "copy_count_status": "DEMO_SINGLE_SAMPLE" if is_present else "MISSING",
            "scope": "UNIVERSAL" if gl.get('form_code') == UNIVERSAL_FORM_CODE else "FORM_SPECIFIC"
        })

    if not matched_gls:
        # Không có quy chuẩn nào áp cho mã biểu mẫu này -> KHÔNG kết luận HOAN_HAO.
        overall_status = "KHONG_CO_QUY_CHUAN"
    elif not missing_docs:
        overall_status = "HOAN_HAO"
    else:
        overall_status = "THIEU_CHUNG_TU" if len(missing_docs) > 1 else "CANH_BAO_THIEU"

    batch.checklist_audit = {
        "order_code": order_code,
        "overall_status": overall_status,
        "applicable_rules": len(matched_gls),
        "unmapped_guideline_rows": unmapped_gls,
        "total_documents": total_docs,
        "total_pages": total_pages,
        "missing_documents": missing_docs,
        "checklist_details": checklist_results,
        "copy_count_note": "copy_count=1 là giới hạn quan sát trong mẫu demo Excel, không kết luận thiếu liên ngoài đời thực."
    }
    return batch.checklist_audit

# --- 7. SIGNATURE PRESET MAPPING (P1) ---

SIGNATURE_PRESET_MAP = {
    'HOA_DON': [
        {"role": "Người mua hàng", "expected_color": "blue_ink", "box_norm": [0.78, 0.08, 0.95, 0.42], "bbox": [0.78, 0.08, 0.95, 0.42], "description": "Chữ ký người nhận / mua hàng góc dưới trái", "desc": "Chữ ký người nhận / mua hàng góc dưới trái", "required": False},
        {"role": "Thủ trưởng đơn vị / Người bán", "expected_color": "blue_ink", "box_norm": [0.78, 0.58, 0.95, 0.94], "bbox": [0.78, 0.58, 0.95, 0.94], "description": "Chữ ký người bán / đại diện công ty góc dưới phải", "desc": "Chữ ký người bán / đại diện công ty góc dưới phải", "required": True},
        {"role": "Con dấu mộc đỏ", "expected_color": "red_stamp", "box_norm": [0.70, 0.52, 0.92, 0.90], "bbox": [0.70, 0.52, 0.92, 0.90], "description": "Mộc tròn đỏ pháp lý đè lên chữ ký người bán", "desc": "Mộc tròn đỏ pháp lý đè lên chữ ký người bán", "required": True}
    ],
    'PO': [
        {"role": "Người giao hàng", "expected_color": "blue_ink", "box_norm": [0.80, 0.08, 0.96, 0.45], "bbox": [0.80, 0.08, 0.96, 0.45], "description": "Tài xế giao hàng siêu thị ký tên", "desc": "Tài xế giao hàng siêu thị ký tên", "required": True},
        {"role": "Thủ kho siêu thị / Khách hàng", "expected_color": "blue_ink", "box_norm": [0.80, 0.55, 0.96, 0.94], "bbox": [0.80, 0.55, 0.96, 0.94], "description": "Người nhận hàng siêu thị ký xác nhận số lượng", "desc": "Người nhận hàng siêu thị ký xác nhận số lượng", "required": True},
        {"role": "Mộc vuông / Mộc tròn siêu thị", "expected_color": "red_stamp", "box_norm": [0.72, 0.50, 0.92, 0.92], "bbox": [0.72, 0.50, 0.92, 0.92], "description": "Con dấu xác nhận nhập kho của siêu thị", "desc": "Con dấu xác nhận nhập kho của siêu thị", "required": True}
    ],
    # LEGACY — chỉ phục vụ benchmark Tầng 4 v1 (GT output/stage4_gt_independent_v2.json +
    # test_stage4_suite 25/25 gắn target_id vào đúng 3 hộp này). ĐÃ BỊ THAY bởi zone động
    # Tầng 3b (5 vai trò, config/stage3b_loading_plan_labels.json). KHÔNG đổi hộp/thứ tự.
    # Production (kido_pipeline nhánh LOADING_PLAN) KHÔNG đọc preset này.
    'LOADING_PLAN': [
        {"role": "Thủ kho xuất", "expected_color": "blue_ink", "box_norm": [0.82, 0.06, 0.96, 0.35], "bbox": [0.82, 0.06, 0.96, 0.35], "description": "Thủ kho xuất hàng ký tên", "desc": "Thủ kho xuất hàng ký tên", "required": True, "target_source": "static_preset_legacy", "superseded_by": "stage3b_dynamic_zone", "use": "legacy_v1_benchmark_only"},
        {"role": "Lái xe nhận hàng", "expected_color": "blue_ink", "box_norm": [0.82, 0.36, 0.96, 0.65], "bbox": [0.82, 0.36, 0.96, 0.65], "description": "Lái xe ký xác nhận số lượng nhận lên xe", "desc": "Lái xe ký xác nhận số lượng nhận lên xe", "required": True, "target_source": "static_preset_legacy", "superseded_by": "stage3b_dynamic_zone", "use": "legacy_v1_benchmark_only"},
        {"role": "Người lập phiếu", "expected_color": "blue_ink", "box_norm": [0.82, 0.66, 0.96, 0.95], "bbox": [0.82, 0.66, 0.96, 0.95], "description": "Nhân viên điều phối / lập lệnh xuất ký tên", "desc": "Nhân viên điều phối / lập lệnh xuất ký tên", "required": False, "target_source": "static_preset_legacy", "superseded_by": "stage3b_dynamic_zone", "use": "legacy_v1_benchmark_only"}
    ],
    'PXKKVCNB': [
        {"role": "Người lập phiếu", "expected_color": "blue_ink", "box_norm": [0.80, 0.04, 0.95, 0.22], "bbox": [0.80, 0.04, 0.95, 0.22], "description": "Người lập phiếu xuất kho kiêm VC nội bộ", "desc": "Người lập phiếu xuất kho kiêm VC nội bộ", "required": False},
        {"role": "Người vận chuyển", "expected_color": "blue_ink", "box_norm": [0.80, 0.24, 0.95, 0.44], "bbox": [0.80, 0.24, 0.95, 0.44], "description": "Tài xế vận chuyển hàng trung chuyển", "desc": "Tài xế vận chuyển hàng trung chuyển", "required": True},
        {"role": "Thủ kho xuất", "expected_color": "blue_ink", "box_norm": [0.80, 0.45, 0.95, 0.65], "bbox": [0.80, 0.45, 0.95, 0.65], "description": "Thủ kho xuất hàng", "desc": "Thủ kho xuất hàng", "required": True},
        {"role": "Thủ kho nhập", "expected_color": "blue_ink", "box_norm": [0.80, 0.68, 0.95, 0.95], "bbox": [0.80, 0.68, 0.95, 0.95], "description": "Thủ kho nhập nhận hàng tại kho đích", "desc": "Thủ kho nhập nhận hàng tại kho đích", "required": True},
        {"role": "Mộc đỏ kho KIDO", "expected_color": "red_stamp", "box_norm": [0.74, 0.46, 0.92, 0.70], "bbox": [0.74, 0.46, 0.92, 0.70], "description": "Mộc đỏ xác thực xuất kho nội bộ", "desc": "Mộc đỏ xác thực xuất kho nội bộ", "required": True}
    ],
    'PHIEU_GIAO_HANG': [
        {"role": "Người giao hàng", "expected_color": "blue_ink", "box_norm": [0.78, 0.08, 0.95, 0.45], "bbox": [0.78, 0.08, 0.95, 0.45], "description": "Lái xe ký bàn giao", "desc": "Lái xe ký bàn giao", "required": True},
        {"role": "Người nhận hàng", "expected_color": "blue_ink", "box_norm": [0.78, 0.55, 0.95, 0.94], "bbox": [0.78, 0.55, 0.95, 0.94], "description": "Đại diện khách hàng / siêu thị nhận hàng", "desc": "Đại diện khách hàng / siêu thị nhận hàng", "required": True}
    ],
    'PHIEU_NHAP_KHO': [
        {"role": "Bên giao", "expected_color": "blue_ink", "box_norm": [0.78, 0.08, 0.95, 0.45], "bbox": [0.78, 0.08, 0.95, 0.45], "description": "Chữ ký bên giao góc dưới trái", "desc": "Chữ ký bên giao góc dưới trái", "required": True},
        {"role": "Bên nhận", "expected_color": "blue_ink", "box_norm": [0.78, 0.55, 0.95, 0.94], "bbox": [0.78, 0.55, 0.95, 0.94], "description": "Chữ ký bên nhận góc dưới phải", "desc": "Chữ ký bên nhận góc dưới phải", "required": True},
        {"role": "Con dấu mộc", "expected_color": "red_stamp", "box_norm": [0.70, 0.45, 0.92, 0.88], "bbox": [0.70, 0.45, 0.92, 0.88], "description": "Con dấu mộc đỏ cơ quan/đối tác", "desc": "Con dấu mộc đỏ cơ quan/đối tác", "required": True}
    ],
    'PHIEU_XUAT_HANG': [
        {"role": "Bên giao", "expected_color": "blue_ink", "box_norm": [0.78, 0.08, 0.95, 0.45], "bbox": [0.78, 0.08, 0.95, 0.45], "description": "Chữ ký bên giao góc dưới trái", "desc": "Chữ ký bên giao góc dưới trái", "required": True},
        {"role": "Bên nhận", "expected_color": "blue_ink", "box_norm": [0.78, 0.55, 0.95, 0.94], "bbox": [0.78, 0.55, 0.95, 0.94], "description": "Chữ ký bên nhận góc dưới phải", "desc": "Chữ ký bên nhận góc dưới phải", "required": True},
        {"role": "Con dấu mộc", "expected_color": "red_stamp", "box_norm": [0.70, 0.45, 0.92, 0.88], "bbox": [0.70, 0.45, 0.92, 0.88], "description": "Con dấu mộc đỏ cơ quan/đối tác", "desc": "Con dấu mộc đỏ cơ quan/đối tác", "required": True}
    ],
    'BBBG_HOADON': [
        {"role": "Người giao hóa đơn", "expected_color": "blue_ink", "box_norm": [0.75, 0.05, 0.98, 0.45], "bbox": [0.75, 0.05, 0.98, 0.45], "description": "Đại diện bên giao hóa đơn ký tên", "desc": "Đại diện bên giao hóa đơn ký tên", "required": True},
        {"role": "Người nhận hóa đơn", "expected_color": "blue_ink", "box_norm": [0.75, 0.55, 0.98, 0.95], "bbox": [0.75, 0.55, 0.98, 0.95], "description": "Đại diện NPP nhận hóa đơn ký tên", "desc": "Đại diện NPP nhận hóa đơn ký tên", "required": True}
    ],
    'BBBG_HANG_HOA': [
        {"role": "Đại diện bên giao", "expected_color": "blue_ink", "box_norm": [0.75, 0.05, 0.98, 0.35], "bbox": [0.75, 0.05, 0.98, 0.35], "description": "Bên giao hàng KIDO ký tên", "desc": "Bên giao hàng KIDO ký tên", "required": True},
        {"role": "Đại diện bên nhận", "expected_color": "blue_ink", "box_norm": [0.75, 0.65, 0.98, 0.95], "bbox": [0.75, 0.65, 0.98, 0.95], "description": "Bên nhận hàng ký tên", "desc": "Bên nhận hàng ký tên", "required": True},
        {"role": "Con dấu mộc", "expected_color": "red_stamp", "box_norm": [0.70, 0.55, 0.95, 0.95], "bbox": [0.70, 0.55, 0.95, 0.95], "description": "Con dấu mộc tiếp nhận / đối tác", "desc": "Con dấu mộc tiếp nhận / đối tác", "required": True}
    ],
    'BBBG_PALLET': [
        {"role": "Đại diện bên giao", "expected_color": "blue_ink", "box_norm": [0.76, 0.08, 0.95, 0.45], "bbox": [0.76, 0.08, 0.95, 0.45], "description": "Bên giao pallet (KIDO) ký tên", "desc": "Bên giao pallet (KIDO) ký tên", "required": True},
        {"role": "Đại diện bên nhận", "expected_color": "blue_ink", "box_norm": [0.76, 0.55, 0.95, 0.94], "bbox": [0.76, 0.55, 0.95, 0.94], "description": "Bên nhận pallet ký tên & đóng dấu", "desc": "Bên nhận pallet ký tên & đóng dấu", "required": True}
    ],
    'BB_THU_HOI': [
        {"role": "Bên giao", "expected_color": "blue_ink", "box_norm": [0.78, 0.08, 0.95, 0.45], "bbox": [0.78, 0.08, 0.95, 0.45], "description": "Chữ ký bên giao góc dưới trái", "desc": "Chữ ký bên giao góc dưới trái", "required": True},
        {"role": "Bên nhận", "expected_color": "blue_ink", "box_norm": [0.78, 0.55, 0.95, 0.94], "bbox": [0.78, 0.55, 0.95, 0.94], "description": "Chữ ký bên nhận góc dưới phải", "desc": "Chữ ký bên nhận góc dưới phải", "required": True},
        {"role": "Con dấu mộc", "expected_color": "red_stamp", "box_norm": [0.70, 0.45, 0.92, 0.88], "bbox": [0.70, 0.45, 0.92, 0.88], "description": "Con dấu mộc đỏ cơ quan/đối tác", "desc": "Con dấu mộc đỏ cơ quan/đối tác", "required": True}
    ],
    'BB_NO_HANG': [
        {"role": "Bên giao", "expected_color": "blue_ink", "box_norm": [0.78, 0.08, 0.95, 0.45], "bbox": [0.78, 0.08, 0.95, 0.45], "description": "Chữ ký bên giao góc dưới trái", "desc": "Chữ ký bên giao góc dưới trái", "required": True},
        {"role": "Bên nhận", "expected_color": "blue_ink", "box_norm": [0.78, 0.55, 0.95, 0.94], "bbox": [0.78, 0.55, 0.95, 0.94], "description": "Chữ ký bên nhận góc dưới phải", "desc": "Chữ ký bên nhận góc dưới phải", "required": True},
        {"role": "Con dấu mộc", "expected_color": "red_stamp", "box_norm": [0.70, 0.45, 0.92, 0.88], "bbox": [0.70, 0.45, 0.92, 0.88], "description": "Con dấu mộc đỏ cơ quan/đối tác", "desc": "Con dấu mộc đỏ cơ quan/đối tác", "required": True}
    ],
    'BB_TRA_HANG': [
        {"role": "Người trả hàng", "expected_color": "blue_ink", "box_norm": [0.80, 0.50, 0.98, 0.95], "bbox": [0.80, 0.50, 0.98, 0.95], "description": "Xác nhận trả hàng ký tên", "desc": "Xác nhận trả hàng ký tên", "required": True},
        {"role": "Con dấu mộc", "expected_color": "red_stamp", "box_norm": [0.70, 0.45, 0.92, 0.88], "bbox": [0.70, 0.45, 0.92, 0.88], "description": "Con dấu mộc xác nhận trả hàng", "desc": "Con dấu mộc xác nhận trả hàng", "required": True}
    ],
    'LENH_DIEU_XE': [
        {"role": "Điều độ cấp lệnh", "expected_color": "blue_ink", "box_norm": [0.80, 0.10, 0.98, 0.45], "bbox": [0.80, 0.10, 0.98, 0.45], "description": "Bộ phận điều phối cấp lệnh", "desc": "Bộ phận điều phối cấp lệnh", "required": True},
        {"role": "Lái xe nhận lệnh", "expected_color": "blue_ink", "box_norm": [0.80, 0.55, 0.98, 0.90], "bbox": [0.80, 0.55, 0.98, 0.90], "description": "Lái xe ký nhận lệnh", "desc": "Lái xe ký nhận lệnh", "required": True}
    ]
}

# Siêu dữ liệu cấp preset (ghi vào manifest metadata). Chỉ doc_type có mâu thuẫn nguồn sự thật.
SIGNATURE_PRESET_METADATA = {
    "LOADING_PLAN": {
        "target_source": "static_preset_legacy",
        "superseded_by": "stage3b_dynamic_zone",
        "use": "legacy_v1_benchmark_only",
        "n_roles_static": 3,
        "dynamic_zone_roles_config": "config/stage3b_loading_plan_labels.json",
        "note": ("Preset tĩnh 3 vai trò giữ nguyên hộp/target_id cho GT v1 (stage4_gt_independent_v2.json) và "
                 "test_stage4_suite. Production LOADING_PLAN dùng zone động Tầng 3b (5 vai trò) — "
                 "tools/kido_pipeline.py nhánh doc_type == 'LOADING_PLAN' đứng TRƯỚC nhánh signature_catalog."),
    }
}


def map_signature_presets(documents: List[DocumentItem]) -> Tuple[int, int]:
    """Gán tọa độ vùng chữ ký theo 14 preset chuẩn hóa. Gán UNMAPPED minh bạch nếu không có preset."""
    mapped_count = 0
    unmapped_count = 0

    for doc in documents:
        if doc.doc_type in SIGNATURE_PRESET_MAP:
            doc.signature_targets = SIGNATURE_PRESET_MAP[doc.doc_type]
            doc.target_mapping_status = "MAPPED"
            doc.preset_source = "SIGNATURE_PRESET_MAP"
            doc.preset_version = "v1"
            mapped_count += 1
        else:
            doc.signature_targets = []
            doc.target_mapping_status = "UNMAPPED"
            doc.preset_source = None
            doc.preset_version = None
            unmapped_count += 1

    return mapped_count, unmapped_count

# --- 7. BENCHMARK & EVALUATION SUITE (P1) ---

def evaluate_multipage_gt(multipage_summary: List[Tuple[str, List[str], str]], gt_data: Dict[str, Any]) -> Dict[str, Any]:
    """Đánh giá độ chính xác ghép nối đa trang so với Ground Truth độc lập."""
    gt_multipage = gt_data.get('multipage_gt', [])
    pred_pairs = set((p, tuple(sorted(c))) for p, c, t in multipage_summary)
    gt_pairs = set((g['parent_file'], tuple(sorted(g['continuation_files']))) for g in gt_multipage)

    correct = len(pred_pairs.intersection(gt_pairs))
    prec = correct / len(pred_pairs) if pred_pairs else 0.0
    rec = correct / len(gt_pairs) if gt_pairs else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    return {
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "correct": correct,
        "total_pred": len(pred_pairs),
        "total_gt": len(gt_pairs)
    }

def evaluate_shipment_batches_gt(batches: List[ShipmentBatch], gt_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Đánh giá độ chính xác phân cụm Lô Chuyến Xe (Pairwise Batch Clustering).
    Bao gồm phân tích chi tiết FP/FN với minh chứng thực tế: expected_identity_evidence, observed_identity_evidence.
    """
    gt_batches = gt_data.get('shipment_batches_gt', {})
    doc_to_gt = {}
    for b_id, b_info in gt_batches.items():
        for fn in b_info.get('doc_files', []):
            doc_to_gt[fn] = b_id

    doc_to_pred = {}
    doc_to_assign = {}
    doc_to_type = {}
    for b in batches:
        for d in b.documents:
            for p in d.page_files:
                fn = p.split('/')[-1].split('\\')[-1]
                doc_to_pred[fn] = b.batch_id
                doc_to_assign[fn] = getattr(d, 'batch_assignment', {}) or {}
                doc_to_type[fn] = d.doc_type

    common_files = sorted(list(set(doc_to_gt.keys()).intersection(set(doc_to_pred.keys()))))
    tp, fp, fn = 0, 0, 0
    fp_details = []
    fn_details = []

    for i in range(len(common_files)):
        for j in range(i + 1, len(common_files)):
            f1, f2 = common_files[i], common_files[j]
            same_gt = (doc_to_gt[f1] == doc_to_gt[f2])
            p1 = doc_to_pred.get(f1, '')
            p2 = doc_to_pred.get(f2, '')
            same_pred = (p1 == p2) and not p1.startswith('UNRESOLVED')

            if same_gt and same_pred:
                tp += 1
            elif not same_gt and same_pred:
                fp += 1
                fp_details.append({
                    "source": f1,
                    "target": f2,
                    "predicted": p1,
                    "expected_source": doc_to_gt[f1],
                    "expected_target": doc_to_gt[f2],
                    "reason": "Khác lô GT nhưng bị gom nhầm do chung mã hoặc quy tắc exception",
                    "observed_identity_evidence": f"Batch: {p1}"
                })
            elif same_gt and not same_pred:
                fn += 1
                is_unres = p1.startswith('UNRESOLVED') or p2.startswith('UNRESOLVED')
                is_conflict = 'COMMON' in p1 or 'COMMON' in p2
                if is_unres:
                    reason = "Thiếu trường khóa OCR (45-150 DPI) nên cách ly an toàn thành UNRESOLVED"
                elif is_conflict:
                    reason = "Xung đột danh tính / mã chuyến (Conflict Guard bảo vệ an toàn, ngăn chặn gộp sai)"
                else:
                    reason = "Chưa đủ bằng chứng liên kết cấp chuyến xe"
                # Lý do cách ly THẬT lấy từ batch_assignment của chứng từ bị UNRESOLVED
                # (câu "Thiếu trường khóa OCR" ở trên là nhãn nhóm chung, không đủ cụ thể).
                iso = []
                for f_, p_ in ((f1, p1), (f2, p2)):
                    if p_.startswith('UNRESOLVED'):
                        ba = doc_to_assign.get(f_, {})
                        iso.append({"file": f_, "doc_type": doc_to_type.get(f_),
                                    "isolation_reason": ba.get("isolation_reason"),
                                    "candidate_batches": ba.get("candidate_batches")})
                fn_details.append({
                    "source": f1,
                    "target": f2,
                    "predicted_source": p1,
                    "predicted_target": p2,
                    "expected_batch": doc_to_gt[f1],
                    "reason": reason,
                    "isolation": iso,
                    "expected_identity_evidence": f"GT: {doc_to_gt[f1]}",
                    "observed_identity_evidence": f"{p1} vs {p2}"
                })

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    return {
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "total_evaluated_files": len(common_files),
        "fp_details": fp_details,
        "fn_details": fn_details
    }

def evaluate_order_dossiers_gt(batches: List[ShipmentBatch], gt_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Đánh giá độ chính xác gom Hồ Sơ Đơn Hàng (OrderDossier Benchmark).
    Hai chứng từ cùng chia sẻ po_no, invoice_no hoặc pxk_no trong cùng lô phải thuộc cùng một OrderDossier.
    """
    doc_to_dossier = {}
    for b in batches:
        for doss in b.order_dossiers:
            for d in doss.documents:
                for p in d.page_files:
                    fn = p.split('/')[-1].split('\\')[-1]
                    doc_to_dossier[fn] = doss.dossier_id

    gt_dossiers = gt_data.get('order_dossiers_gt', {})
    if not gt_dossiers:
        # KHÔNG trả 1.0 khi không có Ground Truth: đó là PASS GIẢ.
        # Trả trạng thái SKIPPED tường minh, P/R/F1 = None để caller bắt buộc xử lý.
        total_dossiers = sum(len(b.order_dossiers) for b in batches)
        return {
            "total_dossiers": total_dossiers,
            "skipped": True,
            "status": "SKIPPED_NO_GT",
            "reason": "gt_data thiếu khóa 'order_dossiers_gt' -> không thể đánh giá, không được coi là PASS.",
            "precision": None,
            "recall": None,
            "f1": None,
            "tp": 0, "fp": 0, "fn": 0
        }

    doc_to_gt_doss = {}
    for did, dinfo in gt_dossiers.items():
        for fn in dinfo.get('doc_files', []):
            doc_to_gt_doss[fn] = did

    common_files = sorted(list(set(doc_to_gt_doss.keys()).intersection(set(doc_to_dossier.keys()))))
    tp, fp, fn = 0, 0, 0
    for i in range(len(common_files)):
        for j in range(i + 1, len(common_files)):
            f1, f2 = common_files[i], common_files[j]
            same_gt = (doc_to_gt_doss[f1] == doc_to_gt_doss[f2])
            same_pred = (doc_to_dossier.get(f1) == doc_to_dossier.get(f2))
            if same_gt and same_pred: tp += 1
            elif not same_gt and same_pred: fp += 1
            elif same_gt and not same_pred: fn += 1

    if (tp + fp + fn) == 0:
        # Không có cặp nào so khớp được giữa GT và dự đoán -> không có gì để đánh giá.
        return {
            "skipped": True,
            "status": "SKIPPED_NO_COMPARABLE_PAIRS",
            "reason": f"Chỉ có {len(common_files)} file chung giữa GT và dự đoán, không sinh được cặp nào.",
            "precision": None, "recall": None, "f1": None,
            "tp": 0, "fp": 0, "fn": 0,
            "common_files": len(common_files)
        }

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {
        "skipped": False,
        "status": "EVALUATED",
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "common_files": len(common_files)
    }

def evaluate_reconciliation_gt(batches: List[ShipmentBatch], gt_data: Dict[str, Any]) -> Dict[str, Any]:
    """Đánh giá độ chính xác đối soát chéo trường dữ liệu so với Ground Truth."""
    gt_reconcil = gt_data.get('reconciliation_gt', [])
    if not gt_reconcil:
        # KHÔNG trả 1.0 khi không có Ground Truth: đó là PASS GIẢ.
        return {
            "skipped": True,
            "status": "SKIPPED_NO_GT",
            "reason": "gt_data thiếu khóa 'reconciliation_gt' -> không thể đánh giá.",
            "accuracy": None, "correct": 0, "total": 0, "details": []
        }

    all_reconcil = []
    doc_type_map = {}
    for b in batches:
        for d in b.documents:
            doc_type_map[d.doc_id] = d.doc_type
        for doss in b.order_dossiers:
            all_reconcil.extend(doss.reconciliation)

    correct = 0
    total = len(gt_reconcil)
    details = []

    for rule in gt_reconcil:
        field = rule['field']
        expected_status = rule['expected_status']
        dossier_key = rule.get('dossier_key', '')
        tgt_type = rule.get('target_doc_type')
        src_type = rule.get('source_doc_type')
        found = False
        for r in all_reconcil:
            s_val = str(r.source_val or "")
            t_val = str(r.target_val or "")
            s_doc = str(r.source_doc or "")
            t_doc = str(r.target_doc or "")
            s_type = doc_type_map.get(r.source_doc)
            t_type = doc_type_map.get(r.target_doc)

            if r.field == field and (dossier_key in s_val or dossier_key in t_val or dossier_key in s_doc or dossier_key in t_doc):
                if tgt_type and t_type and t_type != tgt_type and s_type != tgt_type:
                    continue
                if src_type and s_type and s_type != src_type and t_type != src_type:
                    continue
                found = True
                is_correct = (r.status == expected_status)
                if is_correct:
                    correct += 1
                details.append({
                    "rule": rule.get('rule_name', field),
                    "expected": expected_status,
                    "actual": r.status,
                    "is_correct": is_correct
                })
                break
        if not found:
            # KHÔNG suy diễn "không tìm thấy evidence == đúng kỳ vọng MISSING_*".
            # Một rule chỉ được tính ĐÚNG khi thực sự tìm được một evidence khớp kỳ vọng.
            # Không có evidence nào => hệ thống KHÔNG hề đối soát trường đó => SAI.
            details.append({
                "rule": rule.get('rule_name', field),
                "expected": expected_status,
                "actual": "NOT_FOUND",
                "is_correct": False,
                "note": "Không sinh được bản ghi ReconciliationEvidence nào khớp rule này."
            })

    not_found = sum(1 for d in details if d['actual'] == 'NOT_FOUND')
    acc = correct / total if total > 0 else None
    return {
        "skipped": False,
        "status": "EVALUATED",
        "accuracy": acc,
        "correct": correct,
        "total": total,
        "not_found": not_found,
        "details": details
    }


# --- 8. PIPELINE CHÍNH THỨC & XUẤT MANIFEST BÀN GIAO TẦNG 4 ---
#
# NGUỒN SINH MANIFEST CHÍNH THỨC (27/09):
#     .venv/Scripts/python.exe tools/stage3_resolver.py
# -> ghi output/stage3_out/stage3_batched_manifest.json (hoặc --out PATH).
# Trước đây manifest chỉ được sinh NGẦM như tác dụng phụ của tools/test_stage3_suite.py:
# chạy test là ghi đè artifact bàn giao Tầng 4, không snapshot. Nay test chỉ ghi khi có
# cờ tường minh --write-manifest, và cả hai đường dùng CHUNG hàm dưới đây nên nội dung
# giống hệt nhau.

DEFAULT_STAGE2_JSON_PATH = "output/stage2_out/stage2_classified_results.json"
DEFAULT_CATALOG_JSON_PATH = "output/form_catalog.json"
DEFAULT_CONFIG_PATH = "config/stage3_business_rules.json"
DEFAULT_REFERENCE_PATH = "config/stage3_shipment_reference.json"

# Khóa dữ liệu tham chiếu (mã chuyến / lệnh điều động / hóa đơn CỤ THỂ) — tiền lệ AGENTS.md 9.2.
REFERENCE_KEYS = ("business_exceptions", "shipment_aliases")


def load_shipment_reference(reference_path: Optional[str] = DEFAULT_REFERENCE_PATH) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Nạp dữ liệu tham chiếu định danh lô. Thiếu file (hoặc reference_path=None) -> KHÔNG lỗi:
    chạy không hiệu chỉnh, cảnh báo tường minh, info.reference_loaded = False.
    File có nhưng hỏng -> lỗi (không nuốt lỗi)."""
    info: Dict[str, Any] = {"reference_loaded": False, "reference_path": reference_path,
                            "reference_status": None, "reference_version": None,
                            "n_business_exceptions": 0, "n_shipment_aliases": 0}
    if not reference_path or not Path(reference_path).exists():
        info["reference_status"] = "DISABLED" if not reference_path else "FILE_NOT_FOUND"
        msg = (f"[CẢNH BÁO Tầng 3] Không nạp dữ liệu tham chiếu lô chuyến ({reference_path or 'tắt tường minh'}): "
               "chạy KHÔNG hiệu chỉnh — business_exceptions/shipment_aliases rỗng, các luật trỏ exception_rule_id "
               "không kích hoạt. Chỉ số phản ánh năng lực thật khi không có danh mục ERP.")
        print(msg, file=sys.stderr)
        import warnings
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return None, info
    with open(reference_path, "r", encoding="utf-8") as f:
        ref = json.load(f)
    for k in REFERENCE_KEYS:
        if not isinstance(ref.get(k, []), list):
            raise ValueError(f"{reference_path}: khóa '{k}' phải là list")
    info.update({"reference_loaded": True, "reference_status": ref.get("_status"),
                 "reference_version": ref.get("version"),
                 "n_business_exceptions": len(ref.get("business_exceptions", [])),
                 "n_shipment_aliases": len(ref.get("shipment_aliases", []))})
    return ref, info


def apply_shipment_reference(business_config: Dict[str, Any], reference: Optional[Dict[str, Any]],
                             info: Dict[str, Any]) -> Dict[str, Any]:
    """Trả bản sao config đã gộp dữ liệu tham chiếu (config luật + reference). Ghi info vào
    khóa '_reference' để manifest truy được chế độ chạy."""
    cfg = copy.deepcopy(business_config)
    for k in REFERENCE_KEYS:
        legacy = list(cfg.get(k, []) or [])
        if legacy:
            # Dữ liệu tham chiếu lẽ ra không còn trong file luật — báo tường minh, không nuốt.
            print(f"[CẢNH BÁO Tầng 3] config luật còn {len(legacy)} mục '{k}' (dữ liệu tham chiếu nên ở "
                  f"{DEFAULT_REFERENCE_PATH}).", file=sys.stderr)
        cfg[k] = legacy + list((reference or {}).get(k, []) or [])
    cfg["_reference"] = dict(info)
    return cfg
OFFICIAL_MANIFEST_PATH = "output/stage3_out/stage3_batched_manifest.json"
MANIFEST_VERSION = "3.3.0"


def run_stage3_pipeline(stage2_records: List[Dict[str, Any]], business_config: Dict[str, Any],
                        form_catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Chạy toàn bộ Tầng 3 trên bản ghi Tầng 2. `scan_index` = thứ tự trong danh sách."""
    for i, r in enumerate(stage2_records):
        r['scan_index'] = i
    docs, multipage_summary = resolve_multipage_documents(stage2_records)
    batches = resolve_shipment_batches(docs, business_config)
    total_dossiers = 0
    for b in batches:
        b.order_dossiers = build_order_dossiers_for_batch(b)
        for dos in b.order_dossiers:
            reconcile_order_dossier_fields(dos, b)
        total_dossiers += len(b.order_dossiers)
    mapped_count, unmapped_count = map_signature_presets(docs)
    checklist_guidelines = build_checklist_guidelines(form_catalog, business_config)
    for b in batches:
        audit_checklist_compliance(b, checklist_guidelines)
    return {
        "stage2_records": stage2_records,
        "docs": docs,
        "multipage_summary": multipage_summary,
        "batches": batches,
        "total_dossiers": total_dossiers,
        "mapped_count": mapped_count,
        "unmapped_count": unmapped_count,
        "checklist_guidelines": checklist_guidelines,
        "reference_info": business_config.get("_reference",
                                              {"reference_loaded": False, "reference_status": "NOT_APPLIED"}),
    }


def build_manifest_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Dựng nội dung manifest bàn giao Tầng 4 (không có timestamp -> tái lập byte-by-byte)."""
    batches = result["batches"]
    return {
        "metadata": {
            "version": MANIFEST_VERSION,
            "source_stage2_records": len(result["stage2_records"]),
            "total_documents": len(result["docs"]),
            "total_batches": len(batches),
            "total_order_dossiers": result["total_dossiers"],
            "multipage_groups_count": len(result["multipage_summary"]),
            "mapped_signatures_count": result["mapped_count"],
            "unmapped_signatures_count": result["unmapped_count"],
            "checklist_audited_batches": sum(1 for b in batches if b.checklist_audit),
            "reference_loaded": bool(result.get("reference_info", {}).get("reference_loaded", False)),
            "reference": result.get("reference_info", {"reference_loaded": False,
                                                      "reference_status": "NOT_APPLIED"}),
            "signature_preset_notes": SIGNATURE_PRESET_METADATA,
            "generator": "tools/stage3_resolver.py"
        },
        "batches": [b.to_dict() for b in batches]
    }


def serialize_manifest(manifest_data: Dict[str, Any]) -> str:
    return json.dumps(manifest_data, ensure_ascii=False, indent=2)


def write_manifest(manifest_data: Dict[str, Any], path: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(serialize_manifest(manifest_data))
    return p


def load_stage3_inputs(stage2_path: str = DEFAULT_STAGE2_JSON_PATH,
                       config_path: str = DEFAULT_CONFIG_PATH,
                       catalog_path: str = DEFAULT_CATALOG_JSON_PATH,
                       reference_path: Optional[str] = DEFAULT_REFERENCE_PATH):
    """reference_path=None -> chạy tường minh KHÔNG dữ liệu tham chiếu."""
    with open(stage2_path, "r", encoding="utf-8") as f:
        stage2_records = json.load(f)
    with open(config_path, "r", encoding="utf-8") as f:
        business_config = json.load(f)
    ref, ref_info = load_shipment_reference(reference_path)
    business_config = apply_shipment_reference(business_config, ref, ref_info)
    with open(catalog_path, "r", encoding="utf-8") as f:
        form_catalog = json.load(f)
    return stage2_records, business_config, form_catalog


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Tầng 3: sinh manifest chính thức bàn giao Tầng 4.")
    ap.add_argument("--stage2", default=DEFAULT_STAGE2_JSON_PATH)
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG_JSON_PATH)
    ap.add_argument("--reference", default=DEFAULT_REFERENCE_PATH,
                    help=f"Dữ liệu tham chiếu lô chuyến (mặc định {DEFAULT_REFERENCE_PATH}; thiếu file -> không hiệu chỉnh)")
    ap.add_argument("--no-reference", action="store_true",
                    help="Chạy tường minh KHÔNG dữ liệu tham chiếu (năng lực thật)")
    ap.add_argument("--out", default=OFFICIAL_MANIFEST_PATH,
                    help=f"Đường dẫn ghi manifest (mặc định: {OFFICIAL_MANIFEST_PATH})")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    recs, cfg, cat = load_stage3_inputs(args.stage2, args.config, args.catalog,
                                        None if args.no_reference else args.reference)
    result = run_stage3_pipeline(recs, cfg, cat)
    data = build_manifest_data(result)
    p = write_manifest(data, args.out)
    md = data["metadata"]
    print(f"[OK] Manifest Tầng 3 -> {p} ({p.stat().st_size / 1024:.1f} KB) | "
          f"{md['total_documents']} docs, {md['total_batches']} batches, "
          f"{md['total_order_dossiers']} dossiers | reference_loaded={md['reference_loaded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
