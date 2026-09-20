/**
 * API 客户端 —— 分包内唯一请求出口
 *
 * 职责边界（决策 D2/D3）：
 * - 组装 method/path/query/body + 幂等键，经 HostBridge.request 发出
 * - 鉴权注入归 Adapter：LocalAdapter 从 storage 读 tt_access_token 注入
 *   Bearer；AiNanshanAdapter 将来注入上级 Token。本层不注入 Authorization
 * - session 读写全部经 HostBridge.getStorage/setStorage（storage key 沿用
 *   tt_*，与主包存量缓存兼容；LocalAdapter 落 uni storage 行为不变）
 * - res.code===0 返回 res.data；TT_COMMON_40102/TT_AUTH_40104 刷新重试一次；
 *   其余抛 Error（含 .code/.message/.requestId/.details）
 *
 * 认证模式（tt_auth_mode）：
 * - account：手机号密码真实登录/注册（/auth/login、/auth/register）
 * - mock：本地开发匿名兜底（/auth/bootstrap），仅 dev 环境生效
 * isLoggedIn 语义：仅 account 模式视为已登录，mock 不算。
 */

import HostBridge from '../../../host/host-bridge.js'
import { TT_COMMON_40102, TT_AUTH_40104 } from '../constants/error-codes.js'

const ACCESS_TOKEN_KEY = 'tt_access_token'
const REFRESH_TOKEN_KEY = 'tt_refresh_token'
const TOKEN_EXPIRES_KEY = 'tt_token_expires_at'
const CURRENT_USER_KEY = 'tt_current_user'
const AUTH_MODE_KEY = 'tt_auth_mode'

const DEV_ENVS = ['local', 'development', 'test']

// ── session helpers（全部经 HostBridge） ──────────────────────

function getStored(key) {
  try {
    return HostBridge.getStorage(key) || null
  } catch (e) {
    return null
  }
}

function setStored(key, value) {
  try {
    HostBridge.setStorage(key, value)
  } catch (e) {
    // ignore
  }
}

function saveSession(data, mode) {
  if (!data) return
  if (data.accessToken) setStored(ACCESS_TOKEN_KEY, data.accessToken)
  if (data.refreshToken) setStored(REFRESH_TOKEN_KEY, data.refreshToken)
  if (data.expiresIn) setStored(TOKEN_EXPIRES_KEY, Date.now() + data.expiresIn * 1000)
  if (data.user) setStored(CURRENT_USER_KEY, data.user)
  if (mode) setStored(AUTH_MODE_KEY, mode)
}

function clearSession() {
  setStored(ACCESS_TOKEN_KEY, '')
  setStored(REFRESH_TOKEN_KEY, '')
  setStored(TOKEN_EXPIRES_KEY, '')
  setStored(CURRENT_USER_KEY, '')
  setStored(AUTH_MODE_KEY, '')
}

function isTokenValid() {
  const expiresAt = getStored(TOKEN_EXPIRES_KEY)
  if (!expiresAt) return false
  return Date.now() < expiresAt
}

function getRefreshToken() {
  return getStored(REFRESH_TOKEN_KEY)
}

/** 当前登录用户（仅真实账号登录；mock 匿名会话返回 null） */
export function getCurrentUser() {
  if (getStored(AUTH_MODE_KEY) !== 'account') return null
  return getStored(CURRENT_USER_KEY)
}

/** 更新当前用户缓存（资料编辑后调用） */
export function setCurrentUser(user) {
  setStored(CURRENT_USER_KEY, user || '')
}

// ── 认证流 ────────────────────────────────────────────────────

// 共享刷新 promise：并发 401 共享同一次 refresh，避免短时间内重复刷新
// （与 admin 端 client.js refreshAccessToken 同一模式）。
let _refreshing = null

async function doRefreshToken() {
	const refreshToken = getRefreshToken()
	if (!refreshToken) return null
	if (!_refreshing) {
		_refreshing = (async () => {
			try {
				const res = await HostBridge.request({
					method: 'POST',
					path: '/auth/refresh',
					body: { refreshToken },
				})
				if (res.code === 0 && res.data) {
					saveSession(res.data)
					return res.data.accessToken
				}
			} catch (e) {
				// ignore
			}
			clearSession()
			return null
		})().finally(() => {
			_refreshing = null
		})
	}
	return _refreshing
}

let _bootstrapping = false
let _bootstrapPromise = null

