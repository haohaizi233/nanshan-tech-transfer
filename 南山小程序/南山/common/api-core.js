/**
 * 主包 API 请求基础设施（token 管理 + 统一请求）
 *
 * 主包页面不能 require 子分包模块，因此 common/ 下的 API 模块
 * （demand-api / achievement-api / interaction-api）共用本模块，
 * 与子分包 api/client.js 共享同一套 storage key。
 */

import { API_BASE } from './config.js'
import { getMockTicket } from '../host/mock-identity.js'

const API_PREFIX = '/api/tech-transfer/v1'
const ACCESS_TOKEN_KEY = 'tt_access_token'
const TOKEN_EXPIRES_KEY = 'tt_token_expires_at'

export function buildURL(path, query) {
  let url = API_BASE + API_PREFIX + path
  if (query && Object.keys(query).length > 0) {
    const qs = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&')
    if (qs) url += '?' + qs
  }
  return url
}

function getToken() {
  try {
    const expiresAt = uni.getStorageSync(TOKEN_EXPIRES_KEY)
    if (!expiresAt || Date.now() >= expiresAt) return null
    return uni.getStorageSync(ACCESS_TOKEN_KEY) || null
  } catch (e) {
    return null
  }
}

async function ensureToken() {
  let token = getToken()
  if (token) return token
  const res = await new Promise((resolve, reject) => {
    uni.request({
      url: buildURL('/auth/bootstrap', null),
      method: 'POST',
      data: { hostCredential: getMockTicket() },
      header: { 'Content-Type': 'application/json' },
      timeout: 30000,
      success: (res) => resolve(res.data),
      fail: (err) => reject(err),
    })
  })
  if (res.code === 0 && res.data) {
    uni.setStorageSync(ACCESS_TOKEN_KEY, res.data.accessToken)
    uni.setStorageSync('tt_refresh_token', res.data.refreshToken)
    uni.setStorageSync('tt_current_user', res.data.user)
    uni.setStorageSync(TOKEN_EXPIRES_KEY, Date.now() + (res.data.expiresIn || 7200) * 1000)
    return res.data.accessToken
  }
  throw new Error('Bootstrap failed: ' + (res.message || 'unknown'))
}

/**
 * 统一请求：自动带 token，业务 code!==0 时抛 Error（含 .code）
 * POST/PATCH 自动携带 X-Idempotency-Key（后端幂等预留）
 */
export async function apiRequest(method, path, query, body) {
  const token = await ensureToken()
  const header = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + token,
  }
  if (method === 'POST' || method === 'PATCH') {
    header['X-Idempotency-Key'] = 'tt_' + Date.now() + '_' + Math.floor(Math.random() * 100000)
  }
  const res = await new Promise((resolve, reject) => {
    uni.request({
      url: buildURL(path, query),
      method: method.toUpperCase(),
      data: body,
      header,
      timeout: 30000,
      success: (res) => resolve(res.data),
      fail: (err) => reject(err),
    })
  })
  if (res.code === 0) return res.data
  const err = new Error(res.message || 'Request failed')
  err.code = res.code
  throw err
}
