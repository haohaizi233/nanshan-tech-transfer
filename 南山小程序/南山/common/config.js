/**
 * 运行环境配置（runtime-aware）
 *
 * API_BASE 解析规则（uni-app 条件编译，同一份源码适配多 Runtime）：
 *
 *  MP-WEIXIN（微信开发者工具模拟器）
 *    → http://127.0.0.1:8787（本机 FastAPI）
 *    → 真机调试时请改为电脑局域网 IP（ipconfig 查询），如 http://192.168.1.10:8787
 *
 *  H5 开发（HBuilderX 内置 dev server :5173）
 *    → http://127.0.0.1:8787（浏览器直连 FastAPI，依赖后端 CORS 白名单）
 *
 *  H5 生产（staging/production）
 *    → ''（空串 = 同源相对路径，如 https://example.com/ 下发 /api/...）
 *    → 生产部署：H5 静态资源与 FastAPI 同域，由网关（nginx/frp）把 /api 转发到 FastAPI
 *
 * USE_CAPITAL_DEMO 当前只被 common/capital.js 消费（资本对接演示开关），
 * 不影响 demand/achievement/interaction 等真实 API 模块。
 */

import { API_BASE as LOCAL_API_BASE, APP_ENV } from '../config/local.env.js'

// #ifdef H5
const PRODUCTION_ENVS = ['staging', 'production']
export const API_BASE = PRODUCTION_ENVS.includes(APP_ENV) ? '' : (LOCAL_API_BASE || 'http://127.0.0.1:8787')
// #endif

// #ifndef H5
export const API_BASE = LOCAL_API_BASE || 'http://127.0.0.1:8787'
// #endif

export const USE_CAPITAL_DEMO = false