/** 开发环境匿名兜底：mock bootstrap（staging/production 不生效） */
async function mockBootstrap() {
  const res = await HostBridge.request({
    method: 'POST',
    path: '/auth/bootstrap',
    body: HostBridge.getIdentityCredential(),
  })
  if (res.code === 0 && res.data) {
    saveSession(res.data, 'mock')
    return true
  }
  throw new Error('Bootstrap failed: ' + (res.message || 'unknown'))
}

function getAppEnv() {
  try {
    return (HostBridge.getEnvironment().appEnv || '').toLowerCase()
  } catch (e) {
    return ''
  }
}

/**
 * 保证 storage 里有可用会话：
 * 有效 → 放行；有 refreshToken → 静默续期；
 * dev 环境 → mock bootstrap 兜底；否则抛「未登录，请先登录」
 */
async function ensureSession() {
  if (isTokenValid()) return true

  if (getRefreshToken()) {
    const token = await doRefreshToken()
    if (token) return true
  }

  if (DEV_ENVS.indexOf(getAppEnv()) >= 0) {
    if (_bootstrapping) return _bootstrapPromise
    _bootstrapping = true
    _bootstrapPromise = (async () => {
      try {
        await mockBootstrap()
        return true
      } finally {
        _bootstrapping = false
        _bootstrapPromise = null
      }
    })()
    return _bootstrapPromise
  }

  throw new Error('未登录，请先登录')
}

/**
 * 手机号注册（创建账号并直接签发会话）
 * @returns {Promise<{accessToken, refreshToken, expiresIn, user, isNewUser}>}
 */
export async function authRegister(phone, password, displayName) {
  const res = await HostBridge.request({
    method: 'POST',
    path: '/auth/register',
    body: {
      phone,
      password,
      displayName: displayName || undefined,
    },
  })
  if (res.code === 0) {
    saveSession(res.data, 'account')
    return res.data
  }
  const err = new Error(res.message || '注册失败')
  err.code = res.code
  throw err
}

/**
 * 手机号密码登录（后端按 user_credential.phone 校验）
 * @returns {Promise<{accessToken, refreshToken, expiresIn, user, isNewUser}>}
 */
export async function authLogin(phone, password) {
  const res = await HostBridge.request({
    method: 'POST',
    path: '/auth/login',
    body: { phone, password },
  })
  if (res.code === 0) {
    saveSession(res.data, 'account')
    return res.data
  }
  const err = new Error(res.message || '登录失败')
  err.code = res.code
  throw err
}

/** 退出登录（后端注销 + 清除本地缓存） */
export async function authLogout() {
  const refreshToken = getRefreshToken()
  clearSession()
  if (refreshToken) {
    try {
      await HostBridge.request({
        method: 'POST',
        path: '/auth/logout',
        body: { refreshToken },
      })
    } catch (e) {
      // 忽略网络错误，本地已清除
    }
  }
}

// ── 统一请求 ──────────────────────────────────────────────────

/**
 * 统一请求：非 /auth/* 路径先保证会话可用；POST/PATCH 自动携带
 * X-Idempotency-Key；401 类错误刷新一次后重试
 */
export async function apiRequest(method, path, query, body) {
  if (!path.startsWith('/auth/')) {
    await ensureSession()
  }

  const headers = {}
  if (method === 'POST' || method === 'PATCH') {
    headers['X-Idempotency-Key'] =
      'tt_' + Date.now() + '_' + Math.floor(Math.random() * 100000)
  }

  const res = await HostBridge.request({ method, path, query, body, headers })

  if (res.code === 0) return res.data

  if (
    (res.code === TT_COMMON_40102 || res.code === TT_AUTH_40104) &&
    !path.startsWith('/auth/')
  ) {
    const newToken = await doRefreshToken()
    if (newToken) {
      const retry = await HostBridge.request({ method, path, query, body, headers })
      if (retry.code === 0) return retry.data
    }
    clearSession()
  }

  const err = new Error(res.message || 'Request failed')
  err.code = res.code
  err.requestId = res.requestId
  err.details = res.details
  throw err
}

/**
 * 公开端点请求（如 /institutions，后端无 identity 依赖）：
 * 不做会话保证、不带幂等键，仅组包 + 解包 + 错误抛出。
 * 未登录用户也应能访问公开数据。
 */
export async function publicRequest(method, path, query, body) {
  const res = await HostBridge.request({ method, path, query, body })
  if (res.code === 0) return res.data
  const err = new Error(res.message || 'Request failed')
  err.code = res.code
  err.requestId = res.requestId
  err.details = res.details
  throw err
}

export const request = apiRequest
export { ensureSession }
