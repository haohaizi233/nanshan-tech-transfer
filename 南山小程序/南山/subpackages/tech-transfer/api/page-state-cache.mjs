export const PAGE_STATE_TTL = Object.freeze({
  list: 2 * 60 * 1000,
  detail: 5 * 60 * 1000,
  dictionary: 30 * 60 * 1000,
  draft: 24 * 60 * 60 * 1000,
})

export const PAGE_STATE_PREFIX = 'tt_page_state_v1:'
export const PAGE_STATE_MAX_BYTES = 256 * 1024
export const PAGE_STATE_STALE_RETENTION = 7 * 24 * 60 * 60 * 1000

const VERSION = 1
const SENSITIVE_KEY = /(token|authorization|password|passwd|secret|credential)/i
const TRANSIENT_KEY = /^(loading|submitting|saving|uploading|retrying|error|loadError|timer|.*Timer|requestTask|tempFilePath|localFilePath|rawFile)$/i
const TRANSIENT_PATH_KEY = /(?:temp|tmp|local).*(?:path|file)|(?:path|file).*(?:temp|tmp|local)/i
const pendingWrites = new Map()
const pageMeta = new WeakMap()

function createLocalStorageAdapter() {
  if (typeof localStorage === 'undefined') return null
  return {
    getStorageSync: (key) => {
      try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : '' } catch { return '' }
    },
    setStorageSync: (key, value) => {
      try { localStorage.setItem(key, JSON.stringify(value)) } catch {}
    },
    removeStorageSync: (key) => {
      try { localStorage.removeItem(key) } catch {}
    },
    getStorageInfoSync: () => ({
      keys: Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(Boolean),
    }),
  }
}

function resolveStorage(storage) {
  const hasFullStorage = (obj) => obj && typeof obj.getStorageSync === 'function' && typeof obj.setStorageSync === 'function'
  if (hasFullStorage(storage)) return storage
  if (typeof uni !== 'undefined' && hasFullStorage(uni)) return uni
  return createLocalStorageAdapter()
}

function normalizeScope(scope) {
  return scope === null || scope === undefined || scope === '' ? 'anonymous' : String(scope)
}

function storageKey(key, scope) {
  return `${PAGE_STATE_PREFIX}${encodeURIComponent(normalizeScope(scope))}:${encodeURIComponent(String(key))}`
}

function ttlFor(dataClass) {
  return PAGE_STATE_TTL[dataClass] || PAGE_STATE_TTL.list
}

export function getPageStateScope(storage) {
  const store = resolveStorage(storage)
  try {
    const mode = store?.getStorageSync('tt_auth_mode')
    const user = store?.getStorageSync('tt_current_user')
    return mode === 'account' && user?.userId ? String(user.userId) : 'anonymous'
  } catch {
    return 'anonymous'
  }
}

function clonePageValue(value, key = '') {
  if (SENSITIVE_KEY.test(key) || TRANSIENT_KEY.test(key) || TRANSIENT_PATH_KEY.test(key)) return undefined
  if (typeof value === 'string' && /^(?:wxfile|file):\/\/|^\/(?:tmp|temp)\//i.test(value)) return undefined
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) return value
  if (Array.isArray(value)) return value.map(item => clonePageValue(item)).filter(item => item !== undefined)
  if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) return undefined
  const output = {}
  for (const [childKey, child] of Object.entries(value)) {
    const cloned = clonePageValue(child, childKey)
    if (cloned !== undefined) output[childKey] = cloned
  }
  return output
}

function scopedSnapshot(fields, page) {
  const output = {}
  for (const field of fields) {
    if (!Object.prototype.hasOwnProperty.call(page.$data || {}, field)) continue
    const value = clonePageValue(page[field], field)
    if (value !== undefined) output[field] = value
  }
  return output
}

function hasSensitiveKey(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return false
  seen.add(value)
  for (const [key, nested] of Object.entries(value)) {
    if (SENSITIVE_KEY.test(key) || hasSensitiveKey(nested, seen)) return true
  }
  return false
}

function removeQuietly(storage, key) {
  try {
    storage?.removeStorageSync?.(key)
  } catch {
    // A storage quota/device error should degrade to a cache miss.
  }
}

