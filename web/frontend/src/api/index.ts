import { api, apiUpload } from './client';
import type {
  AdminSettings,
  AdminUserOut,
  AuditLog,
  GroupDetail,
  GroupStatusOut,
  GroupSummary,
  MessageOut,
  PageDetail,
  ReviewDecision,
  ReviewOut,
  UserOut,
} from './types';

export * from './types';
export { ApiError, errorMessage, imageUrl } from './client';

const enc = (v: string | number) => encodeURIComponent(String(v));

export const authApi = {
  register: (body: { email: string; password: string; full_name: string }) =>
    api<MessageOut>('POST', '/auth/register', body),
  verifyEmail: (token: string) => api<MessageOut>('POST', '/auth/verify-email', { token }),
  resendVerification: (email: string) => api<MessageOut>('POST', '/auth/resend-verification', { email }),
  login: (email: string, password: string) => api<UserOut>('POST', '/auth/login', { email, password }),
  logout: () => api<MessageOut>('POST', '/auth/logout'),
  me: () => api<UserOut>('GET', '/auth/me'),
  forgotPassword: (email: string) => api<MessageOut>('POST', '/auth/forgot-password', { email }),
  resetPassword: (token: string, new_password: string) =>
    api<MessageOut>('POST', '/auth/reset-password', { token, new_password }),
  changePassword: (old_password: string, new_password: string) =>
    api<MessageOut>('POST', '/auth/change-password', { old_password, new_password }),
};

export const adminApi = {
  users: (q?: string) => api<AdminUserOut[]>('GET', `/admin/users${q ? `?q=${enc(q)}` : ''}`),
  updateUser: (id: number | string, patch: { role?: string; is_active?: boolean }) =>
    api<AdminUserOut>('PATCH', `/admin/users/${enc(id)}`, patch),
  unlockLogin: (id: number | string) => api<AdminUserOut>('POST', `/admin/users/${enc(id)}/unlock-login`),
  settings: () => api<AdminSettings>('GET', '/admin/settings'),
  saveSettings: (s: AdminSettings) => api<AdminSettings>('PUT', '/admin/settings', s),
  audit: (limit = 200) => api<AuditLog[]>('GET', `/admin/audit?limit=${limit}`),
};

export const groupsApi = {
  list: (all = false) => api<GroupSummary[]>('GET', `/groups${all ? '?all=true' : ''}`),
  get: (id: number | string) => api<GroupDetail>('GET', `/groups/${enc(id)}`),
  status: (id: number | string) => api<GroupStatusOut>('GET', `/groups/${enc(id)}/status`),
  rerun: (id: number | string) => api<unknown>('POST', `/groups/${enc(id)}/rerun`),
  /**
   * Tải lên một bộ: `files` theo đúng thứ tự (thứ tự = scan_index 0..n-1).
   * `useReference` chỉ gửi khi người dùng là admin (khác undefined).
   */
  create: (
    files: File[],
    title: string,
    useReference: boolean | undefined,
    onProgress: (loaded: number, total: number) => void,
  ) => {
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);
    if (title.trim()) form.append('title', title.trim());
    if (useReference !== undefined) form.append('use_reference', useReference ? 'true' : 'false');
    return apiUpload<GroupDetail>('/groups', form, onProgress);
  },
};

export const pagesApi = {
  get: (id: number | string) => api<PageDetail>('GET', `/pages/${enc(id)}`),
  review: (id: number | string, targetIndex: number, decision: ReviewDecision, note: string) =>
    api<PageDetail>('POST', `/pages/${enc(id)}/targets/${targetIndex}/review`, { decision, note }),
  reviews: (id: number | string) => api<ReviewOut[]>('GET', `/pages/${enc(id)}/reviews`),
};
