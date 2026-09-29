import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

export function Header() {
  const { user, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const [adminOpen, setAdminOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!adminOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setAdminOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [adminOpen]);

  const onLogout = async () => {
    await logout();
    navigate('/dang-nhap', { replace: true });
  };

  return (
    <header className="app-header">
      <div className="app-header-inner">
        <Link to="/" className="brand" aria-label="Trang chủ">
          <span className="brand-mark">KIDO</span>
          <span className="brand-sep">·</span>
          <span className="brand-name">Kiểm tra chứng từ</span>
        </Link>
        {user && (
          <nav className="main-nav" aria-label="Điều hướng chính">
            <NavLink to="/" end className="nav-link">
              Bộ chứng từ
            </NavLink>
            <NavLink to="/tai-len" className="nav-link">
              Tải lên
            </NavLink>
            {isAdmin && (
              <div className="nav-menu" ref={menuRef}>
                <button
                  type="button"
                  className="nav-link nav-menu-btn"
                  aria-haspopup="menu"
                  aria-expanded={adminOpen}
                  onClick={() => setAdminOpen((o) => !o)}
                >
                  Quản trị ▾
                </button>
                {adminOpen && (
                  <div className="nav-dropdown" role="menu">
                    <Link role="menuitem" to="/quan-tri/nguoi-dung" onClick={() => setAdminOpen(false)}>
                      Người dùng
                    </Link>
                    <Link role="menuitem" to="/quan-tri/cai-dat" onClick={() => setAdminOpen(false)}>
                      Cài đặt &amp; nhật ký
                    </Link>
                  </div>
                )}
              </div>
            )}
          </nav>
        )}
        <div className="header-right">
          {user ? (
            <>
              <Link to="/tai-khoan" className="user-chip" title={user.email}>
                <span className="user-avatar" aria-hidden="true">
                  {(user.full_name || user.email).trim().charAt(0).toUpperCase()}
                </span>
                <span className="user-name">{user.full_name || user.email}</span>
                {isAdmin && <span className="role-tag">Quản trị</span>}
              </Link>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onLogout()}>
                Đăng xuất
              </button>
            </>
          ) : (
            <Link to="/dang-nhap" className="btn btn-ghost btn-sm">
              Đăng nhập
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