export function readPageState(key, scope, dataClass = 'list', storage, now = Date.now()) {
  const store = resolveStorage(storage)
  if (!store || !key) return null
  const cacheKey = storageKey(key, scope)
  try {
    let entry = store.getStorageSync(cacheKey)
    if (typeof entry === 'string') entry = JSON.parse(entry)
    if (!entry || entry.version !== VERSION || entry.key !== String(key)
      || entry.scope !== normalizeScope(scope) || entry.dataClass !== dataClass
      || !Number.isFinite(entry.savedAt) || !Number.isFinite(entry.expiresAt)
      || !Object.prototype.hasOwnProperty.call(entry, 'value')) {
      removeQuietly(store, cacheKey)
      return null
    }
    const hasValidatedMarker = Object.prototype.hasOwnProperty.call(entry.value || {}, '__pageCacheValidatedAt')
    const validatedAt = Number(entry.value && entry.value.__pageCacheValidatedAt)
    // 显式 marker 为 0 表示「本会话从未验证成功」（加载失败/被 invalidate 后写回）：
    // 直接当作缓存未命中丢弃，禁止用 savedAt 冒充验证时间把失败快照洗成 fresh，
    // 也禁止其保留期随每次写回无限续期。缺失 marker 的条目
    // （直连 writePageState 的调用方）仍按 savedAt 计算。
    if (hasValidatedMarker && !(Number.isFinite(validatedAt) && validatedAt > 0)) {
      removeQuietly(store, cacheKey)
      return null
    }
    const lastValidatedAt = hasValidatedMarker ? validatedAt : entry.savedAt
    const freshUntil = dataClass === 'draft'
      ? entry.expiresAt
      : Math.min(entry.expiresAt, lastValidatedAt + ttlFor(dataClass))
    const staleUntil = dataClass === 'draft'
      ? entry.expiresAt
      : lastValidatedAt + ttlFor(dataClass) + PAGE_STATE_STALE_RETENTION
    if (Number(now) >= staleUntil) {
      removeQuietly(store, cacheKey)
      return null
    }
    const fresh = Number(now) < freshUntil
    return { value: entry.value, fresh, stale: !fresh, savedAt: entry.savedAt, expiresAt: entry.expiresAt }
  } catch {
    removeQuietly(store, cacheKey)
    return null
  }
}

export function writePageState(key, scope, dataClass = 'list', value, storage, now = Date.now()) {
  const store = resolveStorage(storage)
  if (!store || !key || !Object.prototype.hasOwnProperty.call(PAGE_STATE_TTL, dataClass)) return false
  try {
    if (hasSensitiveKey(value)) return false
    const safeValue = clonePageValue(value)
    if (safeValue === undefined) return false
    const serialized = JSON.stringify(safeValue)
    if (serialized === undefined || serialized.length > PAGE_STATE_MAX_BYTES) return false
    const savedAt = Number(now)
    if (!Number.isFinite(savedAt)) return false
    const entry = {
      version: VERSION,
      key: String(key),
      scope: normalizeScope(scope),
      dataClass,
      savedAt,
      expiresAt: savedAt + PAGE_STATE_TTL[dataClass],
      value: JSON.parse(serialized),
    }
    store.setStorageSync(storageKey(key, scope), entry)
    return true
  } catch {
    return false
  }
}

function deletePageStateEntry(key, scope, store) {
  if (!store) return false
  if (key === undefined || key === null || key === '*') return clearPageStateScope(scope, store)
  cancelPendingWrite(key, scope)
  if (String(key).endsWith('*')) {
    const prefix = `${PAGE_STATE_PREFIX}${encodeURIComponent(normalizeScope(scope))}:${encodeURIComponent(String(key).slice(0, -1))}`
    try {
      for (const [id, pending] of pendingWrites) {
        if (id.startsWith(prefix)) {
          clearTimeout(pending.timer)
          pendingWrites.delete(id)
        }
      }
      for (const storageKeyValue of store.getStorageInfoSync?.().keys || []) {
        if (String(storageKeyValue).startsWith(prefix)) removeQuietly(store, storageKeyValue)
      }
      return true
    } catch {
      return false
    }
  }
  removeQuietly(store, storageKey(key, scope))
  return true
}

function cancelPendingWrite(key, scope) {
  const id = storageKey(key, scope)
  const pending = pendingWrites.get(id)
  if (!pending) return
  clearTimeout(pending.timer)
  pendingWrites.delete(id)
}

export function invalidatePageState(key, scope, storage) {
  return deletePageStateEntry(key, scope, resolveStorage(storage))
}

