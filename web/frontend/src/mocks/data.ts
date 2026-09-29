// DỮ LIỆU GIẢ — chỉ nạp khi VITE_MOCK=1 (xem main.tsx). Không lọt vào bản build thường.
// Trang LOADING_PLAN mẫu: Load3.3__0.png — 5 ô ký lấy nguyên box_norm / detected / evidence / reason / required
// từ output/stage4_out/stage4_verification_manifest_v2.json (27/09). Ảnh: output/stage1_out/images/form_samples/
// (chuyển sang JPG để nhẹ).

import lpImg from './assets/mock_lp_page.jpg';
import page1Img from './assets/mock_page1.jpg';
import type {
  AdminUserOut,
  AuditLog,
  Dossier,
  PageDetail,
  StatusTone,
  TargetOut,
} from '../api/types';

export const MOCK_IMAGES = { lp: lpImg, page1: page1Img };

export interface MockUser extends AdminUserOut {
  password: string;
}

const now = Date.now();
const iso = (msAgo: number) => new Date(now - msAgo).toISOString();

export const users: MockUser[] = [
  {
    id: 1,
    email: 'admin@kido.local',
    password: 'Admin@123',
    full_name: 'Quản trị KIDO',
    role: 'admin',
    is_active: true,
    email_verified: true,
    created_at: iso(86400e3 * 3),
    last_login_at: iso(3600e3),
  },
  {
    id: 2,
    email: 'nv@kido.local',
    password: 'Kido@1234',
    full_name: 'Nguyễn Văn Kho',
    role: 'user',
    is_active: true,
    email_verified: true,
    created_at: iso(86400e3 * 2),
    last_login_at: iso(7200e3),
  },
  {
    id: 3,
    email: 'moi@kido.local',
    password: 'Kido@1234',
    full_name: 'Trần Thị Mới',
    role: 'user',
    is_active: true,
    email_verified: false,
    created_at: iso(86400e3),
    last_login_at: null,
  },
];

/** Mô phỏng app/labels.py (backend quyết định thật). */
export const LABELS: Record<string, { label: string; tone: StatusTone }> = {
  DAT_CHUAN_GOC: { label: 'Đạt chuẩn (bản gốc)', tone: 'success' },
  DAT_CHUAN_PHOTO: { label: 'Đạt chuẩn (bản photo)', tone: 'success' },
  THIEU_MOT_SO_CHU_KY: { label: 'Thiếu chữ ký bắt buộc', tone: 'danger' },
  CHUA_KY_DONG_DAU: { label: 'Chưa ký / đóng dấu', tone: 'danger' },
  CAN_KIEM_TRA_TAY: { label: 'Cần kiểm tra tay', tone: 'warning' },
  TRANG_1_CHUA_KY: { label: 'Trang 1 — khối ký ở trang sau', tone: 'info' },
  KHONG_TIM_THAY_KHOI_KY: { label: 'Không tìm thấy khối ký trong hồ sơ', tone: 'warning' },
  CHUA_CHUAN_HOA_VUNG_KY: { label: 'Không xác định được vùng ký', tone: 'neutral' },
  KHONG_YEU_CAU: { label: 'Không yêu cầu ký theo SOP', tone: 'info' },
  UNMAPPED: { label: 'Chưa hỗ trợ kiểm chữ ký', tone: 'neutral' },
};

const MT_REQ = 'POLICY:MT:REQUIRED[Guideline!H15,Guideline!H19,Guideline!H23]';

function t(
  index: number,
  role: string,
  required: boolean,
  required_source: string,
  box_norm: [number, number, number, number],
  detected: boolean,
  confidence: number,
  evidence: string,
  reason: string,
  extra?: { muc_so_huu_mm2?: number; so_cum?: number; policy_channel?: string },
): TargetOut {
  return {
    index,
    role,
    required,
    required_source,
    policy_channel: extra?.policy_channel ?? 'MT',
    box_norm,
    detected,
    confidence,
    evidence,
    reason,
    review_required: false,
    latest_review: null,
    effective_detected: detected,
    ...(extra?.muc_so_huu_mm2 === undefined ? {} : { muc_so_huu_mm2: extra.muc_so_huu_mm2 }),
    ...(extra?.so_cum === undefined ? {} : { so_cum: extra.so_cum }),
  };
}

