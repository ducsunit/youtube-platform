import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxy: mọi /api/* chuyển thẳng sang API server backend
// (python -m youtube_pipeline api-server, mặc định 127.0.0.1:8787).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
      },
    },
  },
});
