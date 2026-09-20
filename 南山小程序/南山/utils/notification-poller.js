import HostBridge from '../host/host-bridge.js'

let timer = null
let inFlight = false

function getExpiresAt() {
  return Number(HostBridge.getStorage('tt_token_expires_at')) || 0
}

// 拥有 refresh token 也视为可续期的会话，让轮询继续并触发静默续期，
// 而不是在令牌刚过期时立即放弃（R2-39 / CR1 P3-7）。
function hasNotificationSession() {
  const expiresAt = getExpiresAt()
  const isAccount = HostBridge.getStorage('tt_auth_mode') === 'account'
  const accessToken = !!HostBridge.getStorage('tt_access_token')
  const refreshToken = !!HostBridge.getStorage('tt_refresh_token')
  return isAccount && accessToken && (expiresAt > Date.now() || refreshToken)
}

function clearNotificationSession() {
  ;['tt_access_token', 'tt_refresh_token', 'tt_token_expires_at', 'tt_current_user', 'tt_auth_mode']
    .forEach((key) => HostBridge.setStorage(key, ''))
}

function isUnauthorized(error) {
  return error && (error.code === 401 || error.code === 'TT_COMMON_40102' || error.code === 'TT_AUTH_40104')
}

function removeNotificationBadge() {
  uni.removeTabBarBadge({ index: 1 })
}

// 主包不能引用分包资源；通知角标在 App 生命周期中执行，因此在此通过宿主桥接直接请求。
async function getNotificationSummary() {
  const res = await HostBridge.request({ method: 'GET', path: '/me/notifications/summary' })
  if (res && res.code === 0) return res.data || {}
  const error = new Error((res && res.message) || '通知摘要请求失败')
  error.code = res && res.code
  throw error
}

// 与分包 client.js 的 doRefreshToken 同源：用 refresh token 换新会话并写回 storage，
// 让轮询与正常 API 调用共享同一套鉴权刷新路径，避免 401 静默失败（R2-39）。
async function refreshNotificationSession() {
  const refreshToken = HostBridge.getStorage('tt_refresh_token')
  if (!refreshToken) return false
  try {
    const res = await HostBridge.request({
      method: 'POST',
      path: '/auth/refresh',
      body: { refreshToken },
    })
    if (res && res.code === 0 && res.data) {
      const d = res.data
      if (d.accessToken) HostBridge.setStorage('tt_access_token', d.accessToken)
      if (d.refreshToken) HostBridge.setStorage('tt_refresh_token', d.refreshToken)
      if (d.expiresIn) HostBridge.setStorage('tt_token_expires_at', Date.now() + d.expiresIn * 1000)
      if (d.user) HostBridge.setStorage('tt_current_user', d.user)
      return true
    }
  } catch (e) {
    // ignore
  }
  return false
}

export function formatNotificationBadge(total) {
  const count = Number(total) || 0
  return count > 99 ? '99+' : String(count)
}

export async function refreshNotificationBadge() {
  if (!hasNotificationSession()) {
    removeNotificationBadge()
    return
  }
  // 令牌已过期但仍有 refresh token：先静默续期，再拉取角标，复用与正常请求一致的鉴权路径。
  if (getExpiresAt() <= Date.now()) {
    const ok = await refreshNotificationSession()
    if (!ok) {
      clearNotificationSession()
      removeNotificationBadge()
      stopNotificationPolling()
      return
    }
  }
  if (inFlight) return
  inFlight = true
  try {
    const data = await getNotificationSummary()
    const total = Number(data && data.total) || 0
    if (total > 0) uni.setTabBarBadge({ index: 1, text: formatNotificationBadge(total) })
    else removeNotificationBadge()
  } catch (e) {
    if (isUnauthorized(e)) {
      // 飞行中 401：刷新一次后重试；仍失败则清理会话并停止轮询。
      const ok = await refreshNotificationSession()
      if (ok) {
        try {
          const data = await getNotificationSummary()
          const total = Number(data && data.total) || 0
          if (total > 0) uni.setTabBarBadge({ index: 1, text: formatNotificationBadge(total) })
          else removeNotificationBadge()
          return
        } catch (e2) {
          // fall through to clear
        }
      }
      clearNotificationSession()
      removeNotificationBadge()
      stopNotificationPolling()
      return
    }
    console.warn('[notification] summary refresh failed:', e)
  } finally {
    inFlight = false
  }
}

export function startNotificationPolling() {
  if (timer) return
  if (!hasNotificationSession()) {
    removeNotificationBadge()
    return
  }
  refreshNotificationBadge()
  timer = setInterval(refreshNotificationBadge, 5000)
}

export function stopNotificationPolling() {
  if (!timer) return
  clearInterval(timer)
  timer = null
}