export const LP_TARGETS: TargetOut[] = [
  t(0, 'Người lập phiếu', false, 'POLICY:ALWAYS_OPTIONAL(NGUOI_LAP_PHIEU)', [0.519, 0.067, 0.72, 0.237], true, 0.731,
    'BLUE_SIGNATURE_DETECTED', 'Chữ ký mực xanh trong ô (2.6 mm² >= 2.0 mm², 4 cụm; bỏ 0.0 mm² ở dải biên)'),
  t(1, 'Trưởng BP Kho / Nhóm trưởng', false, 'POLICY:ALWAYS_OPTIONAL(TRUONG_BP_KHO)', [0.519, 0.237, 0.709, 0.408], false, 0,
    'NO_SIGNATURE_DETECTED', 'Không có mực xanh của ô (0.0 mm²) và không có nét tay tối'),
  t(2, 'Tài xế (Lái xe nhận hàng)', true, MT_REQ, [0.519, 0.408, 0.709, 0.579], true, 1,
    'BLUE_SIGNATURE_DETECTED', 'Chữ ký mực xanh trong ô (33.4 mm² >= 2.0 mm², 7 cụm; bỏ 4.2 mm² ở dải biên)'),
  t(3, 'Người nhận hàng', false, 'POLICY:MT:NOT_REQUIRED[Guideline!H15,Guideline!H19,Guideline!H23]', [0.519, 0.579, 0.709, 0.75], false, 0,
    'BLUE_INK_ONLY_AT_COLUMN_EDGE', 'Chỉ có mực xanh ở dải biên ô (14.3 mm²) — coi là tràn từ cột bên'),
  t(4, 'Người giao / Thủ kho xuất', true, MT_REQ, [0.519, 0.75, 0.709, 0.927], true, 1,
    'BLUE_SIGNATURE_DETECTED', 'Chữ ký mực xanh trong ô (68.1 mm² >= 2.0 mm², 5 cụm; bỏ 8.3 mm² ở dải biên)'),
];

const EVIDENCE_VI: Record<string, string> = {
  BLUE_SIGNATURE_DETECTED: 'Có nét chữ ký mực xanh trong ô',
  NO_SIGNATURE_DETECTED: 'Không thấy nét ký',
  BLUE_INK_ONLY_AT_COLUMN_EDGE: 'Chỉ có mực ở mép ô (tràn từ cột bên)',
  BLUE_SIGNATURE_OWNED: 'Có nét ký mực xanh THUỘC ô (đã trừ mực tràn)',
  NO_OWNED_INK: 'Không có mực nào thuộc ô',
};
function labelEvidence(list: TargetOut[]) {
  for (const x of list) x.evidence_label_vi = x.evidence ? EVIDENCE_VI[x.evidence] ?? null : null;
}
labelEvidence(LP_TARGETS);

const S1_OK = {
  status: 'CANH_BAO',
  status_label_vi: 'Ảnh có cảnh báo chất lượng',
  action: 'CHUYEN_TANG_2',
  warns: ['Ảnh scan: không tách được biên tờ giấy, sẽ cắt viền trắng theo nội dung'],
  rejects: [],
  source_type: 'scan',
  low_resolution: false,
  effective_dpi: null,
};

const REQ_POLICY_MT = {
  policy_channel: 'MT',
  policy_channel_unresolved: false,
  policy_channel_reason: 'PREFIX(MT_)',
  required_roles: ['Tài xế (Lái xe nhận hàng)', 'Người giao / Thủ kho xuất'],
  policy_version: '1.0.0',
};

export interface MockPage extends PageDetail {
  group_id: number;
  stored_filename: string;
  image_stage1: string;
  image_original: string;
}

