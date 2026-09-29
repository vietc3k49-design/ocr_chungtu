import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { authApi, errorMessage } from '../../api';
import { Alert } from '../../components/Alert';
import { AuthCard, MailpitNote } from './AuthCard';

export const MIN_PASSWORD = 8;

export default function Register() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError(`Mật khẩu phải có ít nhất ${MIN_PASSWORD} ký tự.`);
      return;
    }
    if (password !== password2) {
      setError('Hai mật khẩu nhập không khớp.');
      return;
    }
    setBusy(true);
    try {
      const r = await authApi.register({ email: email.trim(), password, full_name: fullName.trim() });
      setDone(r?.message || 'Đăng ký thành công.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <AuthCard title="Kiểm tra hộp thư" footer={<Link to="/dang-nhap">Về trang đăng nhập</Link>}>
        <p>{done}</p>
        <p>
          Thư xác thực đã được gửi tới <strong>{email.trim()}</strong>. Mở thư và bấm vào liên kết để kích hoạt tài khoản
          — bạn chỉ đăng nhập được sau khi đã xác thực email.
        </p>
        <MailpitNote />
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Đăng ký tài khoản"
      footer={
        <span>
          Đã có tài khoản? <Link to="/dang-nhap">Đăng nhập</Link>
        </span>
      }
    >
      <form className="form" onSubmit={(e) => void onSubmit(e)} noValidate>
        <label className="field">
          <span>Họ và tên</span>
          <input autoComplete="name" required value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Mật khẩu (tối thiểu {MIN_PASSWORD} ký tự)</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Nhập lại mật khẩu</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            value={password2}
            onChange={(e) => setPassword2(e.target.value)}
          />
        </label>
        {error && <Alert kind="danger">{error}</Alert>}
        <button
          type="submit"
          className="btn btn-primary btn-block"
          disabled={busy || !email || !password || !fullName}
        >
          {busy ? 'Đang đăng ký…' : 'Đăng ký'}
        </button>
      </form>
    </AuthCard>
  );
}
