import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Chế độ mock: `npm run dev:mock` (mode "mock" nạp .env.mock ⇒ VITE_MOCK=1).
// __MOCK__ là hằng số biên dịch: bản build thường có __MOCK__ = false nên
// toàn bộ src/mocks/ (kể cả ảnh mẫu) bị loại khỏi bundle.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  const mock = env.VITE_MOCK === '1';
  return {
    plugins: [react()],
    define: {
      __MOCK__: JSON.stringify(mock),
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: mock
        ? undefined
        : {
            '/api': {
              target: 'http://localhost:8000',
              changeOrigin: false,
            },
          },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  };
});