export function makeLpPage(id: number, groupId: number, scanIndex: number, original: string): MockPage {
  return {
    id,
    group_id: groupId,
    scan_index: scanIndex,
    original_filename: original,
    stored_filename: `${String(scanIndex).padStart(3, '0')}_1a2b3c${String(id % 100).padStart(2, '0')}.jpg`,
    width: 1555,
    height: 2200,
    s1_status: 'CANH_BAO',
    s1_status_label_vi: 'Ảnh có cảnh báo chất lượng',
    s1_status_tone: 'warning',
    machine_status_label_vi: LABELS.DAT_CHUAN_GOC?.label ?? null,
    machine_status_tone: LABELS.DAT_CHUAN_GOC?.tone ?? null,
    status_unknown: false,
    effective_action: 'DUYET',
    doc_type: 'LOADING_PLAN',
    doc_type_vi: 'Loading Plan (bảng kê xếp hàng)',
    system: 'MT_BIGC',
    page_role: 'HEADER',
    batch_id: 'BATCH_UPLOAD_001',
    s4_doc_status: 'DAT_CHUAN_GOC',
    s4_action: 'DUYET',
    status_label_vi: LABELS.DAT_CHUAN_GOC?.label ?? null,
    status_tone: 'success',
    supported: true,
    reviewed: false,
    effective_doc_status: 'DAT_CHUAN_GOC',
    s1: { ...S1_OK },
    s2: {
      doc_type: 'LOADING_PLAN',
      system: 'MT_BIGC',
      page_role: 'HEADER',
      confidence: 1,
      status: 'DAT',
      key_fields: { shipment_id: null, invoice_no: null, po_no: null, transfer_order_no: null, pxk_no: null },
      evidence: null,
    },
    s4: {
      zone_status: 'TABLE_BOTTOM_DETECTED',
      zone_description: 'Dò đáy bảng tại Y=0.53; cột đo từ 5/5 nhãn OCR',
      modality: 'TRUE_COLOR',
      zone_status_label_vi: 'Dò được khối ký dưới đáy bảng',
      doc_status: 'DAT_CHUAN_GOC',
      doc_status_label_vi: LABELS.DAT_CHUAN_GOC?.label ?? null,
      action: 'DUYET',
      action_label_vi: 'Duyệt',
      reason: 'Đạt chuẩn tất cả 2 chữ ký/mộc bắt buộc',
      required_policy: { ...REQ_POLICY_MT, policy_system: 'MT_BIGC' },
      a4_size: [1555, 2200],
      targets: LP_TARGETS.map((x) => ({ ...x })),
    },
    effective: {
      doc_status: 'DAT_CHUAN_GOC',
      action: 'DUYET',
      action_label_vi: 'Duyệt',
      reason: 'Đạt chuẩn tất cả 2 chữ ký/mộc bắt buộc',
      n_overridden: 0,
      n_reviewed: 0,
      source: 'MACHINE',
      label_vi: LABELS.DAT_CHUAN_GOC?.label ?? null,
      tone: LABELS.DAT_CHUAN_GOC?.tone ?? null,
    },
    image_stage1: lpImg,
    image_original: lpImg,
  };
}

export function makeTrang1Page(id: number, groupId: number, scanIndex: number, original: string): MockPage {
  return {
    id,
    group_id: groupId,
    scan_index: scanIndex,
    original_filename: original,
    stored_filename: `${String(scanIndex).padStart(3, '0')}_9f8e7d${String(id % 100).padStart(2, '0')}.jpg`,
    width: 1552,
    height: 2200,
    s1_status: 'CANH_BAO',
    s1_status_label_vi: 'Ảnh có cảnh báo chất lượng',
    s1_status_tone: 'warning',
    machine_status_label_vi: LABELS.TRANG_1_CHUA_KY?.label ?? null,
    machine_status_tone: LABELS.TRANG_1_CHUA_KY?.tone ?? null,
    status_unknown: false,
    effective_action: 'HOP_LE',
    doc_type: 'LOADING_PLAN',
    doc_type_vi: 'Loading Plan (bảng kê xếp hàng)',
    system: 'MT_BHX',
    page_role: 'HEADER',
    batch_id: 'BATCH_UPLOAD_001',
    s4_doc_status: 'TRANG_1_CHUA_KY',
    s4_action: 'HOP_LE',
    status_label_vi: LABELS.TRANG_1_CHUA_KY?.label ?? null,
    status_tone: 'info',
    supported: true,
    reviewed: false,
    effective_doc_status: 'TRANG_1_CHUA_KY',
    s1: { ...S1_OK },
    s2: {
      doc_type: 'LOADING_PLAN',
      system: 'MT_BHX',
      page_role: 'HEADER',
      confidence: 1,
      status: 'DAT',
      key_fields: { shipment_id: null, invoice_no: null, po_no: null, transfer_order_no: null, pxk_no: null },
      evidence: null,
    },
    s4: {
      zone_status: 'PAGE_1_NO_SIGNATURES',
      zone_description: 'Trang 1/2: Bảng hàng hóa dài phủ kín trang, khối ký nằm ở Trang 2',
      modality: 'N/A',
      zone_status_label_vi: 'Trang 1 — bảng phủ kín, khối ký ở trang sau',
      doc_status: 'TRANG_1_CHUA_KY',
      doc_status_label_vi: LABELS.TRANG_1_CHUA_KY?.label ?? null,
      action: 'HOP_LE',
      action_label_vi: 'Hợp lệ',
      reason: 'Trang 1/2: Bảng hàng hóa dài phủ kín trang, khối ký nằm ở Trang 2',
      required_policy: { ...REQ_POLICY_MT, policy_system: 'MT_BHX' },
      a4_size: [1552, 2200],
      targets: [],
    },
    effective: {
      doc_status: 'TRANG_1_CHUA_KY',
      action: 'HOP_LE',
      reason: 'Trang 1/2: Bảng hàng hóa dài phủ kín trang, khối ký nằm ở Trang 2',
      n_overridden: 0,
      n_reviewed: 0,
      source: 'MACHINE',
      label_vi: LABELS.TRANG_1_CHUA_KY?.label ?? null,
      tone: LABELS.TRANG_1_CHUA_KY?.tone ?? null,
    },
    image_stage1: page1Img,
    image_original: page1Img,
  };
}

