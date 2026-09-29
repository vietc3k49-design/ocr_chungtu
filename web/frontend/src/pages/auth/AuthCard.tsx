import type { ReactNode } from 'react';

export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">KIDO</span>
          <span className="brand-sep">·</span>
          <span className="brand-name">Kiểm tra chứng từ</span>
        </div>
        <h1 className="auth-title">{title}</h1>
        {subtitle && <p className="auth-subtitle">{subtitle}</p>}
        {children}
        {footer && <div className="auth-footer">{footer}</div>}
      </div>
    </div>
  );
}

/** Chỉ hiện ở chế độ dev (vite dev server) — bản build production không hiện. */
export function MailpitNote() {
  if (!import.meta.env.DEV) return null;
  return (
    <p className="dev-note">
      Ghi chú dev: thư được gửi tới Mailpit, xem tại{' '}
      <a href="http://localhost:8025" target="_blank" rel="noreferrer">
        http://localhost:8025
      </a>
      .
    </p>
  );
}
