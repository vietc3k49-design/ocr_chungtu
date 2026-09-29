import { Link, Route, Routes } from 'react-router-dom';
import { GuestOnly, RequireAuth } from './auth/RequireAuth';
import { Layout } from './components/Layout';
import Account from './pages/Account';
import AdminSettingsPage from './pages/admin/Settings';
import AdminUsers from './pages/admin/Users';
import ForgotPassword from './pages/auth/ForgotPassword';
import Login from './pages/auth/Login';
import Register from './pages/auth/Register';
import ResetPassword from './pages/auth/ResetPassword';
import VerifyEmail from './pages/auth/VerifyEmail';
import GroupDetailPage from './pages/GroupDetailPage';
import GroupList from './pages/GroupList';
import PageViewer from './pages/PageViewer';
import Upload from './pages/Upload';

function NotFound() {
  return (
    <div className="page">
      <h1>Không tìm thấy trang</h1>
      <p>
        <Link to="/">← Về danh sách bộ chứng từ</Link>
      </p>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/dang-nhap" element={<GuestOnly><Login /></GuestOnly>} />
      <Route path="/dang-ky" element={<GuestOnly><Register /></GuestOnly>} />
      <Route path="/xac-thuc-email" element={<VerifyEmail />} />
      <Route path="/quen-mat-khau" element={<GuestOnly><ForgotPassword /></GuestOnly>} />
      <Route path="/dat-lai-mat-khau" element={<ResetPassword />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route path="/" element={<GroupList />} />
        <Route path="/tai-len" element={<Upload />} />
        <Route path="/bo/:id" element={<GroupDetailPage />} />
        <Route path="/trang/:id" element={<PageViewer />} />
        <Route path="/tai-khoan" element={<Account />} />
        <Route path="/quan-tri/nguoi-dung" element={<RequireAuth admin><AdminUsers /></RequireAuth>} />
        <Route path="/quan-tri/cai-dat" element={<RequireAuth admin><AdminSettingsPage /></RequireAuth>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
