 // 统一 API 客户端：同源走 vite 代理（/api → 127.0.0.1:8787）
// 响应契约：{ code: 0, message, data, requestId }；非 0 一律抛错（含错误码）

import { showToast } from '../utils/toast.js'

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

// 按状态码映射友好的中文提示，避免在每个调用方重复翻译。
function friendlyMessageForStatus(status, error) {
  if (error && error.code === 'NETWORK_ERROR') return '网络连接失败'
  if (status === 401) return '登录已过期'
  if (status === 403) return '无权限执行此操作'
  if (status === 404) return '资源不存在'
  if (status === 409) return '操作冲突，请刷新重试'
  if (status === 429) return '操作过于频繁，请稍后再试'
  if (status === 500 || status === 502 || status === 503) return '服务暂时不可用，请稍后重试'
  return ''
}

// 集中错误 toast：仅对未取消的请求弹一次友好提示；调用方仍可 catch 做局部展示。
let lastToastMessage = ''
let lastToastAt = 0
function notifyError(error) {
  if (!error) return
  if (error.name === 'AbortError') return
  const message = friendlyMessageForStatus(error.status, error)
  if (!message) return
  const now = Date.now()
  if (message === lastToastMessage && now - lastToastAt < 1500) return
  lastToastMessage = message
  lastToastAt = now
  showToast(message)
}

// GET 请求去重：同 URL 的在途 GET 共享同一个 promise，避免并发重复请求。
const inflightGets = new Map()

function buildUrl(path, params) {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) {
        url.searchParams.set(k, v)
      }
    })
  }
  return url
}

export async function api(path, {
  method = 'GET',
  body,
  params,
  skipAuthRefresh,
  signal,
  guestOn401 = false,
  skipErrorToast = false,
} = {}) {
  const url = buildUrl(path, params)

  const isGet = method.toUpperCase() === 'GET'

  // GET 去重：同 URL 在途请求共享一次。
  // 仅对未传 signal 的 GET 去重，避免与 useAbortable 的取消语义冲突
  // （带 signal 的调用自行管理生命周期，不参与共享）。
  if (isGet && !signal) {
    const cacheKey = url.pathname + url.search
    const existing = inflightGets.get(cacheKey)
    if (existing) {
      return existing
    }
    const promise = doRequest(url, { method, body, skipAuthRefresh, signal, guestOn401, skipErrorToast, isGet })
      .finally(() => {
        inflightGets.delete(cacheKey)
      })
    inflightGets.set(cacheKey, promise)
    return promise
  }

  return doRequest(url, { method, body, skipAuthRefresh, signal, guestOn401, skipErrorToast, isGet })
}

async function doRequest(url, { method, body, skipAuthRefresh, signal, guestOn401, skipErrorToast, isGet }) {
  const buildHeaders = () => {
    const headers = { 'Content-Type': 'application/json' }
    const token = getToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
    return headers
  }

  const request = (headers, attemptSignal) =>
    fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: attemptSignal || signal,
    })

  let resp
  try {
    resp = await request(buildHeaders())
  } catch (err) {
    // 网络失败：GET 重试一次（非取消），其余直接抛。
    if (isGet && !(err && err.name === 'AbortError')) {
      try {
        resp = await request(buildHeaders())
      } catch (retryErr) {
        const error = new Error('网络连接失败')
        error.code = 'NETWORK_ERROR'
        error.status = 0
        if (!skipErrorToast) notifyError(error)
        throw error
      }
    } else {
      const error = new Error('网络连接失败')
      error.code = 'NETWORK_ERROR'
      error.status = 0
      if (!skipErrorToast) notifyError(error)
      throw error
    }
  }

  // access token 过期：静默续期一次并重放原请求
  if (resp.status === 401 && !skipAuthRefresh && getToken()) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      resp = await request(buildHeaders())
    } else {
      // 会话彻底失效（refresh 也无效/缺失）
      if (guestOn401) {
        // 公共列表/详情页：静默降级为游客视图，不强制跳登录。
        return null
      }
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
    if (!skipErrorToast) notifyError(error)
    throw error
  }
  return payload.data
}
