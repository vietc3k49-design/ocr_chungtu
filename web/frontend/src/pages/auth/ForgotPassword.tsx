import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { authApi, errorMessage } from '../../api';
import { Alert } from '../../components/Alert';
import { AuthCard, MailpitNote } from './AuthCard';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await authApi.forgotPassword(email.trim());
      setMsg(r?.message || 'Nếu email tồn tại, thư hướng dẫn đặt lại mật khẩu đã được gửi.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard
      title="Quên mật khẩu"
      subtitle="Nhập email tài khoản, hệ thống sẽ gửi liên kết đặt lại mật khẩu."
      footer={<Link to="/dang-nhap">Về trang đăng nhập</Link>}
    >
      {msg ? (
        <>
          <Alert kind="info">{msg}</Alert>
          <MailpitNote />
        </>
      ) : (
        <form className="form" onSubmit={(e) => void onSubmit(e)} noValidate>
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
          </label>
          {error && <Alert kind="danger">{error}</Alert>}
          <button type="submit" className="btn btn-primary btn-block" disabled={busy || !email}>
            {busy ? 'Đang gửi…' : 'Gửi liên kết đặt lại'}
          </button>
        </form>
      )}
    </AuthCard>
  );
}
