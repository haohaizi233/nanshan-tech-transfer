import HostBridge from '../host/host-bridge.js'

let timer = null
let inFlight = false

// 主包不能引用分包资源；通知角标在 App 生命周期中执行，因此在此通过宿主桥接直接请求。
async function getNotificationSummary() {
  const res = await HostBridge.request({ method: 'GET', path: '/me/notifications/summary' })
  if (res && res.code === 0) return res.data || {}
  throw new Error((res && res.message) || '通知摘要请求失败')
}

export function formatNotificationBadge(total) {
  const count = Number(total) || 0
  return count > 99 ? '99+' : String(count)
}

export async function refreshNotificationBadge() {
  if (inFlight) return
  inFlight = true
  try {
    const data = await getNotificationSummary()
    const total = Number(data && data.total) || 0
    if (total > 0) uni.setTabBarBadge({ index: 1, text: formatNotificationBadge(total) })
    else uni.removeTabBarBadge({ index: 1 })
  } catch (e) {
    console.warn('[notification] summary refresh failed:', e)
  } finally {
    inFlight = false
  }
}

export function startNotificationPolling() {
  if (timer) return
  refreshNotificationBadge()
  timer = setInterval(refreshNotificationBadge, 200)
}

export function stopNotificationPolling() {
  if (!timer) return
  clearInterval(timer)
  timer = null
}
