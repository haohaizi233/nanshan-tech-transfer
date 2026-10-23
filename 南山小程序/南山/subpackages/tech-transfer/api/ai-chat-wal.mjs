import { getPageStateScope } from './page-state-cache.mjs'

export const AI_CHAT_WAL_PREFIX = 'tt_ai_chat_wal_v1:'
export const AI_CHAT_WAL_VERSION = 1
export const AI_CHAT_WAL_MAX_BYTES = 512 * 1024

const TURN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/
const SENSITIVE_KEY = /(token|authorization|password|passwd|secret|credential)/i
const LOCAL_FILE_KEY = /(?:temp|tmp|local).*(?:path|file)|(?:path|file).*(?:temp|tmp|local)/i

function createLocalStorageAdapter() {
  if (typeof localStorage === 'undefined') return null
  return {
    getStorageSync: (key) => {
      return localStorage.getItem(key) || ''
    },
    setStorageSync: (key, value) => {
      localStorage.setItem(key, JSON.stringify(value))
    },
    removeStorageSync: (key) => {
      localStorage.removeItem(key)
    }
  }
}

function storageApi(storage) {
  // 必须同时有 get 和 set 才可用
  const hasFullStorage = (obj) => obj && typeof obj.getStorageSync === 'function' && typeof obj.setStorageSync === 'function'
  if (hasFullStorage(storage)) return storage
  if (typeof uni !== 'undefined' && hasFullStorage(uni)) return uni
  // H5降级：uni.getStorageSync不存在或是不完整时使用localStorage
  return createLocalStorageAdapter()
}

function normalizeScope(scope, storage) {
  const value = scope === undefined ? getPageStateScope(storage) : scope
  return value === null || value === undefined || value === '' ? 'anonymous' : String(value)
}

function keyFor(scope) {
  return AI_CHAT_WAL_PREFIX + encodeURIComponent(String(scope || 'anonymous'))
}

function removeQuietly(storage, key) {
  try {
    storage?.removeStorageSync?.(key)
  } catch {
    // A malformed or stale WAL must not prevent the page from opening.
  }
}

function sanitize(value, parentKey = '') {
  if (SENSITIVE_KEY.test(parentKey) || LOCAL_FILE_KEY.test(parentKey)) return undefined
  if (typeof value === 'string' && /^(?:wxfile|file):\/\/|^\/(?:tmp|temp)\//i.test(value)) return undefined
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) return value
  if (Array.isArray(value)) {
    return value.map((item) => sanitize(item)).filter((item) => item !== undefined)
  }
  if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) return undefined
  const output = {}
  for (const [key, nested] of Object.entries(value)) {
    const cleaned = sanitize(nested, key)
    if (cleaned !== undefined) output[key] = cleaned
  }
  return output
}

function readEntry(storage, scope) {
  const api = storageApi(storage)
  if (!api) return { ok: false, turn: null }
  const key = keyFor(scope)
  let entry
  try {
    entry = api.getStorageSync(key)
  } catch {
    return { ok: false, turn: null }
  }
  if (typeof entry === 'string') {
    try {
      entry = JSON.parse(entry)
    } catch {
      removeQuietly(api, key)
      return { ok: true, turn: null }
    }
  }
  if (entry === undefined || entry === null || entry === '') return { ok: true, turn: null }
  const turn = entry && entry.turn
  if (entry.version !== AI_CHAT_WAL_VERSION || entry.scope !== String(scope)
    || !turn || typeof turn !== 'object'
    || typeof turn.turnId !== 'string' || !TURN_ID_PATTERN.test(turn.turnId)
    || typeof turn.message !== 'string' || !turn.message.trim()
    || !['pending', 'succeeded', 'failed'].includes(turn.status)
    || !Number.isFinite(Number(turn.createdAt))) {
    removeQuietly(api, key)
    return { ok: true, turn: null }
  }
  return { ok: true, turn }
}

function writeEntry(storage, scope, turn) {
  const api = storageApi(storage)
  if (!api || typeof api.setStorageSync !== 'function') return false
  try {
    const entry = { version: AI_CHAT_WAL_VERSION, scope: String(scope), turn }
    const serialized = JSON.stringify(entry)
    if (!serialized || encodeURIComponent(serialized).replace(/%[0-9A-F]{2}/g, 'x').length > AI_CHAT_WAL_MAX_BYTES) return false
    api.setStorageSync(keyFor(scope), JSON.parse(serialized))
    return true
  } catch {
    return false
  }
}

