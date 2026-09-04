import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // base '/admin/'：构建产物由 FastAPI 托管在 /admin 下（公网走 8076 API 入口，同源免代理）
  // dev 模式 URL 相应变为 http://localhost:5273/admin/login
  base: '/admin/',
  plugins: [vue()],
  server: {
    port: 5273,
    proxy: {
      // 后端 FastAPI（127.0.0.1:8787），同源代理避免 CORS
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true
      }
    }
  }
})
