import type { ApiErrorBody } from './types';

/** Thông báo dự phòng khi backend không kèm message tiếng Việt. */
const CODE_MESSAGES: Record<string, string> = {
  EMAIL_NOT_VERIFIED: 'Email chưa được xác thực. Vui lòng mở thư xác thực trong hộp thư của bạn.',
  INVALID_CREDENTIALS: 'Email hoặc mật khẩu không đúng.',
  LAST_ADMIN: 'Không thể thực hiện: hệ thống phải luôn còn ít nhất một quản trị viên đang hoạt động.',
  USER_INACTIVE: 'Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.',
  NETWORK_ERROR: 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.',
};

function statusMessage(status: number): string {
  if (status === 401) return 'Bạn chưa đăng nhập hoặc phiên đã hết hạn.';
  if (status === 403) return 'Bạn không có quyền thực hiện thao tác này.';
  if (status === 404) return 'Không tìm thấy dữ liệu yêu cầu.';
  if (status === 409) return 'Thao tác bị từ chối do xung đột trạng thái.';
  if (status === 413) return 'Tệp tải lên quá lớn.';
  if (status === 422 || status === 400) return 'Dữ liệu gửi lên không hợp lệ.';
  if (status === 429) return 'Bạn thao tác quá nhanh, vui lòng thử lại sau.';
  if (status >= 500) return 'Máy chủ gặp lỗi. Vui lòng thử lại sau.';
  return `Yêu cầu thất bại (mã HTTP ${status}).`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as ApiErrorBody | null)?.detail;
  let code: string | null = null;
  let message: string | null = null;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    code = typeof detail.code === 'string' ? detail.code : null;
    message = typeof detail.message === 'string' ? detail.message : null;
  } else if (typeof detail === 'string') {
    message = detail;
  } else if (Array.isArray(detail)) {
    // Lỗi kiểm dữ liệu kiểu FastAPI mặc định (tiếng Anh) ⇒ dùng câu tiếng Việt chung.
    message = null;
  }
  const finalMessage = message ?? (code ? CODE_MESSAGES[code] : undefined) ?? statusMessage(status);
  return new ApiError(status, code, finalMessage);
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return 'Đã có lỗi không xác định.';
}

export interface RawResponse {
  status: number;
  body: unknown;
}

export type ImageKind = 'stage1' | 'original';

/** Tầng vận chuyển: thật (fetch/XHR) hoặc mock (chỉ khi __MOCK__). */
export interface Transport {
  request(method: string, path: string, body?: unknown): Promise<RawResponse>;
  upload(path: string, form: FormData, onProgress: (loaded: number, total: number) => void): Promise<RawResponse>;
  imageUrl(pageId: number | string, kind: ImageKind): string;
}

const API_PREFIX = '/api';
const CSRF_HEADER = { 'X-Requested-With': 'kido' };

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { detail: null, raw: text };
  }
}

export const httpTransport: Transport = {
  async request(method, path, body) {
    const headers: Record<string, string> = { ...CSRF_HEADER, Accept: 'application/json' };
    let payload: BodyInit | undefined;
    if (body instanceof FormData) {
      payload = body;
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    let res: Response;
    try {
      res = await fetch(API_PREFIX + path, { method, headers, body: payload, credentials: 'include' });
    } catch {
      throw new ApiError(0, 'NETWORK_ERROR', CODE_MESSAGES.NETWORK_ERROR ?? 'Lỗi mạng');
    }
    return { status: res.status, body: await readBody(res) };
  },

  upload(path, form, onProgress) {
    return new Promise<RawResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', API_PREFIX + path);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-Requested-With', 'kido');
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded, e.total);
      };
      xhr.onload = () => {
        let body: unknown = null;
        try {
          body = xhr.responseText ? (JSON.parse(xhr.responseText) as unknown) : null;
        } catch {
          body = null;
        }
        resolve({ status: xhr.status, body });
      };
      xhr.onerror = () => reject(new ApiError(0, 'NETWORK_ERROR', CODE_MESSAGES.NETWORK_ERROR ?? 'Lỗi mạng'));
      xhr.onabort = () => reject(new ApiError(0, 'ABORTED', 'Đã hủy tải lên.'));
      xhr.send(form);
    });
  },

  imageUrl(pageId, kind) {
    return `${API_PREFIX}/pages/${encodeURIComponent(String(pageId))}/image?kind=${kind}`;
  },
};

let transport: Transport = httpTransport;

export function setTransport(t: Transport): void {
  transport = t;
}

export function getTransport(): Transport {
  return transport;
}

/** Phát khi một API (không phải kiểm tra phiên) trả 401 ⇒ AuthProvider đưa về /dang-nhap. */
export const UNAUTHORIZED_EVENT = 'kido:unauthorized';

const SILENT_401_PATHS = ['/auth/me', '/auth/login'];

function handle<T>(path: string, raw: RawResponse): T {
  if (raw.status >= 200 && raw.status < 300) return raw.body as T;
  const err = toApiError(raw.status, raw.body);
  if (raw.status === 401 && !SILENT_401_PATHS.includes(path)) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
  throw err;
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const raw = await transport.request(method, path, body);
  return handle<T>(path, raw);
}

export async function apiUpload<T>(
  path: string,
  form: FormData,
  onProgress: (loaded: number, total: number) => void,
): Promise<T> {
  const raw = await transport.upload(path, form, onProgress);
  return handle<T>(path, raw);
}

export function imageUrl(pageId: number | string, kind: ImageKind): string {
  return transport.imageUrl(pageId, kind);
}
