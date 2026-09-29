// Kiểu dữ liệu khớp hợp đồng API trong web/SPEC.md §3.
// Trường đánh dấu "(giả định)" không có trong SPEC — FE xử lý được cả khi backend không trả.

export type Role = 'user' | 'admin';

export interface UserOut {
  id: number | string;
  email: string;
  full_name: string;
  role: Role | string;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
}

export interface AdminUserOut extends UserOut {
  last_login_at: string | null;
  /** Tạm khóa đăng nhập do sai quá nhiều lần (theo email) — khác `is_active` (admin vô hiệu hóa). */
  login_locked?: boolean;
  login_locked_until?: string | null;
  login_recent_fails?: number;
}

export interface MessageOut {
  message: string;
}

export interface AdminSettings {
  use_reference_default: boolean;
}

/** Bản ghi audit — SPEC không mô tả cột; FE hiển thị linh hoạt. */
export interface AuditLog {
  id?: number | string;
  created_at?: string;
  action?: string;
  user_email?: string | null;
  actor_email?: string | null;
  user_id?: number | string | null;
  actor_id?: string | null;
  entity?: string | null;
  entity_id?: string | null;
  payload?: unknown;
  target_type?: string | null;
  target_id?: string | number | null;
  ip?: string | null;
  detail?: unknown;
  details?: unknown;
  meta?: unknown;
  [key: string]: unknown;
}

export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral' | 'info';

export type GroupStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED' | string;

