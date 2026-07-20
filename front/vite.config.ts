import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // 将 API 请求代理到后端 FastAPI 服务
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE 流式响应支持：禁用响应缓冲
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req) => {
            if (
              proxyRes.headers['content-type']?.includes('text/event-stream') ||
              req.url?.includes('/chat/query')
            ) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform';
              proxyRes.headers['x-accel-buffering'] = 'no';
            }
          });
        },
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
})
