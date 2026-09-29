import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { Spinner } from '../components/Spinner';

export function RequireAuth({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { user, loading, isAdmin } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner label="Đang kiểm tra phiên đăng nhập…" block />;
  if (!user) {
    const next = location.pathname + location.search;
    return <Navigate to={`/dang-nhap?next=${encodeURIComponent(next)}`} replace />;
  }
  if (admin && !isAdmin) {
    return (
      <div className="page">
        <div className="alert alert-danger">Trang này chỉ dành cho quản trị viên.</div>
      </div>
    );
  }
  return <>{children}</>;
}

/** Trang khách (đăng nhập, đăng ký…): đã đăng nhập thì về trang chủ. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner label="Đang tải…" block />;
  if (user) return <Navigate to="/" replace />;
  return <>{children}</>;
}
