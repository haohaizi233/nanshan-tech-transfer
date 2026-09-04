 // 统一 API 客户端：同源走 vite 代理（/api → 127.0.0.1:8787）
// 响应契约：{ code: 0, message, data, requestId }；非 0 一律抛错（含错误码）

const BASE = '/api/tech-transfer/v1'
const TOKEN_KEY = 'nanshan_admin_token'
const USER_KEY = 'nanshan_admin_user'
const REFRESH_KEY = 'nanshan_admin_refresh_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY) || ''
}

export function getSavedUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function saveSession(token, user, refreshToken) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user || {}))
  if (refreshToken) {
    localStorage.setItem(REFRESH_KEY, refreshToken)
  } else {
    localStorage.removeItem(REFRESH_KEY)
  }
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

let refreshing = null

// 用 refreshToken 换新的 access/refresh token（并发 401 共享同一次刷新）
async function refreshAccessToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    return null
  }
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const resp = await fetch(`${BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refreshToken })
        })
        const payload = await resp.json().catch(() => ({}))
        if (!resp.ok || payload.code !== 0) {
          return null
        }
        localStorage.setItem(TOKEN_KEY, payload.data.accessToken)
        localStorage.setItem(REFRESH_KEY, payload.data.refreshToken)
        return payload.data.accessToken
      } catch {
        return null
      }
    })().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

export async function api(path, { method = 'GET', body, params, skipAuthRefresh } = {}) {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) {
        url.searchParams.set(k, v)
      }
    })
  }

  const buildHeaders = () => {
    const headers = { 'Content-Type': 'application/json' }
    const token = getToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
    return headers
  }

  const request = (headers) =>
    fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    })

  let resp = await request(buildHeaders())

  // access token 过期：静默续期一次并重放原请求
  if (resp.status === 401 && !skipAuthRefresh && getToken()) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      resp = await request(buildHeaders())
    } else {
      // 会话彻底失效（refresh 也无效/缺失）：清空并回登录页重新认证
      clearSession()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
    }
  }

  const payload = await resp.json().catch(() => ({}))
  if (!resp.ok || payload.code !== 0) {
    const error = new Error(payload.message || `请求失败（${resp.status}）`)
    error.code = payload.code
    error.status = resp.status
    throw error
  }
  return payload.data
}
