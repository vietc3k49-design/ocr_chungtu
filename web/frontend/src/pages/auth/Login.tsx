import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError, authApi, errorMessage } from '../../api';
import { useAuth } from '../../auth/AuthContext';
import { Alert } from '../../components/Alert';
import { safeNext } from '../../lib/labels';
import { AuthCard, MailpitNote } from './AuthCard';

export default function Login() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notVerified, setNotVerified] = useState(false);
  const [resendMsg, setResendMsg] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotVerified(false);
    setResendMsg(null);
    try {
      const u = await authApi.login(email.trim(), password);
      setUser(u);
      navigate(safeNext(params.get('next')), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'EMAIL_NOT_VERIFIED') setNotVerified(true);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onResend = async () => {
    setResending(true);
    try {
      const r = await authApi.resendVerification(email.trim());
      setResendMsg(r?.message || 'Nếu email tồn tại và chưa xác thực, thư xác thực mới đã được gửi.');
    } catch (err) {
      setResendMsg(errorMessage(err));
    } finally {
      setResending(false);
    }
  };

  return (
    <AuthCard
      title="Đăng nhập"
      footer={
        <>
          <Link to="/quen-mat-khau">Quên mật khẩu?</Link>
          <span>
            Chưa có tài khoản? <Link to="/dang-ky">Đăng ký</Link>
          </span>
        </>
      }
    >
      <form className="form" onSubmit={(e) => void onSubmit(e)} noValidate>
        <label className="field">
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
        </label>
        <label className="field">
          <span>Mật khẩu</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <Alert kind={notVerified ? 'warning' : 'danger'}>{error}</Alert>}
        {notVerified && (
          <div className="resend-box">
            <p>Chưa nhận được thư xác thực?</p>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={resending || !email.trim()}
              onClick={() => void onResend()}
            >
              {resending ? 'Đang gửi…' : 'Gửi lại email xác thực'}
            </button>
            {resendMsg && <p className="muted">{resendMsg}</p>}
            <MailpitNote />
          </div>
        )}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy || !email || !password}>
          {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </button>
      </form>
    </AuthCard>
  );
}