export interface JobInfo {
  status: string;
  stage: string | null;
  stage_done: number | null;
  stage_total: number | null;
  percent: number | null;
  message: string | null;
  error: string | null;
  id?: string;
  attempts?: number;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface GroupStatusOut {
  status: GroupStatus;
  status_label_vi?: string | null;
  error?: string | null;
  /** job.stage ∈ "T1".."T4" | "SAVE" */
  job: JobInfo | null;
}

export interface GroupSummary {
  id: number | string;
  title: string | null;
  status: GroupStatus;
  status_label_vi?: string | null;
  error?: string | null;
  n_pages: number;
  use_reference: boolean;
  /** Chữ hiển thị badge tham chiếu DEMO (null khi tắt) */
  reference_badge_vi?: string | null;
  created_at: string;
  finished_at: string | null;
  owner_email: string;
  n_lp_pages: number;
  /** Phân bổ phán quyết hồ sơ SAU DUYỆT */
  lp_dossier_summary: Record<string, number> | null;
  /** Phân bổ phán quyết hồ sơ của MÁY */
  lp_dossier_summary_machine?: Record<string, number> | null;
}

export interface DossierPageRef {
  page_id: number | string;
  file_name: string;
  scan_index: number;
}

/** Một phần tử stage4_dossiers.dossiers kèm nhãn (backend app/labels.py). */
export interface Dossier {
  dossier_id: string;
  batch_id?: string | null;
  source?: string | null;
  pages: string[];
  page_refs?: DossierPageRef[];
  page_verdicts?: Record<string, string>;
  page_classes?: Record<string, string>;
  systems?: string[];
  stage3_is_multi_page?: boolean;
  policy_channel?: string | null;
  policy_channel_reason?: string | null;
  policy_channel_unresolved?: boolean;
  required_roles?: string[];
  role_evidence?: Record<string, unknown>;
  contract_errors?: unknown[];
  /** Phán quyết MÁY */
  doc_status: string;
  action?: string | null;
  reason?: string | null;
  label_vi?: string | null;
  tone?: StatusTone | null;
  unknown?: boolean;
  /** Phán quyết SAU DUYỆT */
  effective_doc_status?: string | null;
  effective_action?: string | null;
  effective_reason?: string | null;
  effective_label_vi?: string | null;
  effective_tone?: StatusTone | null;
  [key: string]: unknown;
}

export interface BatchInfo {
  batch_id: string;
  n_documents: number;
  is_isolated: boolean;
}

export interface PageSummary {
  id: number | string;
  group_id?: number | string | null;
  scan_index: number;
  original_filename: string;
  width: number | null;
  height: number | null;
  s1_status: string | null;
  s1_status_label_vi?: string | null;
  s1_status_tone?: StatusTone | null;
  doc_type: string | null;
  doc_type_vi: string | null;
  system: string | null;
  page_role: string | null;
  batch_id: string | null;
  s4_doc_status: string | null;
  s4_action: string | null;
  /** Nhãn/tone phán quyết SAU DUYỆT (hiệu lực) */
  status_label_vi: string | null;
  status_tone: StatusTone | null;
  status_unknown?: boolean;
  /** Nhãn/tone phán quyết MÁY */
  machine_status_label_vi?: string | null;
  machine_status_tone?: StatusTone | null;
  supported: boolean;
  reviewed: boolean;
  effective_doc_status: string | null;
  effective_action?: string | null;
  key_fields?: Record<string, unknown> | null;
}

export interface GroupDetail extends GroupSummary {
  pages: PageSummary[];
  dossiers: Dossier[];
  batches: BatchInfo[];
  reference_info: unknown;
  timings: Record<string, unknown> | null;
  pipeline_contract?: string | null;
  stage3_scope: 'UPLOAD_GROUP' | string;
  job: JobInfo | null;
}

export type ReviewDecision = 'SIGNED' | 'NOT_SIGNED' | 'UNCLEAR';

export interface LatestReview {
  id?: number | string;
  target_index?: number;
  role?: string | null;
  machine_detected?: boolean | null;
  decision: ReviewDecision;
  decision_vi?: string | null;
  note: string | null;
  reviewer_email: string;
  created_at: string;
  stale?: boolean;
}

export interface TargetOut {
  index: number;
  role: string;
  required: boolean;
  required_source: string | null;
  policy_channel: string | null;
  box_norm: [number, number, number, number];
  detected: boolean;
  confidence: number | null;
  evidence: string | null;
  evidence_label_vi?: string | null;
  evidence_vi?: string | null;
  reason: string | null;
  review_required: boolean;
  latest_review: LatestReview | null;
  effective_detected: boolean | null;
  /** Diện tích mực THUỘC ô (đã trừ mực tràn từ cột bên) — mm². Backend cũ không trả ⇒ không hiện. */
  muc_so_huu_mm2?: number | null;
  /** Số cụm nét mực thuộc ô. Backend cũ không trả ⇒ không hiện. */
  so_cum?: number | null;
}

export interface S1Info {
  status: string | null;
  status_label_vi?: string | null;
  action: string | null;
  warns: string[] | null;
  rejects: string[] | null;
  source_type: string | null;
  low_resolution: boolean | null;
  effective_dpi?: number | null;
  error?: string | null;
}

export interface S2Info {
  doc_type: string | null;
  doc_type_vi?: string | null;
  system: string | null;
  page_role: string | null;
  confidence: number | null;
  status: string | null;
  key_fields: Record<string, unknown> | null;
  evidence: unknown;
}

export interface S4Info {
  zone_status: string | null;
  zone_status_label_vi?: string | null;
  zone_description: string | null;
  modality: string | null;
  /** Phán quyết MÁY */
  doc_status: string | null;
  doc_status_label_vi?: string | null;
  action: string | null;
  action_label_vi?: string | null;
  reason: string | null;
  required_policy: Record<string, unknown> | null;
  a4_size: unknown;
  targets: TargetOut[];
}

/** Phán quyết SAU DUYỆT của trang */
export interface EffectiveInfo {
  doc_status: string | null;
  action: string | null;
  action_label_vi?: string | null;
  reason: string | null;
  n_overridden: number;
  n_reviewed?: number;
  source?: string | null;
  label_vi?: string | null;
  tone?: StatusTone | null;
}

export interface PageDetail extends PageSummary {
  group_title?: string | null;
  group_status?: string | null;
  s1: S1Info | null;
  s2: S2Info | null;
  s4: S4Info | null;
  effective: EffectiveInfo | null;
}

export interface ReviewOut {
  id?: number | string;
  target_index: number;
  role?: string | null;
  machine_detected?: boolean | null;
  decision: ReviewDecision;
  decision_vi?: string | null;
  note: string | null;
  reviewer_email: string;
  created_at: string;
  stale?: boolean;
}

export interface ApiErrorBody {
  detail?: { code?: string; message?: string } | string | Array<{ msg?: string }>;
}
