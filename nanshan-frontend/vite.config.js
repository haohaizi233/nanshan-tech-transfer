import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // base '/'：与 vue-router（createWebHistory()）一致，
  // 页面路径为 /login、/admin/*，由 FastAPI 对这些路径回 index.html（刷新不 404）
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
