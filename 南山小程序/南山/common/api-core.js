/**
 * 主包 API 请求基础设施（token 管理 + 统一请求）
 *
 * 主包页面不能 require 子分包模块，因此 common/ 下的 API 模块
 * （demand-api / achievement-api / interaction-api）共用本模块，
 * 与子分包 api/client.js 共享同一套 storage key。
 *
 * 认证模式（tt_auth_mode）：
 * - account：手机号密码真实登录/注册（/auth/login、/auth/register）
 * - mock：本地开发匿名兜底（/auth/bootstrap + mock ticket），仅 dev 环境生效
 * isLoggedIn 语义：仅 account 模式视为已登录，mock 不算。
 */

import { API_BASE, APP_ENV } from './config.js'
import { getMockTicket } from '../host/mock-identity.js'

const API_PREFIX = '/api/tech-transfer/v1'
const ACCESS_TOKEN_KEY = 'tt_access_token'
const REFRESH_TOKEN_KEY = 'tt_refresh_token'
const TOKEN_EXPIRES_KEY = 'tt_token_expires_at'
const CURRENT_USER_KEY = 'tt_current_user'
const AUTH_MODE_KEY = 'tt_auth_mode'

const DEV_ENVS = ['local', 'development', 'test']

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

function saveAuthSession(data, mode) {
  if (!data) return
  if (data.accessToken) {
    uni.setStorageSync(ACCESS_TOKEN_KEY, data.accessToken)
  }
  if (data.refreshToken) {
    uni.setStorageSync(REFRESH_TOKEN_KEY, data.refreshToken)
  }
  if (data.expiresIn) {
    uni.setStorageSync(TOKEN_EXPIRES_KEY, Date.now() + data.expiresIn * 1000)
  }
  if (data.user) {
    uni.setStorageSync(CURRENT_USER_KEY, data.user)
  }
  if (mode) {
    uni.setStorageSync(AUTH_MODE_KEY, mode)
  }
}

function clearAuthSession() {
  try {
    uni.removeStorageSync(ACCESS_TOKEN_KEY)
    uni.removeStorageSync(REFRESH_TOKEN_KEY)
    uni.removeStorageSync(TOKEN_EXPIRES_KEY)
    uni.removeStorageSync(CURRENT_USER_KEY)
    uni.removeStorageSync(AUTH_MODE_KEY)
  } catch (e) {
    // ignore
  }
}

/** 当前登录用户（仅真实账号登录；mock 匿名会话返回 null） */
export function getCurrentUser() {
  try {
    if (uni.getStorageSync(AUTH_MODE_KEY) !== 'account') return null
    return uni.getStorageSync(CURRENT_USER_KEY) || null
  } catch (e) {
    return null
  }
}

/** 更新当前用户缓存（资料编辑后调用） */
export function setCurrentUser(user) {
  try {
    if (user) {
      uni.setStorageSync(CURRENT_USER_KEY, user)
    } else {
      uni.removeStorageSync(CURRENT_USER_KEY)
    }
  } catch (e) {
    // ignore
  }
}

/** 获取 refreshToken */
export function getRefreshToken() {
  try {
    return uni.getStorageSync(REFRESH_TOKEN_KEY) || null
  } catch (e) {
    return null
  }
}

async function rawRequest(method, path, query, body, header) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: buildURL(path, query),
      method: method.toUpperCase(),
      data: body,
      header: header || { 'Content-Type': 'application/json' },
      timeout: 30000,
      success: (res) => resolve(res.data),
      fail: (err) => reject(err),
    })
  })
}

/**
 * 手机号注册
 * @param {string} phone
 * @param {string} password
 * @param {string} [displayName]
 * @returns {Promise<{accessToken, refreshToken, expiresIn, user, isNewUser}>}
 */
export async function authRegister(phone, password, displayName) {
  const res = await rawRequest('POST', '/auth/register', null, {
    phone,
    password,
    displayName: displayName || undefined,
  })
  if (res.code === 0) {
    saveAuthSession(res.data, 'account')
    return res.data
  }
  const err = new Error(res.message || '注册失败')
  err.code = res.code
  throw err
}

/**
 * 账号密码登录
 * @param {string} username - 手机号
 * @param {string} password
 * @returns {Promise<{accessToken, refreshToken, expiresIn, user, isNewUser}>}
 */
export async function authLogin(username, password) {
  const res = await rawRequest('POST', '/auth/login', null, {
    username,
    password,
  })
  if (res.code === 0) {
    saveAuthSession(res.data, 'account')
    return res.data
  }
  const err = new Error(res.message || '登录失败')
  err.code = res.code
  throw err
}

/**
 * 退出登录（调用后端注销 + 清除本地缓存）
 */
export async function authLogout() {
  const refreshToken = getRefreshToken()
  clearAuthSession()
  if (refreshToken) {
    try {
      await rawRequest('POST', '/auth/logout', null, { refreshToken })
    } catch (e) {
      // 忽略网络错误，本地已清除
    }
  }
}

/**
 * 刷新 token
 */
async function doRefreshToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  try {
    const res = await rawRequest('POST', '/auth/refresh', null, { refreshToken })
    if (res.code === 0) {
      saveAuthSession(res.data)
      return res.data.accessToken
    }
  } catch (e) {
    // ignore
  }
  clearAuthSession()
  return null
}

/**
 * 开发环境匿名兜底：mock bootstrap（staging/production 不生效）
 */
async function mockBootstrap() {
  const res = await rawRequest('POST', '/auth/bootstrap', null, {
    hostCredential: getMockTicket(),
  })
  if (res.code === 0 && res.data) {
    saveAuthSession(res.data, 'mock')
    return res.data.accessToken
  }
  throw new Error('Bootstrap failed: ' + (res.message || 'unknown'))
}

async function ensureToken() {
  let token = getToken()
  if (token) return token

  // 已有 refreshToken（真实登录或 mock 会话均可）优先静默续期
  if (getRefreshToken()) {
    token = await doRefreshToken()
    if (token) return token
  }

  // 开发环境匿名兜底：mock bootstrap（含外网隧道 H5，仅按 APP_ENV 判断）
  if (DEV_ENVS.indexOf(APP_ENV) >= 0) {
    try {
      token = await mockBootstrap()
      if (token) return token
    } catch (e) {
      // 兜底失败则落到未登录
    }
  }

  throw new Error('未登录，请先登录')
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
  const res = await rawRequest(method, path, query, body, header)
  if (res.code === 0) return res.data
  // token 过期时尝试刷新一次
  if (res.code === 'TT_COMMON_40102' || res.code === 'TT_AUTH_40104') {
    const newToken = await doRefreshToken()
    if (newToken) {
      header['Authorization'] = 'Bearer ' + newToken
      const retryRes = await rawRequest(method, path, query, body, header)
      if (retryRes.code === 0) return retryRes.data
    }
    clearAuthSession()
  }
  const err = new Error(res.message || 'Request failed')
  err.code = res.code
  err.details = res.details
  throw err
}
