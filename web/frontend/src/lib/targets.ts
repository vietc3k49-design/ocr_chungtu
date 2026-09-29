import type { TargetOut } from '../api/types';

export type TargetState = 'signed' | 'missing_required' | 'missing_optional' | 'review';

/**
 * Trạng thái hiển thị của một ô ký (SPEC §6):
 * - cam: review_required hoặc duyệt "Không rõ" (hoặc hiệu lực null sau duyệt)
 * - xanh lá: effective_detected = true
 * - đỏ: bắt buộc mà không thấy
 * - xám: không bắt buộc và không thấy
 */
export function targetState(t: TargetOut): TargetState {
  if (t.review_required || t.latest_review?.decision === 'UNCLEAR') return 'review';
  let eff = t.effective_detected;
  if (eff === null || eff === undefined) {
    // Chưa có duyệt tay ⇒ hiệu lực = máy. Có duyệt mà vẫn null ⇒ không rõ.
    if (!t.latest_review) eff = t.detected;
    else return 'review';
  }
  if (eff) return 'signed';
  return t.required ? 'missing_required' : 'missing_optional';
}

export const STATE_COLOR: Record<TargetState, string> = {
  signed: 'var(--box-signed)',
  missing_required: 'var(--box-missing-required)',
  missing_optional: 'var(--box-missing-optional)',
  review: 'var(--box-review)',
};

export const STATE_LABEL: Record<TargetState, string> = {
  signed: 'Có chữ ký',
  missing_required: 'Bắt buộc — không thấy chữ ký',
  missing_optional: 'Không bắt buộc — không thấy chữ ký',
  review: 'Cần kiểm tra tay',
};

export function evidenceText(t: TargetOut): string {
  return t.evidence_vi || t.evidence_label_vi || t.evidence || '—';
}

/** Chuẩn hóa box_norm [ymin,xmin,ymax,xmax] về khoảng 0..1, loại box hỏng. */
export function validBox(b: unknown): [number, number, number, number] | null {
  if (!Array.isArray(b) || b.length !== 4) return null;
  const n = b.map((v) => (typeof v === 'number' && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : NaN));
  if (n.some((v) => Number.isNaN(v))) return null;
  const [y0, x0, y1, x1] = n as [number, number, number, number];
  if (y1 <= y0 || x1 <= x0) return null;
  return [y0, x0, y1, x1];
}
