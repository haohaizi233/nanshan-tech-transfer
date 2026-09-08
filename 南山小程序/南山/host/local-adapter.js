/**
 * LocalAdapter —— 本地宿主适配器
 * 实现与 AiNanshanAdapter 相同的接口，仅用于本地开发
 */

import { APP_ENV, HOST_MODE, AUTH_PROVIDER, API_BASE, API_PREFIX } from '../config/local.env.js'
import { getMockTicket } from './mock-identity.js'

const ACCESS_TOKEN_KEY = 'tt_access_token'
const REFRESH_TOKEN_KEY = 'tt_refresh_token'
const USER_KEY = 'tt_current_user'
const TOKEN_EXPIRES_KEY = 'tt_token_expires_at'
const AUTH_MODE_KEY = 'tt_auth_mode'

const PRODUCTION_ENVS = ['staging', 'production']
const TUNNEL_H5_PORT = '8077'
const TUNNEL_API_PORT = '8076'
const LOCAL_API_PORT = '8787'
const LOCALHOST_HOSTNAMES = ['localhost', '127.0.0.1', '::1', '[::1]']
const DEFAULT_LOCAL_API_BASE = 'http://127.0.0.1:8787'

/**
 * Select the API origin for an H5 page without changing its public route.
 *
 * The page's own origin decides which API it can reach — a visitor's browser
 * must never inherit the developer machine's 127.0.0.1 API address:
 *   - :8077 frp tunnel page  → paired :8076 tunnel API on the same host
 *   - LAN hostname (phone/other PC on the same WiFi) → same host, direct :8787
 *   - localhost / mini-program (no location) → localApiBase as configured
 */
export function resolveH5ApiBase({ appEnv, localApiBase, pageLocation = globalThis.location } = {}) {
  if (PRODUCTION_ENVS.includes(appEnv)) return ''

  if (pageLocation && pageLocation.hostname) {
    const protocol = pageLocation.protocol === 'https:' ? 'https:' : 'http:'
    if (String(pageLocation.port) === TUNNEL_H5_PORT) {
      return `${protocol}//${pageLocation.hostname}:${TUNNEL_API_PORT}`
    }
    if (!LOCALHOST_HOSTNAMES.includes(pageLocation.hostname)) {
      return `${protocol}//${pageLocation.hostname}:${LOCAL_API_PORT}`
    }
  }

  return localApiBase || DEFAULT_LOCAL_API_BASE
}

function effectiveApiBase() {
  return resolveH5ApiBase({ appEnv: APP_ENV, localApiBase: API_BASE })
}

function getStorageSync(key) {
  try {
    return uni.getStorageSync(key)
  } catch (e) {
    return null
  }
}

function setStorageSync(key, value) {
  try {
    uni.setStorageSync(key, value)
  } catch (e) {
    console.error('[LocalAdapter] storage write failed:', key, e)
  }
}

function removeStorageSync(key) {
  try {
    uni.removeStorageSync(key)
  } catch (e) {}
}

const LocalAdapter = {
  _getEnvironment() {
    return {
      appEnv: APP_ENV,
      hostMode: HOST_MODE,
      authProvider: AUTH_PROVIDER,
      apiBase: API_BASE,
      apiPrefix: API_PREFIX,
    }
  },

  _getIdentityCredential() {
    return {
      hostCredential: getMockTicket(),
    }
  },

  async _request(options) {
    const { method = 'GET', path, query, body, headers = {} } = options
    const env = this._getEnvironment()

    let url = effectiveApiBase() + env.apiPrefix + path
    if (query && Object.keys(query).length > 0) {
      const qs = Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
      if (qs) url += '?' + qs
    }

    const token = getStorageSync(ACCESS_TOKEN_KEY)
    if (token) {
      headers['Authorization'] = 'Bearer ' + token
    }

    const requestId = headers['X-Request-Id'] || generateRequestId()
    headers['X-Request-Id'] = requestId

    return new Promise((resolve, reject) => {
      uni.request({
        url,
        method: method.toUpperCase(),
        data: body,
        header: headers,
        timeout: 30000,
        success: (res) => {
          resolve(res.data)
        },
        fail: (err) => {
          reject(err)
        },
      })
    })
  },

  async _upload(file, options = {}) {
    return new Promise((resolve, reject) => {
      uni.uploadFile({
        url: effectiveApiBase() + API_PREFIX + '/uploads/presign',
        filePath: file,
        name: 'file',
        formData: options.formData || {},
        success: (res) => {
          const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data
          resolve(data)
        },
        fail: reject,
      })
    })
  },

  _navigate(path, params) {
    let url = '/subpackages/tech-transfer/' + path
    if (params) {
      const query = Object.entries(params)
        .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
        .join('&')
      if (query) url += '?' + query
    }
    uni.navigateTo({ url })
  },

  _showMessage(message, duration = 2000) {
    uni.showToast({ title: message, icon: 'none', duration })
  },

  _reportError(error, context = {}) {
    console.error('[LocalAdapter] error:', error, 'context:', context)
  },

  _getStorage(key) {
    return getStorageSync(key)
  },

  _setStorage(key, value) {
    setStorageSync(key, value)
  },
}

export function generateRequestId() {
  return 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9)
}

export function saveSession(accessToken, refreshToken, expiresIn, user, authMode) {
  setStorageSync(ACCESS_TOKEN_KEY, accessToken)
  setStorageSync(REFRESH_TOKEN_KEY, refreshToken)
  setStorageSync(USER_KEY, user)
  const expiresAt = Date.now() + (expiresIn || 7200) * 1000
  setStorageSync(TOKEN_EXPIRES_KEY, expiresAt)
  if (authMode) {
    setStorageSync(AUTH_MODE_KEY, authMode)
  }
}

export function clearSession() {
  removeStorageSync(ACCESS_TOKEN_KEY)
  removeStorageSync(REFRESH_TOKEN_KEY)
  removeStorageSync(USER_KEY)
  removeStorageSync(TOKEN_EXPIRES_KEY)
  removeStorageSync(AUTH_MODE_KEY)
}

export function getStoredUser() {
  return getStorageSync(USER_KEY)
}

export function isTokenValid() {
  const expiresAt = getStorageSync(TOKEN_EXPIRES_KEY)
  if (!expiresAt) return false
  return Date.now() < expiresAt
}

export function getRefreshToken() {
  return getStorageSync(REFRESH_TOKEN_KEY)
}

export default LocalAdapter
