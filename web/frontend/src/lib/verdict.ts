import type { Dossier, PageDetail, PageSummary, StatusTone } from '../api/types';
import { safeTone, unknownLabel } from './labels';

// Quy tắc: FE KHÔNG tự đặt nhãn "Đạt"/màu xanh cho phán quyết chữ ký. Nhãn + tone lấy từ backend
// (app/labels.py). Thiếu nhãn ⇒ hiện nguyên mã + "Cần kiểm tra", tone neutral.
//
// Khóa backend (đã đối chiếu JSON thật):
//   trang  — MÁY: machine_status_label_vi / machine_status_tone (s4.doc_status_label_vi)
//            SAU DUYỆT: status_label_vi / status_tone, effective.{label_vi, tone}
//   hồ sơ  — MÁY: label_vi / tone;  SAU DUYỆT: effective_label_vi / effective_tone / effective_reason

export interface Verdict {
  code: string | null;
  label: string;
  tone: StatusTone;
}

export const NOT_SUPPORTED: Verdict = { code: null, label: 'Chưa hỗ trợ kiểm chữ ký', tone: 'neutral' };

// Biểu mẫu KHÔNG có ô ký theo SOP (vd. Biểu đồ nhiệt độ hành trình): không phải lỗi, không phải
// "chưa hỗ trợ". Nhãn chuẩn nằm ở backend (app/labels.py: KHONG_YEU_CAU) — hằng dưới đây chỉ dùng
// khi backend chưa trả nhãn, và để FE nhận diện trường hợp này mà không cần biết doc_type.
export const NO_SIGN_REQUIRED_CODE = 'KHONG_YEU_CAU';
export const NO_SIGN_REQUIRED_LABEL = 'Không yêu cầu ký theo SOP';
/** zone_status của biểu mẫu không có ô ký (backend Tầng 3b). */
export const NO_ZONE_NEEDED_STATUS = 'KHONG_CAN_VUNG_KY';

const NO_SIGN_REQUIRED: Verdict = { code: NO_SIGN_REQUIRED_CODE, label: NO_SIGN_REQUIRED_LABEL, tone: 'info' };

/**
 * Trang thuộc biểu mẫu không cần ký? Suy từ mã trạng thái backend, KHÔNG suy từ doc_type —
 * nhờ vậy thêm biểu mẫu mới không phải sửa FE.
 */
export function isNoSignRequired(p: PageDetail | PageSummary): boolean {
  const d = p as PageDetail;
  const codes = [
    d.effective?.doc_status,
    p.effective_doc_status,
    d.s4?.doc_status,
    p.s4_doc_status,
  ];
  if (codes.some((c) => c === NO_SIGN_REQUIRED_CODE)) return true;
  return d.s4?.zone_status === NO_ZONE_NEEDED_STATUS;
}

function fromBackend(code: string | null | undefined, label: string | null | undefined, tone: string | null | undefined): Verdict {
  if (label) return { code: code ?? null, label, tone: safeTone(tone) };
  if (!code) return { code: null, label: 'Chưa có kết quả', tone: 'neutral' };
  return { code, label: unknownLabel(code), tone: 'neutral' };
}

/** Trạng thái kiểm ký SAU DUYỆT (hiệu lực) của một trang — dùng ở bảng mọi trang. */
export function pageSignatureStatus(p: PageSummary): Verdict {
  if (isNoSignRequired(p)) return fromBackend(NO_SIGN_REQUIRED_CODE, p.status_label_vi ?? NO_SIGN_REQUIRED_LABEL, p.status_tone ?? 'info');
  if (!p.supported) return NOT_SUPPORTED;
  const v = fromBackend(p.effective_doc_status ?? p.s4_doc_status, p.status_label_vi, p.status_tone);
  return p.status_unknown ? { ...v, tone: 'neutral' } : v;
}

/** Phán quyết MÁY cấp trang (bảng mọi trang). */
export function pageMachineStatus(p: PageSummary): Verdict {
  if (isNoSignRequired(p)) return fromBackend(NO_SIGN_REQUIRED_CODE, p.machine_status_label_vi ?? NO_SIGN_REQUIRED_LABEL, p.machine_status_tone ?? 'info');
  if (!p.supported) return NOT_SUPPORTED;
  return fromBackend(p.s4_doc_status, p.machine_status_label_vi, p.machine_status_tone);
}

export function pageMachineVerdict(p: PageDetail): Verdict {
  if (isNoSignRequired(p)) {
    const lb = p.machine_status_label_vi ?? p.s4?.doc_status_label_vi;
    return lb ? fromBackend(NO_SIGN_REQUIRED_CODE, lb, p.machine_status_tone ?? 'info') : NO_SIGN_REQUIRED;
  }
  if (!p.supported) return NOT_SUPPORTED;
  const code = p.s4?.doc_status ?? p.s4_doc_status;
  return fromBackend(code, p.machine_status_label_vi ?? p.s4?.doc_status_label_vi, p.machine_status_tone);
}

export function pageEffectiveVerdict(p: PageDetail): Verdict {
  if (isNoSignRequired(p)) {
    const lb = p.effective?.label_vi ?? p.status_label_vi;
    return lb ? fromBackend(NO_SIGN_REQUIRED_CODE, lb, p.effective?.tone ?? p.status_tone ?? 'info') : NO_SIGN_REQUIRED;
  }
  if (!p.supported) return NOT_SUPPORTED;
  const code = p.effective?.doc_status ?? p.effective_doc_status ?? p.s4?.doc_status ?? null;
  return fromBackend(code, p.effective?.label_vi ?? p.status_label_vi, p.effective?.tone ?? p.status_tone);
}

export function dossierMachineVerdict(d: Dossier): Verdict {
  const v = fromBackend(d.doc_status, d.label_vi, d.tone);
  return d.unknown ? { ...v, tone: 'neutral' } : v;
}

/** Phán quyết hồ sơ sau duyệt — null nếu backend không trả (hiển thị "—"). */
export function dossierEffectiveVerdict(d: Dossier): Verdict | null {
  const code = d.effective_doc_status ?? null;
  if (!code) return null;
  return fromBackend(code, d.effective_label_vi, d.effective_tone);
}

/** Nối trang của hồ sơ với PageSummary: ưu tiên page_refs (page_id), sau đó scan_index / tên file. */
export function resolveDossierPages(d: Dossier, pages: PageSummary[]): Array<{ name: string; page: PageSummary | null }> {
  const byId = new Map(pages.map((p) => [String(p.id), p]));
  const byIndex = new Map(pages.map((p) => [p.scan_index, p]));
  const byOriginal = new Map(pages.map((p) => [p.original_filename, p]));
  if (d.page_refs?.length) {
    return [...d.page_refs]
      .sort((a, b) => a.scan_index - b.scan_index)
      .map((r) => ({
        name: r.file_name,
        page: byId.get(String(r.page_id)) ?? byIndex.get(r.scan_index) ?? null,
      }));
  }
  return (d.pages ?? []).map((name) => {
    // Quy ước lưu file SPEC §3: {scan_index:03d}_{sha8}.{ext}
    const m = name.match(/^(\d{3})_[0-9a-f]+\.(jpe?g|png)$/i);
    if (m?.[1]) {
      const p = byIndex.get(Number(m[1]));
      if (p) return { name, page: p };
    }
    return { name, page: byOriginal.get(name) ?? null };
  });
}