export function makeOtherPage(id: number, groupId: number, scanIndex: number, original: string, img: string): MockPage {
  return {
    id,
    group_id: groupId,
    scan_index: scanIndex,
    original_filename: original,
    stored_filename: `${String(scanIndex).padStart(3, '0')}_5c4b3a${String(id % 100).padStart(2, '0')}.jpg`,
    width: 1552,
    height: 2200,
    s1_status: 'DAT',
    s1_status_label_vi: 'Ảnh dùng được',
    s1_status_tone: 'success',
    machine_status_label_vi: LABELS.UNMAPPED?.label ?? null,
    machine_status_tone: LABELS.UNMAPPED?.tone ?? null,
    status_unknown: false,
    effective_action: 'ABSTAIN',
    doc_type: 'PO',
    doc_type_vi: 'Đơn đặt hàng (PO)',
    system: 'MT_WINMART',
    page_role: 'HEADER',
    batch_id: 'UNRESOLVED_DOC_002',
    s4_doc_status: 'CHUA_CHUAN_HOA_VUNG_KY',
    s4_action: 'ABSTAIN',
    status_label_vi: LABELS.UNMAPPED?.label ?? null,
    status_tone: 'neutral',
    supported: false,
    reviewed: false,
    effective_doc_status: 'CHUA_CHUAN_HOA_VUNG_KY',
    s1: { status: 'DAT', action: 'CHUYEN_TANG_2', warns: [], rejects: [], source_type: 'photo', low_resolution: true, effective_dpi: 96 },
    s2: {
      doc_type: 'PO',
      system: 'MT_WINMART',
      page_role: 'HEADER',
      confidence: 1,
      status: 'DAT',
      key_fields: { shipment_id: null, invoice_no: null, po_no: '4173475639', transfer_order_no: null, pxk_no: null },
      evidence: null,
    },
    s4: {
      zone_status: 'OUT_OF_SCOPE',
      zone_description: null,
      modality: null,
      zone_status_label_vi: 'Ngoài phạm vi kiểm chữ ký',
      doc_status: 'CHUA_CHUAN_HOA_VUNG_KY',
      doc_status_label_vi: LABELS.UNMAPPED?.label ?? null,
      action: 'ABSTAIN',
      action_label_vi: 'Bỏ qua',
      reason: 'Loại chứng từ PO chưa có template vùng ký (chỉ LOADING_PLAN)',
      required_policy: null,
      a4_size: [1552, 2200],
      targets: [],
    },
    effective: {
      doc_status: 'CHUA_CHUAN_HOA_VUNG_KY',
      action: 'ABSTAIN',
      reason: 'Loại chứng từ PO chưa có template vùng ký (chỉ LOADING_PLAN)',
      n_overridden: 0,
      n_reviewed: 0,
      source: 'MACHINE',
      label_vi: LABELS.UNMAPPED?.label ?? null,
      tone: LABELS.UNMAPPED?.tone ?? null,
    },
    image_stage1: img,
    image_original: img,
  };
}

