import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { authApi, errorMessage } from '../../api';
import { Alert } from '../../components/Alert';
import { Spinner } from '../../components/Spinner';
import { AuthCard } from './AuthCard';

// Token dùng một lần: gộp các lần gọi trùng (React StrictMode chạy effect 2 lần ở dev).
const inflight = new Map<string, Promise<string>>();

function verifyOnce(token: string): Promise<string> {
  let p = inflight.get(token);
  if (!p) {
    p = authApi.verifyEmail(token).then((r) => r?.message || 'Xác thực email thành công.');
    inflight.set(token, p);
  }
  return p;
}

type State = { kind: 'loading' | 'ok' | 'error'; message: string };

export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [state, setState] = useState<State>({ kind: 'loading', message: '' });

  useEffect(() => {
    if (!token) {
      setState({ kind: 'error', message: 'Liên kết xác thực thiếu mã (token).' });
      return;
    }
    let alive = true;
    verifyOnce(token).then(
      (m) => {
        if (alive) setState({ kind: 'ok', message: m });
      },
      (e: unknown) => {
        if (alive) setState({ kind: 'error', message: errorMessage(e) });
      },
    );
    return () => {
      alive = false;
    };
  }, [token]);

  return (
    <AuthCard title="Xác thực email" footer={<Link to="/dang-nhap">Đến trang đăng nhập</Link>}>
      {state.kind === 'loading' && <Spinner label="Đang xác thực email…" />}
      {state.kind === 'ok' && (
        <Alert kind="info">
          {state.message} Bạn có thể <Link to="/dang-nhap">đăng nhập</Link> ngay.
        </Alert>
      )}
      {state.kind === 'error' && (
        <>
          <Alert kind="danger">{state.message}</Alert>
          <p className="muted">
            Liên kết có thể đã hết hạn hoặc đã được dùng. Hãy thử đăng nhập — nếu email chưa xác thực, màn đăng nhập sẽ cho
            phép gửi lại thư.
          </p>
        </>
      )}
    </AuthCard>
  );
}
