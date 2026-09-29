import { Outlet } from 'react-router-dom';
import { Header } from './Header';

export function Layout() {
  return (
    <div className="app-shell">
      <Header />
      <main className="app-main">
        <Outlet />
      </main>
      {__MOCK__ && <div className="mock-ribbon">CHẾ ĐỘ MOCK · dữ liệu giả</div>}
    </div>
  );
}
