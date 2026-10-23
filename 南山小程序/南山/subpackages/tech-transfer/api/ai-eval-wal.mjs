import { getPageStateScope } from './page-state-cache.mjs'

/**
 * AI 成果评估 WAL（write-ahead log）—— 提交前先落本地，切页/杀进程后可恢复。
 *
 * 与 ai-chat-wal.mjs 同模式，但记录的是「评估提交意图」：
 * 用户点「开始评估」→ beginEval 先持久化 {achievementId, taskId:null, status:'pending'}
 *   → createEvaluationTask 发出（请求中断/切页不丢意图）
 *   → 服务端确认后 saveEvalTask 落 {taskId, status:'queued'}
 *   → 任务终态后 acknowledgeEval 清除。
 * 恢复：发起页（我的成果/发布成功页）回来时 loadActiveEval → 重新发起
 * （服务端 10 分钟去重，重复提交幂等）→ saveEvalTask → 跳转详情轮询。
 */
export const AI_EVAL_WAL_PREFIX = 'tt_ai_eval_wal_v1:'
export const AI_EVAL_WAL_VERSION = 1

/** 未终态：pending=提交意图已记录但未拿到 taskId；queued/running=服务端已受理 */
export const EVAL_ACTIVE_STATUSES = ['pending', 'queued', 'running']
export const EVAL_TERMINAL_STATUSES = ['succeeded', 'failed', 'stale']
const ALL_STATUSES = [...EVAL_ACTIVE_STATUSES, ...EVAL_TERMINAL_STATUSES]

/** 无 taskId 的 pending 提交意图最长保留时间：超时允许覆盖，避免永久阻塞新评估 */
export const AI_EVAL_WAL_TTL_MS = 5 * 60 * 1000

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
  const hasFullStorage = (obj) => obj && typeof obj.getStorageSync === 'function' && typeof obj.setStorageSync === 'function'
  if (hasFullStorage(storage)) return storage
  if (typeof uni !== 'undefined' && hasFullStorage(uni)) return uni
  return createLocalStorageAdapter()
}

function normalizeScope(scope, storage) {
  const value = scope === undefined ? getPageStateScope(storage) : scope
  return value === null || value === undefined || value === '' ? 'anonymous' : String(value)
}

function keyFor(scope) {
  return AI_EVAL_WAL_PREFIX + encodeURIComponent(String(scope || 'anonymous'))
}

function removeQuietly(storage, key) {
  try {
    storage?.removeStorageSync?.(key)
  } catch {
    // A malformed or stale WAL must not prevent the page from opening.
  }
}

function isValidAchievementId(value) {
  return Number.isSafeInteger(value) && value > 0
}

function isValidTaskId(value) {
  return value === null || (Number.isSafeInteger(value) && value > 0)
}

function readEntry(storage, scope) {
  const api = storageApi(storage)
  if (!api) return { ok: false, entry: null }
  const key = keyFor(scope)
  let entry
  try {
    entry = api.getStorageSync(key)
  } catch {
    return { ok: false, entry: null }
  }
  if (typeof entry === 'string') {
    try {
      entry = JSON.parse(entry)
    } catch {
      removeQuietly(api, key)
      return { ok: true, entry: null }
    }
  }
  if (entry === undefined || entry === null || entry === '') return { ok: true, entry: null }
  const record = entry && entry.entry
  if (entry.version !== AI_EVAL_WAL_VERSION || entry.scope !== String(scope)
    || !record || typeof record !== 'object'
    || !isValidAchievementId(record.achievementId)
    || !isValidTaskId(record.taskId)
    || !ALL_STATUSES.includes(record.status)
    || !Number.isFinite(Number(record.createdAt))) {
    removeQuietly(api, key)
    return { ok: true, entry: null }
  }
  return { ok: true, entry: record }
}

function writeEntry(storage, scope, record) {
  const api = storageApi(storage)
  if (!api || typeof api.setStorageSync !== 'function') return false
  try {
    const entry = { version: AI_EVAL_WAL_VERSION, scope: String(scope), entry: record }
    const serialized = JSON.stringify(entry)
    if (!serialized || serialized.length > 16 * 1024) return false
    api.setStorageSync(keyFor(scope), JSON.parse(serialized))
    return true
  } catch {
    return false
  }
}

/**
 * 提交前记录评估意图（WAL）。返回 false 表示已有另一成果的在途评估未确认，
 * 不允许覆盖（覆盖会让恢复中的提交永久丢失）。
 * 同一成果重复 beginEval 幂等返回 true（续接既有 entry）。
 */
export function beginEval(achievementId, storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const id = Number(achievementId)
  if (!isValidAchievementId(id)) return false
  const existing = readEntry(storage, resolvedScope)
  if (!existing.ok) return false
  const record = existing.entry
  if (record && EVAL_ACTIVE_STATUSES.includes(record.status)) {
    if (record.achievementId === id) return true // 续接同一成果的在途评估
    const age = Date.now() - Number(record.createdAt)
    // 仅在途的 pending（无 taskId 且未超时）受保护；已有 taskId 的任务服务端可查、可去重，
    // 不阻塞用户对其他成果发起评估。
    if (record.status === 'pending' && record.taskId === null && age < AI_EVAL_WAL_TTL_MS) return false
  }
  const now = Date.now()
  return writeEntry(storage, resolvedScope, {
    achievementId: id,
    taskId: null,
    status: 'pending',
    createdAt: now,
    updatedAt: now,
  })
}

/** 服务端确认任务后落 taskId（pending → queued）。 */
export function saveEvalTask(achievementId, taskId, storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const id = Number(achievementId)
  const task = Number(taskId)
  if (!isValidAchievementId(id) || !isValidAchievementId(task)) return false
  const existing = readEntry(storage, resolvedScope)
  if (!existing.ok || !existing.entry || existing.entry.achievementId !== id) return false
  return writeEntry(storage, resolvedScope, {
    ...existing.entry,
    taskId: task,
    status: 'queued',
    updatedAt: Date.now(),
  })
}

/** 轮询进度回写（仅未终态）：queued / running。 */
export function saveEvalStatus(taskId, status, storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const task = Number(taskId)
  if (!isValidAchievementId(task) || !EVAL_ACTIVE_STATUSES.includes(status)) return false
  const existing = readEntry(storage, resolvedScope)
  if (!existing.ok || !existing.entry || existing.entry.taskId !== task) return false
  return writeEntry(storage, resolvedScope, {
    ...existing.entry,
    status,
    updatedAt: Date.now(),
  })
}

/** 返回当前账号唯一一条未确认的评估记录（无则 null）。 */
export function loadActiveEval(storage, scope) {
  const resolvedScope = normalizeScope(scope, storage)
  const entry = readEntry(storage, resolvedScope)
  return entry.ok && entry.entry ? { ...entry.entry } : null
}

/** 任务已终态/提交已确认：清除 WAL 记录。taskId 可选，传入时校验一致性。 */
export function acknowledgeEval(taskId, storage, scope) {
  const api = storageApi(storage)
  if (!api || typeof api.removeStorageSync !== 'function') return false
  const resolvedScope = normalizeScope(scope, storage)
  const entry = readEntry(api, resolvedScope)
  if (!entry.ok || !entry.entry) return false
  if (taskId !== undefined && taskId !== null && entry.entry.taskId !== Number(taskId)) return false
  try {
    api.removeStorageSync(keyFor(resolvedScope))
    return true
  } catch {
    return false
  }
}

export function clearEval(storage, scope) {
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
