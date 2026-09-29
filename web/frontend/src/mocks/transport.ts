// Adapter fetch GIẢ cho chế độ VITE_MOCK=1. Mô phỏng hợp đồng web/SPEC.md §3 ở mức đủ để kiểm UI.
// Luật phán quyết sau duyệt ở đây là MÔ PHỎNG đơn giản — backend thật gọi evaluate_document_verdict_v2.

import type { RawResponse, Transport } from '../api/client';
import type {
  GroupDetail,
  GroupSummary,
  PageSummary,
  ReviewDecision,
  ReviewOut,
  UserOut,
} from '../api/types';
import {
  LABELS,
  audit,
  dossierFor,
  makeBieuDoNhietDoPage,
  makeLenhDieuXePage,
  makeLpPage,
  makeOtherPage,
  makeTrang1Page,
  users,
  type MockGroup,
  type MockPage,
  type MockUser,
} from './data';

const SESSION_KEY = 'kido_mock_session';
let settings = { use_reference_default: false };
const pages = new Map<string, MockPage>();
const reviews: Array<ReviewOut & { page_id: string }> = [];
const groups: MockGroup[] = [];
let nextPageId = 200;
let nextGroupId = 4;

function addPage(p: MockPage) {
  pages.set(String(p.id), p);
}

// Bộ 1: đã xong (3 trang). Bộ 2: đang chạy (tiến độ theo thời gian thực).
{
  const t0 = Date.now() - 3600e3;
  addPage(makeLpPage(101, 1, 0, 'Load3.3__0.png'));
  addPage(makeTrang1Page(102, 1, 1, 'Loading_Plan3.1__1.png'));
  addPage(makeOtherPage(103, 1, 2, 'PO_3.6__1.jpg', pages.get('102')?.image_stage1 ?? ''));
  groups.push({ id: 1, title: 'DEMO Loading Plan BigC (mock)', owner_id: 1, use_reference: false, created_at: new Date(t0).toISOString(), created_ms: t0, duration_ms: 0, page_ids: [101, 102, 103] });
  const t1 = Date.now();
  addPage(makeLpPage(111, 2, 0, 'Load3.3__0.png'));
  groups.push({ id: 2, title: 'Bộ đang xử lý (mock)', owner_id: 2, use_reference: true, created_at: new Date(t1).toISOString(), created_ms: t1, duration_ms: 25000, page_ids: [111] });
  // Bộ 3: đủ 3 loại biểu mẫu có kiểm ký — Lệnh điều xe (14 ô, template toạ độ cứng),
  // Biểu đồ nhiệt độ (không có ô ký nào) và Loading Plan (vùng ký dò động).
  const t2 = Date.now() - 7200e3;
  addPage(makeLenhDieuXePage(121, 3, 0, 'LenhDieuXe_01.jpg'));
  addPage(makeBieuDoNhietDoPage(122, 3, 1, 'BieuDoNhietDo_01.jpg'));
  addPage(makeLpPage(123, 3, 2, 'Load3.3__0.png'));
  groups.push({ id: 3, title: 'DEMO 3 loại biểu mẫu (mock)', owner_id: 1, use_reference: false, created_at: new Date(t2).toISOString(), created_ms: t2, duration_ms: 0, page_ids: [121, 122, 123] });
}