/** Persist a user question before any request can leave the device. */
export function beginTurn(turn, storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const turnId = String(turn?.turnId || '')
  const message = String(turn?.message || '').trim()
  if (!TURN_ID_PATTERN.test(turnId) || !message) return false
  const existing = readEntry(storage, resolvedScope)
  if (!existing.ok) return false
  if (existing.turn && existing.turn.status === 'pending') {
    // 未确认的 pending turn 不允许被覆盖：覆盖会让恢复中的问答永久丢失，
    // 正是 WAL 要防的场景。页面侧在 typing 期间会走排队，不会走到这里。
    // 但终态（succeeded/failed）未 ack 的遗留 turn 不永久阻塞新提问：
    // 其结果本应已由恢复流程展示，允许新一轮覆盖，避免聊天功能整体卡死。
    return false
  }
  const safeTurn = {
    turnId,
    message,
    status: 'pending',
    result: null,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    reference: sanitize(turn.reference) || undefined,
    generation: Number.isSafeInteger(turn.generation) ? turn.generation : null,
    generationConfirmed: false,
  }
  return writeEntry(storage, resolvedScope, safeTurn)
}

/** Save a server-confirmed terminal result before the UI renders or acknowledges it. */
export function saveTurnResult(turnId, result, status = 'succeeded', storage, scope) {
  if (!['succeeded', 'failed'].includes(status)) return false
  const resolvedScope = normalizeScope(scope, storage)
  const existing = readEntry(storage, resolvedScope)
  if (!existing.ok || !existing.turn || existing.turn.turnId !== String(turnId)) return false
  if (existing.turn.status !== 'pending') return existing.turn.status === status
  const safeResult = sanitize(result)
  if (result !== null && result !== undefined && safeResult === undefined) return false
  return writeEntry(storage, resolvedScope, {
    ...existing.turn,
    status,
    result: safeResult === undefined ? null : safeResult,
    updatedAt: Date.now(),
  })
}

/** Return the one unacknowledged turn for the current account. */
export function loadActiveTurn(storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const entry = readEntry(storage, resolvedScope)
  return entry.ok && entry.turn ? { ...entry.turn } : null
}

export function saveTurnProgress(turnId, progress, storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const existing = readEntry(storage, resolvedScope)
  if (!existing.ok || !existing.turn || existing.turn.turnId !== String(turnId) || existing.turn.status !== 'pending') return false
  if (existing.turn.generation !== null && existing.turn.generation !== undefined && existing.turn.generation !== progress.generation) {
    if (existing.turn.generationConfirmed || existing.turn.stageSeq >= 0 || !Number.isSafeInteger(progress.generation) || progress.generation < existing.turn.generation) return false
  }
  if ((existing.turn.stageSeq ?? -1) > (progress.stageSeq ?? -1)) return false
  return writeEntry(storage, resolvedScope, {
    ...existing.turn,
    generation: progress.generation ?? existing.turn.generation,
    generationConfirmed: existing.turn.generationConfirmed || Number.isSafeInteger(progress.generation),
    stage: progress.stage,
    stageSeq: progress.stageSeq,
    updatedAt: Date.now(),
  })
}

export function acknowledgeTurn(turnId, storage, scope) {
  const api = storageApi(storage)
  if (!api || typeof api.removeStorageSync !== 'function') return false
  const resolvedScope = normalizeScope(scope, storage)
  const entry = readEntry(api, resolvedScope)
  if (!entry.ok || !entry.turn || entry.turn.turnId !== String(turnId)) return false
  try {
    api.removeStorageSync(keyFor(resolvedScope))
    return true
  } catch {
    return false
  }
}

export function clearTurns(storage, scope) {
  const api = storageApi(storage)
  if (!api || typeof api.removeStorageSync !== 'function') return false
  const resolvedScope = normalizeScope(scope, storage)
  try {
    api.removeStorageSync(keyFor(resolvedScope))
    return true
  } catch {
    return false
  }
}