// --- Lệnh điều xe: 14 ô ký lấy từ TEMPLATE toạ độ cố định -------------------------------------------
// box_norm giữ đúng thứ tự backend đang dùng: [y0, x0, y1, x1] (xem tools/build_lp_dynamic_crops.py).
const LDX_ROLES: Array<[string, boolean]> = [
  ['Người lập lệnh', true],
  ['Trưởng bộ phận điều vận', true],
  ['Tài xế', true],
  ['Phụ xe 1', false],
  ['Phụ xe 2', false],
  ['Bảo vệ cổng (xuất)', true],
  ['Thủ kho xuất', true],
  ['Người nhận hàng điểm 1', true],
  ['Người nhận hàng điểm 2', false],
  ['Người nhận hàng điểm 3', false],
  ['Bảo vệ cổng (nhập)', false],
  ['Thủ kho nhập', true],
  ['Kế toán kho', false],
  ['Trưởng bộ phận kho', true],
];

const LDX_TEMPLATE_SRC = 'TEMPLATE:LENH_DIEU_XE:v1[toa_do_cung]';

export const LDX_TARGETS: TargetOut[] = LDX_ROLES.map(([role, required], i) => {
  const row = Math.floor(i / 7);
  const col = i % 7;
  const y0 = 0.615 + row * 0.185;
  const x0 = 0.045 + col * 0.129;
  const signed = i % 3 !== 1; // mô phỏng: 2/3 số ô có ký
  const mm2 = signed ? Number((6 + i * 2.7).toFixed(1)) : 0;
  const cum = signed ? 3 + (i % 5) : 0;
  return t(
    i,
    role,
    required,
    LDX_TEMPLATE_SRC,
    [y0, x0, y0 + 0.105, x0 + 0.118],
    signed,
    signed ? 0.86 : 0,
    signed ? 'BLUE_SIGNATURE_OWNED' : 'NO_OWNED_INK',
    signed ? `Mực xanh thuộc ô ${mm2} mm² (>= 2.0 mm²), ${cum} cụm` : 'Không có mực nào thuộc ô (0.0 mm²)',
    { muc_so_huu_mm2: mm2, so_cum: cum, policy_channel: 'GT' },
  );
});
labelEvidence(LDX_TARGETS);

