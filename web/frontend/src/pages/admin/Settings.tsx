import { useCallback, useEffect, useState } from 'react';
import { adminApi, errorMessage, type AdminSettings, type AuditLog } from '../../api';
import { Alert, DEMO_REFERENCE_WARNING } from '../../components/Alert';
import { Spinner } from '../../components/Spinner';
import { formatDateTime } from '../../lib/labels';

const KNOWN_KEYS = new Set(['id', 'created_at', 'action', 'user_email', 'actor_email', 'actor_id', 'user_id', 'entity', 'entity_id', 'target_type', 'target_id']);

function auditDetail(a: AuditLog): string {
  const d = a.payload ?? a.detail ?? a.details ?? a.meta;
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(a)) {
    if (!KNOWN_KEYS.has(k) && k !== 'payload' && k !== 'detail' && k !== 'details' && k !== 'meta' && v !== null && v !== undefined) rest[k] = v;
  }
  const parts: string[] = [];
  if (d !== undefined && d !== null) parts.push(typeof d === 'string' ? d : JSON.stringify(d));
  if (Object.keys(rest).length) parts.push(JSON.stringify(rest));
  return parts.join(' ') || '—';
}

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditLog[] | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [limit, setLimit] = useState(200);

  useEffect(() => {
    adminApi.settings().then(setSettings, (e: unknown) => setError(errorMessage(e)));
  }, []);

  const loadAudit = useCallback(async () => {
    try {
      setAudit(await adminApi.audit(limit));
      setAuditError(null);
    } catch (e) {
      setAuditError(errorMessage(e));
    }
  }, [limit]);

  useEffect(() => {
    void loadAudit();
  }, [loadAudit]);

  const toggle = async (value: boolean) => {
    if (value && !window.confirm(`Bật mặc định dùng tham chiếu DEMO cho mọi bộ upload mới?\n\n${DEMO_REFERENCE_WARNING}`)) return;
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const s = await adminApi.saveSettings({ use_reference_default: value });
      setSettings(s);
      setSaved('Đã lưu cài đặt.');
      void loadAudit();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Quản trị · Cài đặt &amp; nhật ký</h1>
        </div>
      </div>

      <section className="card">
        <h2 className="card-title">Dữ liệu tham chiếu mã chuyến</h2>
        {!settings && !error && <Spinner />}
        {settings && (
          <>
            <label className="switch-row">
              <input
                type="checkbox"
                checked={settings.use_reference_default}
                disabled={saving}
                onChange={(e) => void toggle(e.target.checked)}
              />
              <span>
                <strong>Mặc định dùng dữ liệu tham chiếu mã chuyến DEMO</strong> cho bộ upload mới
                <span className="block muted small">
                  Người dùng thường không tự chọn được; quản trị viên vẫn có thể bật/tắt riêng từng lần tải lên.
                </span>
              </span>
            </label>
            <p className="warn-red">{DEMO_REFERENCE_WARNING}</p>
            <p className="small muted">
              Trạng thái hiện tại: <strong>{settings.use_reference_default ? 'ĐANG BẬT' : 'Đang tắt'}</strong>
            </p>
          </>
        )}
        {error && <Alert kind="danger">{error}</Alert>}
        {saved && <Alert kind="info">{saved}</Alert>}
      </section>

      <section className="card table-card">
        <div className="card-title-row">
          <h2 className="card-title">Nhật ký hệ thống (audit log)</h2>
          <div className="btn-row">
            <label className="small">
              Số dòng{' '}
              <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                {[50, 200, 500, 1000].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void loadAudit()}>
              Làm mới
            </button>
          </div>
        </div>
        {auditError && <Alert kind="danger">{auditError}</Alert>}
        {!audit && !auditError && <Spinner />}
        {audit && (
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Thời điểm</th>
                <th>Hành động</th>
                <th>Người thực hiện</th>
                <th>Đối tượng</th>
                <th>Chi tiết</th>
              </tr>
            </thead>
            <tbody>
              {audit.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    Chưa có bản ghi.
                  </td>
                </tr>
              )}
              {audit.map((a, i) => (
                <tr key={String(a.id ?? i)}>
                  <td className="nowrap small">{formatDateTime(a.created_at)}</td>
                  <td className="mono small">{a.action ?? '—'}</td>
                  <td className="small break">{a.actor_email ?? a.user_email ?? (a.actor_id ?? a.user_id) ?? '—'}</td>
                  <td className="mono small">
                    {(() => {
                      const kind = a.entity ?? a.target_type;
                      const eid = a.entity_id ?? a.target_id;
                      if (!kind) return '—';
                      return `${kind}${eid != null && eid !== '' ? `#${String(eid).slice(0, 8)}` : ''}`;
                    })()}
                  </td>
                  <td className="mono tiny break">{auditDetail(a)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
