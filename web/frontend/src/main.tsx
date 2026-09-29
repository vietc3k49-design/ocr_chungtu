import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './auth/AuthContext';
import { setTransport } from './api/client';
import './styles/tokens.css';
import './styles/global.css';
import './styles/pages.css';

async function bootstrap() {
  // __MOCK__ là hằng biên dịch: bản build thường thay bằng `false` ⇒ nhánh này (và src/mocks) bị loại bỏ.
  if (__MOCK__) {
    const { mockTransport } = await import('./mocks/transport');
    setTransport(mockTransport);
    console.info('[KIDO] Đang chạy CHẾ ĐỘ MOCK — mọi dữ liệu là giả.');
  }
  const root = document.getElementById('root');
  if (!root) throw new Error('Thiếu #root');
  createRoot(root).render(
    <StrictMode>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </StrictMode>,
  );
}

void bootstrap();