export function invalidatePageStateKeys(keys, scope = getPageStateScope(), storage) {
  return (Array.isArray(keys) ? keys : []).map(key => {
    const removed = invalidatePageState(key, scope, storage)
    if (key === undefined || key === null || String(key).endsWith('*')) return removed
    const variantsRemoved = invalidatePageState(`${key}:*`, scope, storage)
    return removed && variantsRemoved
  }).every(Boolean)
}

export function clearPageStateScope(scope, storage) {
  const store = resolveStorage(storage)
  if (!store || typeof store.getStorageInfoSync !== 'function') return false
  const encodedScopePrefix = `${encodeURIComponent(normalizeScope(scope))}:`
  const prefix = `${PAGE_STATE_PREFIX}${encodedScopePrefix}`
  try {
    for (const [id, pending] of pendingWrites) {
      if (id.startsWith(prefix)) {
        clearTimeout(pending.timer)
        pendingWrites.delete(id)
      }
    }
    const info = store.getStorageInfoSync()
    for (const key of info?.keys || []) {
      if (String(key).startsWith(prefix)) removeQuietly(store, key)
    }
    return true
  } catch {
    return false
  }
}

export function cancelAllPageStateWrites() {
  for (const pending of pendingWrites.values()) clearTimeout(pending.timer)
  pendingWrites.clear()
}

export function schedulePageStateWrite(key, scope, dataClass, value, delay = 250, storage) {
  const id = storageKey(key, scope)
  const store = resolveStorage(storage)
  if (!store) return false
  const snapshot = clonePageValue(value)
  if (snapshot === undefined) return false
  const previous = pendingWrites.get(id)
  if (previous) clearTimeout(previous.timer)
  const timer = setTimeout(() => {
    pendingWrites.delete(id)
    writePageState(key, scope, dataClass, snapshot, store)
  }, Math.max(0, Number(delay) || 0))
  pendingWrites.set(id, { timer, key, scope, dataClass, value: snapshot, storage: store })
  return true
}

export function flushPageStateWrite(key, scope, dataClass, value, storage) {
  const id = storageKey(key, scope)
  const pending = pendingWrites.get(id)
  if (pending) {
    clearTimeout(pending.timer)
    pendingWrites.delete(id)
    const snapshot = clonePageValue(value)
    return writePageState(key, scope, dataClass, snapshot === undefined ? pending.value : snapshot, pending.storage)
  }
  return writePageState(key, scope, dataClass, clonePageValue(value), storage)
}

