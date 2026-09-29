import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { ApiError, adminApi, errorMessage, type AdminUserOut } from '../../api';
import { useAuth } from '../../auth/AuthContext';
import { Alert } from '../../components/Alert';
import { Badge } from '../../components/Badge';
import { Spinner } from '../../components/Spinner';
import { formatDateTime } from '../../lib/labels';

export default function AdminUsers() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<AdminUserOut[] | null>(null);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await adminApi.users(query || undefined));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    setQuery(q.trim());
  };

  const patch = async (u: AdminUserOut, body: { role?: string; is_active?: boolean }, confirmText: string) => {
    if (!window.confirm(confirmText)) return;
    setBusyId(String(u.id));
    setActionError(null);
    try {
      const updated = await adminApi.updateUser(u.id, body);
      setUsers((list) => (list ?? []).map((x) => (String(x.id) === String(u.id) ? { ...x, ...updated } : x)));
    } catch (e) {
      const msg = errorMessage(e);
      setActionError(e instanceof ApiError && e.code === 'LAST_ADMIN' ? `${msg}` : msg);
    } finally {
      setBusyId(null);
    }
  };

  const unlockLogin = async (u: AdminUserOut) => {
    if (!window.confirm(`Gỡ tạm khóa đăng nhập cho ${u.email}? Bộ đếm số lần nhập sai sẽ về 0.`)) return;
    setBusyId(String(u.id));
    setActionError(null);
    try {
      const updated = await adminApi.unlockLogin(u.id);
      setUsers((list) => (list ?? []).map((x) => (String(x.id) === String(u.id) ? { ...x, ...updated } : x)));
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Quản trị · Người dùng</h1>
          <p className="muted">
            Đổi vai trò, khóa hoặc mở khóa tài khoản. Hệ thống luôn giữ ít nhất một quản trị viên đang hoạt động. Tài khoản nhập sai
            mật khẩu quá nhiều lần sẽ bị <b>tạm khóa đăng nhập</b> (tự hết hạn, hoặc gỡ ở cột “Đăng nhập sai”).
          </p>
        </div>
        <form className="search" onSubmit={onSearch}>
          <input placeholder="Tìm theo email hoặc tên" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="submit" className="btn btn-secondary">
            Tìm
          </button>
        </form>
      </div>
      {error && <Alert kind="danger">{error}</Alert>}
      {actionError && <Alert kind="danger">{actionError}</Alert>}
      {!users && !error && <Spinner block />}
      {users && (
        <div className="card table-card">
          <table className="table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Họ tên</th>
                <th>Vai trò</th>
                <th>Xác thực email</th>
                <th>Hoạt động</th>
                <th>Đăng nhập cuối</th>
                <th>Đăng nhập sai</th>
                <th>Tạo lúc</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && (
                <tr>
                  <td colSpan={9} className="muted">
                    Không có người dùng phù hợp.
                  </td>
                </tr>
              )}
              {users.map((u) => {
                const self = me && String(me.id) === String(u.id);
                const busy = busyId === String(u.id);
                const isAdminRole = u.role === 'admin';
                return (
                  <tr key={u.id}>
                    <td className="break">
                      {u.email} {self && <span className="tiny muted">(bạn)</span>}
                    </td>
                    <td>{u.full_name || '—'}</td>
                    <td>{isAdminRole ? <Badge tone="info">Quản trị</Badge> : <Badge tone="neutral">Người dùng</Badge>}</td>
                    <td>{u.email_verified ? 'Đã xác thực' : <Badge tone="warning">Chưa xác thực</Badge>}</td>
                    <td>{u.is_active ? 'Đang hoạt động' : <Badge tone="danger">Đã khóa</Badge>}</td>
                    <td className="nowrap">{formatDateTime(u.last_login_at)}</td>
                    <td>
                      {u.login_locked ? (
                        <div className="stack-xs">
                          <Badge tone="danger">Tạm khóa đến {formatDateTime(u.login_locked_until ?? null)}</Badge>
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            disabled={busy}
                            onClick={() => void unlockLogin(u)}
                          >
                            Gỡ tạm khóa đăng nhập
                          </button>
                        </div>
                      ) : u.login_recent_fails ? (
                        <span className="tiny muted">{u.login_recent_fails} lần sai gần đây</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="nowrap">{formatDateTime(u.created_at)}</td>
                    <td>
                      <div className="btn-row">
                        <button
                          type="button"
                          className="btn btn-sm btn-secondary"
                          disabled={busy || Boolean(self)}
                          title={self ? 'Không thể tự đổi vai trò của chính mình' : undefined}
                          onClick={() =>
                            void patch(
                              u,
                              { role: isAdminRole ? 'user' : 'admin' },
                              isAdminRole ? `Hạ quyền ${u.email} xuống người dùng thường?` : `Cấp quyền quản trị cho ${u.email}?`,
                            )
                          }
                        >
                          {isAdminRole ? 'Hạ quyền' : 'Cấp quyền quản trị'}
                        </button>
                        <button
                          type="button"
                          className={`btn btn-sm ${u.is_active ? 'btn-danger-outline' : 'btn-secondary'}`}
                          disabled={busy || Boolean(self)}
                          title={self ? 'Không thể tự khóa chính mình' : undefined}
                          onClick={() =>
                            void patch(u, { is_active: !u.is_active }, u.is_active ? `Khóa tài khoản ${u.email}?` : `Mở khóa tài khoản ${u.email}?`)
                          }
                        >
                          {u.is_active ? 'Khóa' : 'Mở khóa'}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
