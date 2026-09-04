/**
 * 本地环境配置
 * 仅存在于本地工程，不合并上级
 */

export const APP_ENV = 'local'
export const HOST_MODE = 'local'
export const AUTH_PROVIDER = 'mock'
// 本地开发默认：模拟器/浏览器直连本机 FastAPI
// 真机调试（同一 WiFi）：改为电脑局域网 IP，如 http://192.168.2.79:8787
// 外网调试：先 python start_dev.py --tunnel 启动 frpc，再改为 http://43.138.138.200:8076
export const API_BASE = 'http://127.0.0.1:8787'
export const API_PREFIX = '/api/tech-transfer/v1'
