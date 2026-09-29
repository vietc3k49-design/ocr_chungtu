import type { ReviewDecision, StatusTone } from '../api/types';

// Chỉ các nhãn MÔ TẢ (không phải phán quyết chữ ký). Phán quyết chữ ký luôn lấy
// status_label_vi / status_tone từ backend (app/labels.py). Mã lạ ⇒ hiện nguyên mã + "Cần kiểm tra".

export const UNKNOWN_SUFFIX = 'Cần kiểm tra';

export function unknownLabel(code: string | null | undefined): string {
  return code ? `${code} · ${UNKNOWN_SUFFIX}` : UNKNOWN_SUFFIX;
}

export function normalizeStatus(s: string | null | undefined): string {
  return (s ?? '').toUpperCase();
}

export const GROUP_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  QUEUED: { label: 'Đang chờ xử lý', tone: 'neutral' },
  PENDING: { label: 'Đang chờ xử lý', tone: 'neutral' },
  RUNNING: { label: 'Đang xử lý', tone: 'info' },
  PROCESSING: { label: 'Đang xử lý', tone: 'info' },
  DONE: { label: 'Đã xử lý xong', tone: 'info' },
  FAILED: { label: 'Lỗi xử lý', tone: 'danger' },
};

export function groupStatus(s: string | null | undefined, label?: string | null): { label: string; tone: StatusTone } {
  const known = GROUP_STATUS[normalizeStatus(s)];
  if (label) return { label, tone: known?.tone ?? 'neutral' };
  return known ?? { label: unknownLabel(s), tone: 'neutral' };
}

export function isFinal(s: string | null | undefined): boolean {
  const n = normalizeStatus(s);
  return n === 'DONE' || n === 'FAILED';
}

/** Trạng thái Tầng 1 (chất lượng ảnh) — mô tả, KHÔNG phải phán quyết chữ ký ⇒ không tô xanh. */
const S1_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  DAT: { label: 'Ảnh dùng được', tone: 'neutral' },
  CANH_BAO: { label: 'Ảnh có cảnh báo', tone: 'warning' },
  CHUP_LAI: { label: 'Cần chụp lại', tone: 'danger' },
};

/** Nhãn T1: ưu tiên nhãn/tone backend (s1_status_label_vi / s1_status_tone), thiếu mới dùng bảng FE.
 *  Chất lượng ảnh KHÔNG phải phán quyết chữ ký ⇒ tone success được hạ về neutral (không tô xanh). */
export function s1Status(
  s: string | null | undefined,
  label?: string | null,
  tone?: string | null,
): { label: string; tone: StatusTone } {
  if (label) return { label, tone: safeTone(tone === 'success' ? 'neutral' : tone) };
  if (!s) return { label: 'Chưa có', tone: 'neutral' };
  return S1_STATUS[normalizeStatus(s)] ?? { label: unknownLabel(s), tone: 'neutral' };
}

const PAGE_ROLE: Record<string, string> = {
  HEADER: 'Trang đầu',
  CONTINUATION: 'Trang tiếp',
  TABLE_CONTINUATION: 'Trang tiếp (bảng)',
  SINGLE: 'Trang đơn',
};

export function pageRole(r: string | null | undefined): string {
  if (!r) return '—';
  return PAGE_ROLE[normalizeStatus(r)] ?? r;
}

export const DECISION_LABEL: Record<ReviewDecision, string> = {
  SIGNED: 'Có chữ ký',
  NOT_SIGNED: 'Không có chữ ký',
  UNCLEAR: 'Không rõ',
};

export function decisionLabel(d: string | null | undefined): string {
  if (!d) return '—';
  return (DECISION_LABEL as Record<string, string>)[d] ?? unknownLabel(d);
}

const TONES: StatusTone[] = ['success', 'warning', 'danger', 'neutral', 'info'];

/** Tone lạ / thiếu ⇒ neutral (không bao giờ tự suy ra success). */
export function safeTone(t: string | null | undefined): StatusTone {
  return t && (TONES as string[]).includes(t) ? (t as StatusTone) : 'neutral';
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatPercent(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

/** Kiểm tra `next` an toàn (chỉ đường dẫn nội bộ) — tránh open redirect. */
export function safeNext(next: string | null | undefined): string {
  if (!next) return '/';
  if (!next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/';
  return next;
}
