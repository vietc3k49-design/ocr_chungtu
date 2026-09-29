import { useState, type FormEvent } from 'react';
import { authApi, errorMessage } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Alert } from '../components/Alert';
import { formatDateTime } from '../lib/labels';
import { MIN_PASSWORD } from './auth/Register';

export default function Account() {
  const { user } = useAuth();
  const [oldPw, setOldPw] = useState('');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMsg(null);
    if (pw.length < MIN_PASSWORD) {
      setError(`Mật khẩu mới phải có ít nhất ${MIN_PASSWORD} ký tự.`);
      return;
    }
    if (pw !== pw2) {
      setError('Hai mật khẩu mới không khớp.');
      return;
    }
    setBusy(true);
    try {
      const r = await authApi.changePassword(oldPw, pw);
      setMsg(r?.message || 'Đã đổi mật khẩu.');
      setOldPw('');
      setPw('');
      setPw2('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!user) return null;
  return (
    <div className="page page-narrow">
      <h1>Tài khoản</h1>
      <section className="card">
        <h2 className="card-title">Thông tin</h2>
        <dl className="kv">
          <div className="kv-row">
            <dt>Họ tên</dt>
            <dd>{user.full_name || '—'}</dd>
          </div>
          <div className="kv-row">
            <dt>Email</dt>
            <dd>{user.email}</dd>
          </div>
          <div className="kv-row">
            <dt>Vai trò</dt>
            <dd>{user.role === 'admin' ? 'Quản trị viên' : 'Người dùng'}</dd>
          </div>
          <div className="kv-row">
            <dt>Tạo lúc</dt>
            <dd>{formatDateTime(user.created_at)}</dd>
          </div>
        </dl>
      </section>
      <section className="card">
        <h2 className="card-title">Đổi mật khẩu</h2>
        <form className="form" onSubmit={(e) => void onSubmit(e)} noValidate>
          <label className="field">
            <span>Mật khẩu hiện tại</span>
            <input type="password" autoComplete="current-password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} />
          </label>
          <label className="field">
            <span>Mật khẩu mới (tối thiểu {MIN_PASSWORD} ký tự)</span>
            <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
          </label>
          <label className="field">
            <span>Nhập lại mật khẩu mới</span>
            <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
          </label>
          {error && <Alert kind="danger">{error}</Alert>}
          {msg && <Alert kind="info">{msg}</Alert>}
          <button type="submit" className="btn btn-primary" disabled={busy || !oldPw || !pw}>
            {busy ? 'Đang lưu…' : 'Đổi mật khẩu'}
          </button>
        </form>
      </section>
    </div>
  );
}
