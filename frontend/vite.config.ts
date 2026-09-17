import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        headers: { Origin: 'http://127.0.0.1:8080' },
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) =>
          /node_modules[\\/](echarts|zrender)[\\/]/.test(id)
            ? 'charts'
            : /node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)
              ? 'react'
              : undefined,
      },
    },
  },
});
