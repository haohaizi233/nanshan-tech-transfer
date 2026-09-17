import HostBridge from '../host/host-bridge.js'

let timer = null
let inFlight = false

function hasNotificationSession() {
  const expiresAt = Number(HostBridge.getStorage('tt_token_expires_at')) || 0
  return HostBridge.getStorage('tt_auth_mode') === 'account' &&
    !!HostBridge.getStorage('tt_access_token') &&
    Date.now() < expiresAt
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

export function formatNotificationBadge(total) {
  const count = Number(total) || 0
  return count > 99 ? '99+' : String(count)
}

export async function refreshNotificationBadge() {
  if (!hasNotificationSession()) {
    removeNotificationBadge()
    return
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
