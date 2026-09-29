import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { authApi, errorMessage } from '../../api';
import { Alert } from '../../components/Alert';
import { AuthCard } from './AuthCard';
import { MIN_PASSWORD } from './Register';

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (pw.length < MIN_PASSWORD) {
      setError(`Mật khẩu phải có ít nhất ${MIN_PASSWORD} ký tự.`);
      return;
    }
    if (pw !== pw2) {
      setError('Hai mật khẩu nhập không khớp.');
      return;
    }
    setBusy(true);
    try {
      const r = await authApi.resetPassword(token, pw);
      setDone(r?.message || 'Đã đặt lại mật khẩu.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title="Đặt lại mật khẩu" footer={<Link to="/dang-nhap">Về trang đăng nhập</Link>}>
      {!token ? (
        <Alert kind="danger">Liên kết đặt lại mật khẩu thiếu mã (token).</Alert>
      ) : done ? (
        <Alert kind="info">
          {done} <Link to="/dang-nhap">Đăng nhập</Link> bằng mật khẩu mới.
        </Alert>
      ) : (
        <form className="form" onSubmit={(e) => void onSubmit(e)} noValidate>
          <label className="field">
            <span>Mật khẩu mới (tối thiểu {MIN_PASSWORD} ký tự)</span>
            <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
          </label>
          <label className="field">
            <span>Nhập lại mật khẩu mới</span>
            <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
          </label>
          {error && <Alert kind="danger">{error}</Alert>}
          <button type="submit" className="btn btn-primary btn-block" disabled={busy || !pw}>
            {busy ? 'Đang lưu…' : 'Đặt lại mật khẩu'}
          </button>
        </form>
      )}
    </AuthCard>
  );
}