function readSession(): number | null {
  try {
    const v = sessionStorage.getItem(SESSION_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}
let sessionUserId: number | null = readSession();
// Tiện ích mock: ?mock_login=admin|nv ⇒ đăng nhập sẵn (chỉ tồn tại trong chế độ mock).
{
  const who = new URLSearchParams(window.location.search).get('mock_login');
  const u = who ? users.find((x) => x.email.startsWith(`${who}@`)) : undefined;
  if (u) sessionUserId = Number(u.id);
}
function setSession(id: number | null) {
  sessionUserId = id;
  try {
    if (id === null) sessionStorage.removeItem(SESSION_KEY);
    else sessionStorage.setItem(SESSION_KEY, String(id));
  } catch {
    /* bỏ qua */
  }
}

const ok = (body: unknown, status = 200): RawResponse => ({ status, body });
const err = (status: number, code: string, message: string): RawResponse => ({ status, body: { detail: { code, message } } });
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

function userOut(u: MockUser): UserOut & { last_login_at: string | null } {
  const { password: _pw, ...rest } = u;
  void _pw;
  return rest;
}

function currentUser(): MockUser | null {
  return users.find((u) => u.id === sessionUserId && u.is_active && u.email_verified) ?? null;
}

function progressOf(g: MockGroup): { status: string; percent: number; stage: string; message: string } {
  if (g.fail) return { status: 'FAILED', percent: 42, stage: 'T2', message: 'Lỗi mô phỏng' };
  if (g.duration_ms <= 0) return { status: 'DONE', percent: 100, stage: 'SAVE', message: 'Hoàn tất' };
  const el = Date.now() - g.created_ms;
  if (el < 2000) return { status: 'QUEUED', percent: 0, stage: '', message: 'Đang chờ worker' };
  const p = Math.min(100, ((el - 2000) / g.duration_ms) * 100);
  if (p >= 100) return { status: 'DONE', percent: 100, stage: 'SAVE', message: 'Hoàn tất' };
  const stage = p < 40 ? 'T1' : p < 80 ? 'T2' : p < 85 ? 'T3' : p < 98 ? 'T4' : 'SAVE';
  const msg: Record<string, string> = {
    T1: 'Chuẩn hóa ảnh',
    T2: 'Phân loại chứng từ',
    T3: 'Gom lô trong bộ',
    T4: 'Kiểm chữ ký chứng từ',
    SAVE: 'Lưu kết quả',
  };
  return { status: 'RUNNING', percent: p, stage, message: msg[stage] ?? '' };
}

function job(g: MockGroup) {
  const pr = progressOf(g);
  return {
    status: pr.status,
    stage: pr.stage || null,
    stage_done: Math.round((pr.percent % 40) / 4),
    stage_total: 10,
    percent: pr.percent,
    message: pr.message,
    error: g.fail ? 'Traceback (mock)\nRuntimeError: lỗi mô phỏng' : null,
  };
}

function pageSummary(p: MockPage): PageSummary {
  return {
    id: p.id,
    scan_index: p.scan_index,
    original_filename: p.original_filename,
    width: p.width,
    height: p.height,
    s1_status: p.s1_status,
    doc_type: p.doc_type,
    doc_type_vi: p.doc_type_vi,
    system: p.system,
    page_role: p.page_role,
    batch_id: p.batch_id,
    s4_doc_status: p.s4_doc_status,
    s4_action: p.s4_action,
    status_label_vi: p.status_label_vi,
    status_tone: p.status_tone,
    supported: p.supported,
    reviewed: p.reviewed,
    effective_doc_status: p.effective_doc_status,
    group_id: p.group_id,
    s1_status_label_vi: p.s1_status_label_vi,
    s1_status_tone: p.s1_status_tone,
    machine_status_label_vi: p.machine_status_label_vi,
    machine_status_tone: p.machine_status_tone,
    status_unknown: p.status_unknown,
    effective_action: p.effective_action,
    key_fields: p.key_fields ?? p.s2?.key_fields ?? null,
  };
}

function groupPages(g: MockGroup): MockPage[] {
  return g.page_ids.map((id) => pages.get(String(id))).filter((p): p is MockPage => Boolean(p));
}

function summary(g: MockGroup): GroupSummary {
  const pr = progressOf(g);
  const owner = users.find((u) => u.id === g.owner_id);
  const done = pr.status === 'DONE';
  // Đếm theo cờ `supported` (trang có kiểm ký), KHÔNG theo doc_type — thêm biểu mẫu mới không phải sửa.
  const lp = groupPages(g).filter((p) => p.supported);
  const dossiers = done ? dossiersOf(g) : [];
  const counts: Record<string, number> = {};
  const countsMachine: Record<string, number> = {};
  for (const d of dossiers) {
    const e = d.effective_doc_status ?? d.doc_status;
    counts[e] = (counts[e] ?? 0) + 1;
    countsMachine[d.doc_status] = (countsMachine[d.doc_status] ?? 0) + 1;
  }
  const statusVi: Record<string, string> = { QUEUED: 'Đang chờ', RUNNING: 'Đang xử lý', DONE: 'Hoàn tất', FAILED: 'Lỗi' };
  return {
    id: g.id,
    title: g.title,
    status: pr.status,
    status_label_vi: statusVi[pr.status] ?? null,
    n_pages: g.page_ids.length,
    use_reference: g.use_reference,
    reference_badge_vi: g.use_reference ? 'Dùng dữ liệu tham chiếu DEMO (suy từ GT)' : null,
    created_at: g.created_at,
    finished_at: done ? new Date(g.created_ms + g.duration_ms + 2000).toISOString() : null,
    owner_email: owner?.email ?? '?',
    n_lp_pages: lp.length,
    lp_dossier_summary: done ? counts : null,
    lp_dossier_summary_machine: done ? countsMachine : null,
    error: g.fail ? 'Xử lý thất bại ở Tầng 2 (mô phỏng).' : null,
  };
}

function dossiersOf(g: MockGroup) {
  const lp = groupPages(g).filter((p) => p.supported);
  return lp.map((p, i) => dossierFor([p], `DOC_${String(i).padStart(3, '0')}`));
}

function detail(g: MockGroup): GroupDetail {
  const s = summary(g);
  const done = s.status === 'DONE';
  const ps = groupPages(g);
  const batchIds = [...new Set(ps.map((p) => p.batch_id ?? ''))].filter(Boolean);
  return {
    ...s,
    pages: done ? ps.map(pageSummary) : [],
    dossiers: done ? dossiersOf(g) : [],
    batches: done ? batchIds.map((b) => ({ batch_id: b, n_documents: ps.filter((p) => p.batch_id === b).length, is_isolated: b.startsWith('UNRESOLVED') })) : [],
    reference_info: g.use_reference ? { reference_loaded: true, reference_status: 'DEMO_DERIVED_FROM_GROUND_TRUTH' } : { reference_loaded: false },
    timings: done ? { stage1_s: 3.1, stage2_s: 4.2, stage3_s: 0.1, stage4_s: 1.3 } : null,
    stage3_scope: 'UPLOAD_GROUP',
    job: job(g),
  };
}

function canSee(g: MockGroup, u: MockUser): boolean {
  return u.role === 'admin' || g.owner_id === u.id;
}

/** Mô phỏng evaluate_document_verdict_v2 — CHỈ để kiểm UI. */
function recomputeEffective(p: MockPage) {
  const s4 = p.s4;
  if (!s4 || !s4.targets.length) return;
  let n = 0;
  for (const t of s4.targets) {
    const r = t.latest_review;
    if (!r) {
      t.effective_detected = t.detected;
      continue;
    }
    if (r.decision === 'SIGNED') t.effective_detected = true;
    else if (r.decision === 'NOT_SIGNED') t.effective_detected = false;
    else t.effective_detected = null;
    if (r.decision === 'UNCLEAR' || t.effective_detected !== t.detected) n += 1;
  }
  const req = s4.targets.filter((t) => t.required);
  let code: string;
  let reason: string;
  if (req.some((t) => t.effective_detected === null || t.review_required)) {
    code = 'CAN_KIEM_TRA_TAY';
    reason = 'Có ô bắt buộc cần kiểm tra tay';
  } else if (req.every((t) => t.effective_detected)) {
    code = 'DAT_CHUAN_GOC';
    reason = `Đạt chuẩn tất cả ${req.length} chữ ký/mộc bắt buộc`;
  } else if (req.some((t) => t.effective_detected)) {
    code = 'THIEU_MOT_SO_CHU_KY';
    reason = `Thiếu ${req.filter((t) => !t.effective_detected).length}/${req.length} chữ ký bắt buộc`;
  } else {
    code = 'CHUA_KY_DONG_DAU';
    reason = 'Không có chữ ký bắt buộc nào';
  }
  const lab = LABELS[code];
  p.effective = {
    doc_status: code,
    action: code === 'DAT_CHUAN_GOC' ? 'DUYET' : 'CANH_BAO',
    action_label_vi: code === 'DAT_CHUAN_GOC' ? 'Duyệt' : 'Cảnh báo',
    reason,
    n_overridden: n,
    n_reviewed: s4.targets.filter((t) => t.latest_review).length,
    source: 'AFTER_REVIEW',
    label_vi: lab?.label ?? null,
    tone: lab?.tone ?? null,
  };
  p.effective_action = p.effective.action;
  p.effective_doc_status = code;
  p.status_label_vi = LABELS[code]?.label ?? null;
  p.status_tone = LABELS[code]?.tone ?? null;
  p.reviewed = s4.targets.some((t) => t.latest_review);
}

function parseJson(body: unknown): Record<string, unknown> {
  return body && typeof body === 'object' && !(body instanceof FormData) ? (body as Record<string, unknown>) : {};
}

async function handle(method: string, fullPath: string, body: unknown): Promise<RawResponse> {
  await delay(120 + Math.random() * 180);
  const [path = '', qs = ''] = fullPath.split('?');
  const query = new URLSearchParams(qs);
  const b = parseJson(body);
  const me = currentUser();
  const route = `${method} ${path}`;
  let m: RegExpMatchArray | null;

  // ---- Auth ----
  if (route === 'POST /auth/login') {
    const u = users.find((x) => x.email.toLowerCase() === String(b.email ?? '').toLowerCase());
    if (!u || u.password !== b.password) return err(401, 'INVALID_CREDENTIALS', 'Email hoặc mật khẩu không đúng.');
    if (!u.email_verified) return err(403, 'EMAIL_NOT_VERIFIED', 'Email chưa được xác thực. Vui lòng kiểm tra hộp thư.');
    if (!u.is_active) return err(403, 'USER_INACTIVE', 'Tài khoản đã bị khóa.');
    setSession(Number(u.id));
    u.last_login_at = new Date().toISOString();
    return ok(userOut(u));
  }
  if (route === 'GET /auth/me') return me ? ok(userOut(me)) : err(401, 'NOT_AUTHENTICATED', 'Chưa đăng nhập.');
  if (route === 'POST /auth/logout') {
    setSession(null);
    return ok({ message: 'Đã đăng xuất.' });
  }
  if (route === 'POST /auth/register') {
    const email = String(b.email ?? '').trim();
    if (String(b.password ?? '').length < 8) return err(422, 'WEAK_PASSWORD', 'Mật khẩu phải có ít nhất 8 ký tự.');
    if (users.some((u) => u.email === email)) return err(409, 'EMAIL_EXISTS', 'Email đã được đăng ký.');
    users.push({ id: users.length + 1, email, password: String(b.password), full_name: String(b.full_name ?? ''), role: 'user', is_active: true, email_verified: false, created_at: new Date().toISOString(), last_login_at: null });
    return ok({ message: 'Đăng ký thành công. Vui lòng kiểm tra email để xác thực tài khoản. (mock: dùng token "ok-<email>")' }, 201);
  }
  if (route === 'POST /auth/verify-email') {
    const token = String(b.token ?? '');
    const u = token.startsWith('ok-') ? users.find((x) => x.email === token.slice(3)) : users.find((x) => !x.email_verified);
    if (!u || token === 'bad') return err(400, 'INVALID_TOKEN', 'Liên kết xác thực không hợp lệ hoặc đã hết hạn.');
    u.email_verified = true;
    return ok({ message: 'Xác thực email thành công.' });
  }
  if (route === 'POST /auth/resend-verification' || route === 'POST /auth/forgot-password')
    return ok({ message: 'Nếu email tồn tại, thư đã được gửi. Vui lòng kiểm tra hộp thư.' });
  if (route === 'POST /auth/reset-password') {
    if (String(b.token ?? '') === 'bad') return err(400, 'INVALID_TOKEN', 'Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.');
    return ok({ message: 'Đã đặt lại mật khẩu.' });
  }

  if (!me) return err(401, 'NOT_AUTHENTICATED', 'Chưa đăng nhập.');

  if (route === 'POST /auth/change-password') {
    if (b.old_password !== me.password) return err(400, 'INVALID_CREDENTIALS', 'Mật khẩu hiện tại không đúng.');
    me.password = String(b.new_password);
    return ok({ message: 'Đã đổi mật khẩu.' });
  }

  // ---- Admin ----
  if (path.startsWith('/admin/') && me.role !== 'admin') return err(403, 'FORBIDDEN', 'Chỉ quản trị viên.');
  if (route === 'GET /admin/users') {
    const q = (query.get('q') ?? '').toLowerCase();
    return ok(users.filter((u) => !q || u.email.includes(q) || u.full_name.toLowerCase().includes(q)).map(userOut));
  }
  if (method === 'PATCH' && (m = path.match(/^\/admin\/users\/(\d+)$/))) {
    const u = users.find((x) => x.id === Number(m?.[1]));
    if (!u) return err(404, 'NOT_FOUND', 'Không tìm thấy người dùng.');
    const activeAdmins = users.filter((x) => x.role === 'admin' && x.is_active);
    const demote = b.role === 'user' || b.is_active === false;
    if (demote && u.role === 'admin' && activeAdmins.length <= 1)
      return err(409, 'LAST_ADMIN', 'Không thể hạ quyền/khóa quản trị viên cuối cùng.');
    if (typeof b.role === 'string') u.role = b.role;
    if (typeof b.is_active === 'boolean') u.is_active = b.is_active;
    audit.unshift({ id: audit.length + 1, created_at: new Date().toISOString(), action: 'role_change', actor_email: me.email, target_type: 'user', target_id: u.id });
    return ok(userOut(u));
  }
  if (method === 'POST' && (m = path.match(/^\/admin\/users\/(\d+)\/unlock-login$/))) {
    const u = users.find((x) => x.id === Number(m?.[1]));
    if (!u) return err(404, 'USER_NOT_FOUND', 'Không tìm thấy người dùng.');
    audit.unshift({ id: audit.length + 1, created_at: new Date().toISOString(), action: 'login_unlock', actor_email: me.email, target_type: 'user', target_id: u.id });
    return ok({ ...userOut(u), login_locked: false, login_locked_until: null, login_recent_fails: 0 });
  }
  if (route === 'GET /admin/settings') return ok(settings);
  if (route === 'PUT /admin/settings') {
    settings = { use_reference_default: Boolean(b.use_reference_default) };
    audit.unshift({ id: audit.length + 1, created_at: new Date().toISOString(), action: 'setting_change', actor_email: me.email, detail: settings });
    return ok(settings);
  }
  if (route === 'GET /admin/audit') return ok(audit.slice(0, Number(query.get('limit') ?? 200)));

  // ---- Groups ----
  if (route === 'GET /groups') {
    const all = query.get('all') === 'true' && me.role === 'admin';
    return ok(groups.filter((g) => (all ? true : g.owner_id === me.id)).sort((a, b2) => b2.created_ms - a.created_ms).map(summary));
  }
  if (route === 'POST /groups') {
    if (!(body instanceof FormData)) return err(400, 'BAD_REQUEST', 'Thiếu dữ liệu tải lên.');
    const files = body.getAll('files').filter((f): f is File => f instanceof File);
    if (!files.length) return err(422, 'NO_FILES', 'Chưa chọn ảnh nào.');
    const bad = files.find((f) => !['image/jpeg', 'image/png'].includes(f.type));
    if (bad) return err(422, 'INVALID_IMAGE', `Tệp ${bad.name} không phải ảnh JPG/PNG.`);
    const id = nextGroupId++;
    const t0 = Date.now();
    const ids: number[] = [];
    files.forEach((f, i) => {
      const pid = nextPageId++;
      ids.push(pid);
      if (i === 0) addPage(makeLpPage(pid, id, i, f.name));
      else addPage(makeOtherPage(pid, id, i, f.name, URL.createObjectURL(f)));
    });
    const useRef = me.role === 'admin' && body.has('use_reference') ? body.get('use_reference') === 'true' : settings.use_reference_default;
    const title = String(body.get('title') ?? '') || null;
    const g: MockGroup = { id, title, owner_id: Number(me.id), use_reference: useRef, created_at: new Date(t0).toISOString(), created_ms: t0, duration_ms: 12000, page_ids: ids };
    groups.push(g);
    audit.unshift({ id: audit.length + 1, created_at: new Date().toISOString(), action: 'upload_create', actor_email: me.email, target_type: 'group', target_id: id });
    return ok(detail(g), 201);
  }
  if ((m = path.match(/^\/groups\/(\d+)(\/status|\/rerun)?$/))) {
    const g = groups.find((x) => x.id === Number(m?.[1]));
    if (!g || !canSee(g, me)) return err(404, 'NOT_FOUND', 'Không tìm thấy bộ chứng từ.');
    if (method === 'GET' && !m[2]) return ok(detail(g));
    if (method === 'GET' && m[2] === '/status') {
      const j = job(g);
      const sm = summary(g);
      return ok({ status: j.status, status_label_vi: sm.status_label_vi, error: sm.error ?? null, job: { ...j, status: j.status.toLowerCase() } });
    }
    if (method === 'POST' && m[2] === '/rerun') {
      g.created_ms = Date.now();
      g.duration_ms = 8000;
      return ok(detail(g));
    }
  }

  // ---- Pages ----
  if ((m = path.match(/^\/pages\/(\d+)(\/reviews|\/targets\/(\d+)\/review)?$/))) {
    const p = pages.get(m[1] ?? '');
    const g = p ? groups.find((x) => x.id === p.group_id) : undefined;
    if (!p || !g || !canSee(g, me)) return err(404, 'NOT_FOUND', 'Không tìm thấy trang.');
    if (method === 'GET' && !m[2]) {
      const { image_stage1: _a, image_original: _b, ...rest } = p;
      void _a;
      void _b;
      return ok(rest);
    }
    if (method === 'GET' && m[2] === '/reviews') return ok(reviews.filter((r) => r.page_id === String(p.id)).map(({ page_id: _p, ...r }) => (void _p, r)));
    if (method === 'POST' && m[3] !== undefined) {
      const idx = Number(m[3]);
      const tg = p.s4?.targets.find((x) => x.index === idx);
      if (!tg) return err(404, 'NOT_FOUND', 'Không tìm thấy ô ký.');
      const decision = String(b.decision ?? '') as ReviewDecision;
      if (!['SIGNED', 'NOT_SIGNED', 'UNCLEAR'].includes(decision)) return err(422, 'INVALID_DECISION', 'Quyết định duyệt không hợp lệ.');
      const note = typeof b.note === 'string' && b.note ? b.note : null;
      const created_at = new Date().toISOString();
      const decision_vi = { SIGNED: 'Có chữ ký', NOT_SIGNED: 'Không có chữ ký', UNCLEAR: 'Không rõ' }[decision];
      tg.latest_review = { target_index: idx, role: tg.role, machine_detected: tg.detected, decision, decision_vi, note, reviewer_email: me.email, created_at, stale: false };
      reviews.push({ id: reviews.length + 1, page_id: String(p.id), target_index: idx, role: tg.role, machine_detected: tg.detected, decision, decision_vi, note, reviewer_email: me.email, created_at, stale: false });
      recomputeEffective(p);
      const { image_stage1: _a, image_original: _b, ...rest } = p;
      void _a;
      void _b;
      return ok(rest);
    }
  }

  return err(404, 'NOT_FOUND', `Mock chưa hỗ trợ ${route}`);
}

export const mockTransport: Transport = {
  request: (method, path, body) => handle(method, path, body),
  async upload(path, form, onProgress) {
    let total = 0;
    for (const v of form.values()) if (v instanceof File) total += v.size;
    total = Math.max(total, 1);
    for (let i = 1; i <= 10; i++) {
      await delay(120);
      onProgress((total * i) / 10, total);
    }
    return handle('POST', path, form);
  },
  imageUrl(pageId, kind) {
    const p = pages.get(String(pageId));
    if (!p) return '';
    return kind === 'stage1' ? p.image_stage1 : p.image_original;
  },
};

