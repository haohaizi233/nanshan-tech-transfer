/**
 * API 客户端 —— 分包内唯一请求出口
 * 组装 method/path/query/body
 * 注入 Authorization、X-Request-Id
 * 解包 code!==0 → 按 error-codes.js 抛业务错误
 */

import HostBridge from '../runtime/host-bridge.js'
import {
  TT_COMMON_40102,
  TT_AUTH_40103,
} from '../constants/error-codes.js'
import {
  saveSession,
  clearSession,
  isTokenValid,
  getRefreshToken,
} from '../../../host/local-adapter.js'

let _bootstrapping = false
let _bootstrapPromise = null

async function ensureSession() {
  if (isTokenValid()) {
    return true
  }
  const refreshToken = getRefreshToken()
  if (refreshToken) {
    try {
      const res = await HostBridge.request({
        method: 'POST',
        path: '/auth/refresh',
        body: { refreshToken },
      })
      if (res.code === 0 && res.data) {
        saveSession(
          res.data.accessToken,
          res.data.refreshToken,
          res.data.expiresIn,
          res.data.user,
        )
        return true
      }
    } catch (e) {
      clearSession()
    }
  }
  return bootstrap()
}

async function bootstrap() {
  if (_bootstrapping) {
    return _bootstrapPromise
  }
  _bootstrapping = true
  _bootstrapPromise = (async () => {
    try {
      const credential = HostBridge.getIdentityCredential()
      const res = await HostBridge.request({
        method: 'POST',
        path: '/auth/bootstrap',
        body: credential,
      })
      if (res.code === 0 && res.data) {
        saveSession(
          res.data.accessToken,
          res.data.refreshToken,
          res.data.expiresIn,
          res.data.user,
        )
        return true
      }
      throw new Error('Bootstrap failed: ' + (res.message || 'unknown'))
    } catch (e) {
      clearSession()
      throw e
    } finally {
      _bootstrapping = false
      _bootstrapPromise = null
    }
  })()
  return _bootstrapPromise
}

export async function request(options) {
  const { method = 'GET', path, query, body } = options

  if (!path.startsWith('/auth/')) {
    try {
      await ensureSession()
    } catch (e) {
      if (e.code === TT_AUTH_40103) {
        throw e
      }
      throw e
    }
  }

  const res = await HostBridge.request({ method, path, query, body })

  if (res.code === 0) {
    return res.data
  }

  if (res.code === TT_COMMON_40102 && !path.startsWith('/auth/')) {
    clearSession()
    const retry = await request(options)
    return retry
  }

  const error = new Error(res.message || 'Request failed')
  error.code = res.code
  error.requestId = res.requestId
  error.details = res.details
  throw error
}

export { bootstrap, ensureSession }