export function createPageStateMixin({ route, groups = [], cacheKey, scope = getPageStateScope, storage } = {}) {
  const groupList = groups.map(group => ({ name: group.name || 'default', dataClass: group.dataClass || 'list', fields: group.fields || [] }))
  const watch = {}
  for (const group of groupList.filter(item => item.dataClass === 'draft')) {
    for (const field of group.fields) {
      watch[field] = {
        deep: true,
        handler() {
          const meta = pageMeta.get(this)
          if (!meta) return
          schedulePageStateWrite(meta.keys[group.name], meta.scope, group.dataClass,
            scopedSnapshot(group.fields, this), 250, storage)
        },
      }
    }
  }

  function initialize(page, options = {}, preserveDefaults = false) {
    let meta = pageMeta.get(page)
    if (!meta || !preserveDefaults) {
      meta = { defaults: {}, keys: {}, freshUntil: {}, validatedAt: {}, restored: {}, skipPersist: {}, scrollTop: 0, scope: scope(storage) }
      groupList.forEach(group => {
        meta.defaults[group.name] = scopedSnapshot(group.fields, page)
        const suffix = Object.keys(options || {}).filter(key => !SENSITIVE_KEY.test(key)).sort()
          .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(String(options[key]))}`).join('&')
        meta.keys[group.name] = `${typeof cacheKey === 'function' ? cacheKey(options, page) : (cacheKey || route || 'page')}:${group.name}${suffix ? `:${suffix}` : ''}`
      })
      pageMeta.set(page, meta)
    }
    const currentScope = scope(storage)
    if (meta.scope !== currentScope) {
      let freshDefaults = null
      try {
        freshDefaults = typeof page.$options?.data === 'function' ? page.$options.data.call(page) : null
      } catch {
        freshDefaults = null
      }
      groupList.forEach(group => {
        const source = freshDefaults && typeof freshDefaults === 'object' ? freshDefaults : meta.defaults[group.name]
        const defaults = {}
        for (const field of group.fields) {
          if (source && Object.prototype.hasOwnProperty.call(source, field)) defaults[field] = source[field]
        }
        Object.assign(page, defaults)
        meta.defaults[group.name] = scopedSnapshot(group.fields, page)
      })
      meta.scope = currentScope
      meta.skipPersist = {}
      meta.scrollTop = 0
    }
    groupList.forEach(group => {
      const cached = readPageState(meta.keys[group.name], meta.scope, group.dataClass, storage)
      if (!cached) {
        meta.freshUntil[group.name] = 0
        meta.validatedAt[group.name] = 0
        meta.restored[group.name] = false
        return
      }
      const value = { ...cached.value }
      const validatedAt = Number(Object.prototype.hasOwnProperty.call(value, '__pageCacheValidatedAt')
        ? value.__pageCacheValidatedAt
        : cached.savedAt)
      meta.scrollTop = Number(value.__pageScrollTop) || meta.scrollTop
      delete value.__pageCacheValidatedAt
      delete value.__pageScrollTop
      Object.assign(page, value)
      meta.restored[group.name] = true
      meta.validatedAt[group.name] = validatedAt
      meta.freshUntil[group.name] = group.dataClass === 'draft'
        ? cached.expiresAt
        : Math.min(cached.expiresAt, validatedAt + ttlFor(group.dataClass))
    })
    if (meta.scrollTop > 0 && typeof uni !== 'undefined' && uni.pageScrollTo) {
      setTimeout(() => uni.pageScrollTo({ scrollTop: meta.scrollTop, duration: 0 }), 0)
    }
  }

  function persist(page, group, forceFresh) {
    const meta = pageMeta.get(page)
    if (!meta) return
    if (meta.skipPersist[group.name]) return
    if (scope(storage) !== meta.scope) {
      groupList.forEach(item => cancelPendingWrite(meta.keys[item.name], meta.scope))
      return
    }
    const payload = scopedSnapshot(group.fields, page)
    payload.__pageScrollTop = meta.scrollTop
    if (group.dataClass !== 'draft') payload.__pageCacheValidatedAt = meta.validatedAt[group.name] || 0
    flushPageStateWrite(meta.keys[group.name], meta.scope, group.dataClass, payload, storage)
    if (forceFresh || group.dataClass === 'draft') meta.freshUntil[group.name] = Date.now() + ttlFor(group.dataClass)
  }

  return {
    watch,
    onLoad(options) { initialize(this, options) },
    onShow() { initialize(this, {}, true) },
    onHide() { groupList.forEach(group => persist(this, group, false)) },
    onUnload() {
      groupList.forEach(group => persist(this, group, false))
      pageMeta.delete(this)
    },
    onPageScroll(event) {
      const meta = pageMeta.get(this)
      if (meta) meta.scrollTop = Number(event?.scrollTop) || 0
    },
    methods: {
      shouldRevalidatePageState(name, force = false) {
        if (force) return true
        const meta = pageMeta.get(this)
        return !meta || Date.now() >= (meta.freshUntil[name] || 0)
      },
      markPageStateFresh(name) {
        const meta = pageMeta.get(this)
        const group = groupList.find(item => item.name === name)
        if (meta && group) {
          const now = Date.now()
          meta.validatedAt[name] = now
          meta.freshUntil[name] = now + ttlFor(group.dataClass)
        }
      },
      invalidatePageState(name) {
        const meta = pageMeta.get(this)
        if (!meta) return false
        const group = groupList.find(item => item.name === name)
        if (!group) return false
        meta.freshUntil[name] = 0
        // 重置验证时间：否则 persist 会把旧验证 marker 盖到已变化的内存数据上，
        // 让「清空/失败」的快照被洗成已验证条目。
        meta.validatedAt[name] = 0
        return deletePageStateEntry(meta.keys[name], meta.scope, resolveStorage(storage))
      },
      clearPageState(name) {
        const meta = pageMeta.get(this)
        if (!meta || !groupList.some(item => item.name === name)) return false
        meta.skipPersist[name] = true
        meta.freshUntil[name] = 0
        meta.validatedAt[name] = 0
        return deletePageStateEntry(meta.keys[name], meta.scope, resolveStorage(storage))
      },
      hasRestoredPageState(name) {
        const meta = pageMeta.get(this)
        return Boolean(meta?.restored[name])
      },
    },
  }
}
