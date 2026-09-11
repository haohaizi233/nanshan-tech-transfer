/**
 * 本地环境配置
 * 仅存在于本地工程，不合并上级
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