/** Trang Lệnh điều xe — ô ký lấy từ template toạ độ cố định (zone_status TEMPLATE_TOA_DO_CUNG). */
export function makeLenhDieuXePage(id: number, groupId: number, scanIndex: number, original: string): MockPage {
  const req = LDX_TARGETS.filter((x) => x.required);
  const missing = req.filter((x) => !x.detected).length;
  const code = missing === 0 ? 'DAT_CHUAN_GOC' : 'THIEU_MOT_SO_CHU_KY';
  const reason = missing === 0 ? `Đạt chuẩn tất cả ${req.length} chữ ký bắt buộc` : `Thiếu ${missing}/${req.length} chữ ký bắt buộc`;
  const lab = LABELS[code];
  const act = code === 'DAT_CHUAN_GOC' ? 'DUYET' : 'CANH_BAO';
  const actVi = code === 'DAT_CHUAN_GOC' ? 'Duyệt' : 'Cảnh báo';
  return {
    id,
    group_id: groupId,
    scan_index: scanIndex,
    original_filename: original,
    stored_filename: `${String(scanIndex).padStart(3, '0')}_7a6b5c${String(id % 100).padStart(2, '0')}.jpg`,
    width: 1555,
    height: 2200,
    s1_status: 'DAT',
    s1_status_label_vi: 'Ảnh đạt chất lượng',
    s1_status_tone: 'info',
    machine_status_label_vi: lab?.label ?? null,
    machine_status_tone: lab?.tone ?? null,
    status_unknown: false,
    effective_action: act,
    doc_type: 'LENH_DIEU_XE',
    doc_type_vi: 'Lệnh điều xe',
    system: 'GT_KIDO',
    page_role: 'SINGLE',
    batch_id: 'BATCH_UPLOAD_001',
    s4_doc_status: code,
    s4_action: act,
    status_label_vi: lab?.label ?? null,
    status_tone: lab?.tone ?? null,
    supported: true,
    reviewed: false,
    effective_doc_status: code,
    s1: { status: 'DAT', action: 'CHUYEN_TANG_2', warns: [], rejects: [], source_type: 'scan', low_resolution: false, effective_dpi: 200 },
    s2: {
      doc_type: 'LENH_DIEU_XE',
      system: 'GT_KIDO',
      page_role: 'SINGLE',
      confidence: 1,
      status: 'DAT',
      key_fields: { shipment_id: 'SH-2026-0912', invoice_no: null, po_no: null, transfer_order_no: null, pxk_no: null },
      evidence: null,
    },
    s4: {
      zone_status: 'TEMPLATE_TOA_DO_CUNG',
      zone_description: 'Ô ký lấy từ template toạ độ cố định của biểu mẫu Lệnh điều xe (14 ô)',
      modality: 'TRUE_COLOR',
      zone_status_label_vi: 'Ô ký lấy từ template toạ độ cố định',
      doc_status: code,
      doc_status_label_vi: lab?.label ?? null,
      action: act,
      action_label_vi: actVi,
      reason,
      required_policy: {
        policy_channel: 'GT',
        policy_channel_unresolved: false,
        policy_channel_reason: 'TEMPLATE(LENH_DIEU_XE)',
        required_roles: req.map((x) => x.role),
        policy_version: '1.0.0',
      },
      a4_size: [1555, 2200],
      targets: LDX_TARGETS.map((x) => ({ ...x })),
    },
    effective: {
      doc_status: code,
      action: act,
      action_label_vi: actVi,
      reason,
      n_overridden: 0,
      n_reviewed: 0,
      source: 'MACHINE',
      label_vi: lab?.label ?? null,
      tone: lab?.tone ?? null,
    },
    image_stage1: lpImg,
    image_original: lpImg,
  };
}

/** Trang Biểu đồ nhiệt độ hành trình — KHÔNG có ô ký nào theo SOP. */
export function makeBieuDoNhietDoPage(id: number, groupId: number, scanIndex: number, original: string): MockPage {
  const lab = LABELS.KHONG_YEU_CAU;
  const reason = 'Biểu mẫu Biểu đồ nhiệt độ hành trình không có ô ký theo SOP';
  return {
    id,
    group_id: groupId,
    scan_index: scanIndex,
    original_filename: original,
    stored_filename: `${String(scanIndex).padStart(3, '0')}_3d2e1f${String(id % 100).padStart(2, '0')}.jpg`,
    width: 1552,
    height: 2200,
    s1_status: 'DAT',
    s1_status_label_vi: 'Ảnh đạt chất lượng',
    s1_status_tone: 'info',
    machine_status_label_vi: lab?.label ?? null,
    machine_status_tone: lab?.tone ?? null,
    status_unknown: false,
    effective_action: 'HOP_LE',
    doc_type: 'BIEU_DO_NHIET_DO',
    doc_type_vi: 'Biểu đồ nhiệt độ hành trình',
    system: 'GT_KIDO',
    page_role: 'SINGLE',
    batch_id: 'BATCH_UPLOAD_001',
    s4_doc_status: 'KHONG_YEU_CAU',
    s4_action: 'HOP_LE',
    status_label_vi: lab?.label ?? null,
    status_tone: lab?.tone ?? null,
    supported: true,
    reviewed: false,
    effective_doc_status: 'KHONG_YEU_CAU',
    s1: { status: 'DAT', action: 'CHUYEN_TANG_2', warns: [], rejects: [], source_type: 'scan', low_resolution: false, effective_dpi: 200 },
    s2: {
      doc_type: 'BIEU_DO_NHIET_DO',
      system: 'GT_KIDO',
      page_role: 'SINGLE',
      confidence: 1,
      status: 'DAT',
      key_fields: { shipment_id: 'SH-2026-0912', invoice_no: null, po_no: null, transfer_order_no: null, pxk_no: null },
      evidence: null,
    },
    s4: {
      zone_status: 'KHONG_CAN_VUNG_KY',
      zone_description: 'Biểu mẫu không có ô ký — không cần dò vùng ký',
      modality: 'N/A',
      zone_status_label_vi: 'Biểu mẫu không có ô ký',
      doc_status: 'KHONG_YEU_CAU',
      doc_status_label_vi: lab?.label ?? null,
      action: 'HOP_LE',
      action_label_vi: 'Hợp lệ (không cần ký ở trang này)',
      reason,
      required_policy: null,
      a4_size: [1552, 2200],
      targets: [],
    },
    effective: {
      doc_status: 'KHONG_YEU_CAU',
      action: 'HOP_LE',
      action_label_vi: 'Hợp lệ (không cần ký ở trang này)',
      reason,
      n_overridden: 0,
      n_reviewed: 0,
      source: 'MACHINE',
      label_vi: lab?.label ?? null,
      tone: lab?.tone ?? null,
    },
    image_stage1: page1Img,
    image_original: page1Img,
  };
}

