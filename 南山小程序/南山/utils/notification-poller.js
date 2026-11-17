import HostBridge from '../host/host-bridge.js'
export const NOTIFICATION_POLL_INTERVAL_MS = 30_000
export const NOTIFICATION_FRESHNESS_MS = 10_000
const NOTIFICATION_BADGE_EVENT = 'notification-badge-change'
let timer = null, active = false, foreground = false, owner = '', epoch = 0, inFlight = null
let failures = 0, retryAt = 0
const cache = new Map()
function identity() {
  return hasNotificationSession() ? String(HostBridge.getStorage('tt_current_user')?.userId || HostBridge.getStorage('tt_access_token')) : ''
}
function publishNotificationBadge(total) { uni.$emit(NOTIFICATION_BADGE_EVENT, Math.max(0, Number(total) || 0)) }
function syncOwner() {
  const next = identity()
  if (next !== owner) {
    owner = next; epoch++; inFlight = null; failures = 0; retryAt = 0
    publishNotificationBadge(cache.get(owner)?.total || 0)
  }
  return owner
}
export function subscribeNotificationBadge(listener) {
  syncOwner()
  const onChange = count => listener(Math.max(0, Number(count) || 0))
  onChange(cache.get(owner)?.total || 0)
  uni.$on(NOTIFICATION_BADGE_EVENT, onChange)
  return () => uni.$off(NOTIFICATION_BADGE_EVENT, onChange)
}
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
  syncNotificationSession()
}

function isUnauthorized(error) {
  return error && (error.code === 401 || error.code === 'TT_COMMON_40102' || error.code === 'TT_AUTH_40104')
}

function removeNotificationBadge() {
  publishNotificationBadge(0)
}

// 主包不能引用分包资源；通知角标在 App 生命周期中执行，因此在此通过宿主桥接直接请求。
async function getNotificationSummary() {
  const res = await HostBridge.request({ method: 'GET', path: '/me/notifications/summary' })
  if (res && res.code === 0) return res.data || {}
  const error = new Error((res && res.message) || '通知摘要请求失败')
  error.code = res && res.code
  throw error
}


function responseData(res) {
  if (res?.code === 0) return res.data || {}
  const e = new Error(res?.message || '通知请求失败'); e.code = res?.code; throw e
}
async function refreshNotificationSession(valid) {
  if (!valid()) return false
  const refreshToken = HostBridge.getStorage('tt_refresh_token')
  if (!refreshToken) { const e = new Error('会话失效'); e.code = 401; throw e }
  const res = await HostBridge.request({method:'POST',path:'/auth/refresh',body:{refreshToken}})
  if (!valid()) return false
  const d = responseData(res)
  if (!d.accessToken) { const e = new Error('会话失效'); e.code = 401; throw e }
  HostBridge.setStorage('tt_access_token', d.accessToken)
  if (d.refreshToken) HostBridge.setStorage('tt_refresh_token', d.refreshToken)
  if (d.expiresIn) HostBridge.setStorage('tt_token_expires_at', Date.now()+d.expiresIn*1000)
  if (d.user) HostBridge.setStorage('tt_current_user', d.user)
  return true
}
export function formatNotificationBadge(total) {
  const count = Math.max(0, Number(total)||0)
  return count > 99 ? '99+' : String(count)
}
export function refreshNotificationBadge() {
  const user = syncOwner()
  if (!hasNotificationSession()) { removeNotificationBadge(); stopNotificationPolling(); return Promise.resolve() }
  if (inFlight) return inFlight
  if (Date.now() < retryAt) return Promise.resolve()
  const version = epoch
  const valid = () => version === epoch && identity() === user
  // Install the lock before renewal starts; stale responses cannot write session or badge.
  const task = Promise.resolve().then(async () => {
    if (!valid()) return
    try {
      if (getExpiresAt() <= Date.now() && !await refreshNotificationSession(valid)) return
      if (!valid()) return
      let data
      try { data = await getNotificationSummary() }
      catch (e) {
        if (!isUnauthorized(e)) throw e
        if (!valid() || !await refreshNotificationSession(valid)) return
        data = await getNotificationSummary()
      }
      if (!valid()) return
      cache.set(user,{total:Math.max(0,Number(data.total)||0),at:Date.now()})
      failures = 0; retryAt = 0; publishNotificationBadge(data.total)
    } catch (e) {
      if (!valid()) return
      if (isUnauthorized(e)) {
        cache.delete(user); clearNotificationSession(); removeNotificationBadge(); stopNotificationPolling()
      } else {
        failures = Math.min(failures+1,4)
        retryAt = Date.now()+Math.min(NOTIFICATION_POLL_INTERVAL_MS*2**failures,300_000)
        console.warn('[notification] summary refresh failed:',e)
      }
    }
  }).finally(()=>{if(inFlight===task) inFlight=null})
  inFlight=task
  return task
}
function schedule() {
  if (!active || timer !== null) return
  timer=setTimeout(async()=>{
    timer=null
    if (!active) return
    await refreshNotificationBadge()
    schedule()
  },Math.max(NOTIFICATION_POLL_INTERVAL_MS,retryAt-Date.now()))
}
export function startNotificationPolling() {
  foreground=true
  // #ifdef H5
  if (typeof document !== 'undefined' && document.hidden) return
  // #endif
  syncOwner()
  if (!hasNotificationSession()) { removeNotificationBadge(); return }
  if (active) return
  active=true
  const saved=cache.get(owner)
  if (!saved || Date.now()-saved.at>=NOTIFICATION_FRESHNESS_MS) refreshNotificationBadge().finally(schedule)
  else schedule()
}
export function stopNotificationPolling() {
  foreground=false; active=false
  if (timer!==null) clearTimeout(timer)
  timer=null
}
export function syncNotificationSession() {
  const resume=foreground
  if(owner) cache.delete(owner)
  epoch++; inFlight=null; owner=''
  publishNotificationBadge(0)
  stopNotificationPolling(); syncOwner()
  if(resume) startNotificationPolling()
}
function onVisibility() {
  // #ifdef H5
  if(document.hidden) stopNotificationPolling()
  else startNotificationPolling()
  // #endif
}
export function installNotificationVisibility() {
  // #ifdef H5
  if(typeof document!=='undefined') {
    document.removeEventListener('visibilitychange',onVisibility)
    document.addEventListener('visibilitychange',onVisibility)
  }
  // #endif
}
export function disposeNotificationVisibility() {
  // #ifdef H5
  if(typeof document!=='undefined') document.removeEventListener('visibilitychange',onVisibility)
  // #endif
  stopNotificationPolling()
}

// A successful read invalidates an older summary, then reconciles through the same request path.
export async function notificationReadSucceeded(updated) {
  const user = syncOwner(), version = ++epoch, pending = inFlight
  const saved = cache.get(user)
  if (saved) {
    saved.total = Math.max(0, saved.total - (Number(updated) || 0))
    publishNotificationBadge(saved.total)
  }
  if (pending) await pending
  if (version !== epoch || identity() !== user) return
  retryAt = 0
  await refreshNotificationBadge()
}
