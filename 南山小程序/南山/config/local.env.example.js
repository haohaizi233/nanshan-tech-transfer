/**
 * 本地环境配置模板（入库）
 *
 * 实际生效的是同目录的 local.env.js，该文件已被 .gitignore 忽略，只存在于本机。
 * 首次使用时复制一份即可：
 *
 *   macOS / Linux   cp config/local.env.example.js config/local.env.js
 *   Windows         Copy-Item config/local.env.example.js config/local.env.js
 *
 * 不复制也能跑：npm run dev:h5、vite 构建、start_dev.py 检测到缺失时会自动从本模板生成。
 *
 * ⚠️ 本模板是「本地开发」默认值（APP_ENV=local、AUTH_PROVIDER=mock）。
 *    要构建 staging / production 版本，请先把 local.env.js 改成真实配置，
 *    否则会把 mock 鉴权和本机地址打进产物。config/env-check.js 会在
 *    APP_ENV=staging|production 时对违规组合直接抛错，但 APP_ENV 本身
 *    若忘了改，它不会报警——这一点靠人工确认。
 */

export const APP_ENV = 'local'
export const HOST_MODE = 'local'
export const AUTH_PROVIDER = 'mock'
// 本地开发默认：H5 本机/局域网仍直连本机 FastAPI
// H5 端 API 地址按页面访问来源自动配对（config/api-origin.js resolveH5ApiBase）：
//   本地/localhost 打开 → 本值（127.0.0.1:8787）
//   Caddy :80/:443 打开（含 https://inanshan.sjhcip.com/h5/）→ 同源相对路径 /api
//   公网隧道 :8077 打开 → 同主机 :8076；局域网 IP 打开 → 同主机 :8787
// 微信小程序（开发者工具 + 扫码真机）一律走公网 HTTPS，避免真机把 127.0.0.1 当成手机自己
export const API_BASE = 'http://127.0.0.1:8787'
export const API_BASE_WEIXIN = 'https://inanshan.sjhcip.com'
export const API_PREFIX = '/api/tech-transfer/v1'
