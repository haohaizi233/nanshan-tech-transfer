// 统一 API 客户端：同源走 vite 代理（/api → 127.0.0.1:8787）
// 响应契约：{ code: 0, message, data, requestId }；非 0 一律抛错（含错误码）

const BASE = '/api/tech-transfer/v1'
const TOKEN_KEY = 'nanshan_admin_token'
const USER_KEY = 'nanshan_admin_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getSavedUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user || {}))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export async function api(path, { method = 'GET', body, params } = {}) {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) {
        url.searchParams.set(k, v)
      }
    })
  }

  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const resp = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  })

  const payload = await resp.json().catch(() => ({}))
  if (!resp.ok || payload.code !== 0) {
    const error = new Error(payload.message || `请求失败（${resp.status}）`)
    error.code = payload.code
    error.status = resp.status
    throw error
  }
  return payload.data
}