export interface MockGroup {
  id: number;
  title: string | null;
  owner_id: number;
  use_reference: boolean;
  created_at: string;
  created_ms: number;
  duration_ms: number;
  fail?: boolean;
  page_ids: number[];
}

export const audit: AuditLog[] = [
  { id: 3, created_at: iso(3600e3), action: 'login_ok', actor_email: 'admin@kido.local', ip: '127.0.0.1' },
  { id: 2, created_at: iso(86400e3), action: 'verify_email', actor_email: 'nv@kido.local' },
  { id: 1, created_at: iso(86400e3 * 2), action: 'register', actor_email: 'nv@kido.local', detail: { full_name: 'Nguyễn Văn Kho' } },
];

export function dossierFor(pageList: MockPage[], dossierId: string): Dossier {
  const block = pageList.find((p) => (p.s4?.targets.length ?? 0) > 0);
  // Hồ sơ mà MỌI trang đều thuộc biểu mẫu không cần ký ⇒ không phải "không tìm thấy khối ký".
  const allNoSignRequired = pageList.length > 0 && pageList.every((p) => p.s4_doc_status === 'KHONG_YEU_CAU');
  const machine = block
    ? block.s4?.doc_status ?? 'CHUA_CHUAN_HOA_VUNG_KY'
    : allNoSignRequired
      ? 'KHONG_YEU_CAU'
      : 'KHONG_TIM_THAY_KHOI_KY';
  const eff = block ? block.effective?.doc_status ?? machine : machine;
  const lm = LABELS[machine];
  const le = LABELS[eff];
  const prefix = block ? `[1 trang có khối ký/${pageList.length}] ` : '';
  return {
    dossier_id: dossierId,
    batch_id: pageList[0]?.batch_id ?? null,
    source: 'STAGE3_DOCUMENT',
    pages: pageList.map((p) => p.stored_filename),
    page_refs: pageList.map((p) => ({ page_id: p.id, file_name: p.stored_filename, scan_index: p.scan_index })),
    page_verdicts: Object.fromEntries(pageList.map((p) => [p.stored_filename, p.s4_doc_status ?? ''])),
    policy_channel: 'MT',
    policy_channel_unresolved: false,
    required_roles: ['Tài xế (Lái xe nhận hàng)', 'Người giao / Thủ kho xuất'],
    contract_errors: [],
    doc_status: machine,
    action: machine === 'DAT_CHUAN_GOC' ? 'DUYET' : 'CANH_BAO',
    reason: block
      ? `${prefix}${block.s4?.reason ?? ''}`
      : allNoSignRequired
        ? 'Biểu mẫu không yêu cầu ký theo SOP'
        : 'Không trang nào trong hồ sơ có khối ký',
    label_vi: lm?.label ?? null,
    tone: lm?.tone ?? null,
    unknown: !lm,
    effective_doc_status: eff,
    effective_action: eff === 'DAT_CHUAN_GOC' ? 'DUYET' : 'CANH_BAO',
    effective_reason: block
      ? `${prefix}${block.effective?.reason ?? ''}`
      : allNoSignRequired
        ? 'Biểu mẫu không yêu cầu ký theo SOP'
        : 'Không trang nào trong hồ sơ có khối ký',
    effective_label_vi: le?.label ?? null,
    effective_tone: le?.tone ?? null,
  };
}

export { iso };
