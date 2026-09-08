/**
 * 本地环境配置
 * 仅存在于本地工程，不合并上级
 */

export const APP_ENV = 'local'
export const HOST_MODE = 'local'
export const AUTH_PROVIDER = 'mock'
// 本地开发默认：模拟器/浏览器直连本机 FastAPI
// H5 端 API 地址按页面访问来源自动配对（host/local-adapter.js resolveH5ApiBase）：
//   本地/localhost 打开 → 本值（127.0.0.1:8787）
//   公网隧道 :8077 打开 → 同主机 :8076；局域网 IP 打开 → 同主机 :8787（真机同 WiFi 免改）
// 微信小程序真机调试无页面来源可依，仍需显式改为局域网 IP 或外网 API 地址。
export const API_BASE = 'http://127.0.0.1:8787'
export const API_PREFIX = '/api/tech-transfer/v1'
