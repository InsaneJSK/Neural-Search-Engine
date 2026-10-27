import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: Object.fromEntries(['/search', '/answer', '/health'].map(path => [path, 'http://127.0.0.1:8000'])),
  },
});
