import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

// HBuilderX 工程入口在项目根：index.html → /main.js。
// uni CLI 默认 UNI_INPUT_DIR=./src，插件只改写 src/main.js（注入 mount），
// 浏览器加载的根目录 main.js 不会挂载，H5 表现为白屏。
const root = path.dirname(fileURLToPath(import.meta.url))
process.env.UNI_INPUT_DIR = root

export default defineConfig({
  base: '/h5/',
  plugins: [uni()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
  },
})
