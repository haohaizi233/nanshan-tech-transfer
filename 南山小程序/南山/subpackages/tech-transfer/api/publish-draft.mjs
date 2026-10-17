import { getPageStateScope } from './page-state-cache.mjs'

// Guest drafts are intentionally transferable across the login boundary. Authenticated drafts are
// namespaced by user ID; both variants expire after one day and exclude credentials/local files.
const KEY_PREFIX = 'tech_transfer_publish_draft_v2:'
const LEGACY_KEY = 'tech_transfer_pending_publish_draft'
const GUEST_SCOPE = 'pending-login'
const VERSION = 2
const MAX_BYTES = 256 * 1024
const MAX_AGE_MS = 24 * 60 * 60 * 1000
const ROUTES = {
  demand: 'pages/post-demand/post-demand',
  achievement: 'pages/post-result/post-result',
}
const PRIVATE_KEY = /(token|authorization|password|passwd|secret|credential)/i
const LOCAL_FILE_KEY = /(?:temp|tmp|local).*(?:path|file)|(?:path|file).*(?:temp|tmp|local)/i

function storeFor(storage) {
  if (storage && typeof storage.getStorageSync === 'function') return storage
  return typeof uni !== 'undefined' && uni ? uni : null
}

function currentScope(scope, storage) {
  const resolved = scope === undefined ? getPageStateScope(storage) : scope
  return resolved && resolved !== 'anonymous' ? `user:${String(resolved)}` : GUEST_SCOPE
}

function keyFor(scope) {
  return `${KEY_PREFIX}${encodeURIComponent(scope)}`
}

function cloneSafe(value, key = '') {
  if (PRIVATE_KEY.test(key) || LOCAL_FILE_KEY.test(key)) return undefined
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
    if (typeof value === 'string' && /^(?:wxfile|file):\/\/|^\/(?:tmp|temp)\//i.test(value)) return undefined
    return value
  }
  if (Array.isArray(value)) return value.map((item) => cloneSafe(item)).filter((item) => item !== undefined)
  if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) return undefined
  const result = {}
  for (const [childKey, child] of Object.entries(value)) {
    const safe = cloneSafe(child, childKey)
    if (safe !== undefined) result[childKey] = safe
  }
  return result
}

function readEntry(store, scope, now) {
  if (!store) return null
  const key = keyFor(scope)
  try {
    let entry = store.getStorageSync(key)
    if (typeof entry === 'string') entry = JSON.parse(entry)
    if (!entry || entry.version !== VERSION || entry.scope !== scope
      || !ROUTES[entry.kind] || entry.route !== ROUTES[entry.kind]
      || !Number.isFinite(entry.savedAt) || !entry.form || typeof entry.form !== 'object') {
      store.removeStorageSync?.(key)
      return null
    }
    if (Number(now) - entry.savedAt >= MAX_AGE_MS || Number(now) < entry.savedAt) {
      store.removeStorageSync?.(key)
      return null
    }
    return entry
  } catch {
    try { store.removeStorageSync?.(key) } catch { /* storage is optional */ }
    return null
  }
}

function readLegacyGuestEntry(store, now) {
  try {
    const legacy = store?.getStorageSync?.(LEGACY_KEY)
    if (!legacy || !ROUTES[legacy.kind] || legacy.route !== ROUTES[legacy.kind]
      || !Number.isFinite(legacy.savedAt) || Number(now) - legacy.savedAt >= MAX_AGE_MS
      || Number(now) < legacy.savedAt) {
      store?.removeStorageSync?.(LEGACY_KEY)
      return null
    }
    const form = cloneSafe(legacy.form || {})
    const migrated = {
      version: VERSION,
      scope: GUEST_SCOPE,
      kind: legacy.kind,
      form,
      route: legacy.route,
      savedAt: legacy.savedAt,
    }
    store.setStorageSync(keyFor(GUEST_SCOPE), migrated)
    store.removeStorageSync(LEGACY_KEY)
    return migrated
  } catch {
    return null
  }
}

export function savePublishDraft(kind, form, { storage, now = Date.now(), scope } = {}) {
  const route = ROUTES[kind]
  const store = storeFor(storage)
  if (!route || !store || typeof store.setStorageSync !== 'function') return false
  if (!Number.isFinite(Number(now))) return false
  const draftScope = currentScope(scope, storage)
  const safeForm = cloneSafe(form || {})
  if (!safeForm || typeof safeForm !== 'object') return false
  try {
    const serialized = JSON.stringify(safeForm)
    if (serialized.length > MAX_BYTES) return false
    store.setStorageSync(keyFor(draftScope), {
      version: VERSION,
      scope: draftScope,
      kind,
      form: JSON.parse(serialized),
      route,
      savedAt: Number(now),
    })
    return true
  } catch {
    return false
  }
}

export function restorePublishDraft(kind, { storage, now = Date.now(), scope } = {}) {
  const store = storeFor(storage)
  if (!store || !ROUTES[kind]) return null
  const userScope = currentScope(scope, storage)
  const userEntry = userScope !== GUEST_SCOPE ? readEntry(store, userScope, now) : null
  let entry = userEntry
    || readEntry(store, GUEST_SCOPE, now)
    || readLegacyGuestEntry(store, now)
  if (!entry || entry.kind !== kind) return null
  if (!userEntry && userScope !== GUEST_SCOPE && entry.scope === GUEST_SCOPE) {
    const migrated = { ...entry, scope: userScope }
    try {
      store.setStorageSync(keyFor(userScope), migrated)
      store.removeStorageSync(keyFor(GUEST_SCOPE))
      entry = migrated
    } catch { /* retain guest copy if account storage cannot accept the migration */ }
  }
  return cloneSafe(entry.form) || null
}

export function getPendingPublishRoute({ storage, now = Date.now(), scope } = {}) {
  const store = storeFor(storage)
  let entry = readEntry(store, GUEST_SCOPE, now) || readLegacyGuestEntry(store, now)
  const userScope = currentScope(scope, storage)
  if (entry && userScope !== GUEST_SCOPE) {
    const migrated = { ...entry, scope: userScope }
    try {
      store.setStorageSync(keyFor(userScope), migrated)
      store.removeStorageSync(keyFor(GUEST_SCOPE))
      entry = migrated
    } catch { /* keep the guest key until the page can restore it */ }
  }
  return entry ? entry.route : null
}

export function clearPublishDraft(kind, { storage, scope } = {}) {
  const store = storeFor(storage)
  if (!store || typeof store.removeStorageSync !== 'function') return false
  const scopes = new Set([GUEST_SCOPE, currentScope(scope, storage)])
  let removed = false
  for (const itemScope of scopes) {
    const entry = readEntry(store, itemScope, Date.now())
    if (!kind || !entry || entry.kind === kind) {
      try {
        store.removeStorageSync(keyFor(itemScope))
        removed = true
      } catch { /* storage is optional */ }
    }
  }
  try {
    const legacy = store.getStorageSync(LEGACY_KEY)
    if (!kind || !legacy || legacy.kind === kind) {
      store.removeStorageSync(LEGACY_KEY)
      removed = true
    }
  } catch { /* storage is optional */ }
  return removed
}
