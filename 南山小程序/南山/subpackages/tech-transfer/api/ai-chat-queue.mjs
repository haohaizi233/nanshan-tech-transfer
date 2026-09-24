/**
 * AI 对话发送队列：生成中可继续输入，本地缓存排队（切页不丢），
 * 当前回复结束后自动发出下一条；排队过多时折叠预览。
 */

export const QUEUE_STORAGE_KEY = 'tt_ai_chat_send_queue'
export const MAX_QUEUE_SIZE = 20
export const QUEUE_PREVIEW_COUNT = 2
export const CHAT_COLLAPSE_THRESHOLD = 12
export const CHAT_KEEP_TAIL = 8
export const INFLIGHT_WAIT_MS = 120000
export const INFLIGHT_POLL_MS = 2000

export function createQueueItem(text, extra = {}) {
  return {
    id: extra.id || ('q_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)),
    text: String(text || '').trim(),
    createdAt: extra.createdAt || Date.now(),
  }
}

export function normalizeQueueState(raw) {
  const src = raw && typeof raw === 'object' ? raw : {}
  const queue = Array.isArray(src.queue)
    ? src.queue
        .map((item) => createQueueItem(item && item.text, item || {}))
        .filter((item) => item.text)
        .slice(0, MAX_QUEUE_SIZE)
    : []
  return {
    version: 1,
    queue,
    inflight: String(src.inflight || '').trim(),
    draft: String(src.draft || ''),
  }
}

function storageApi(storage) {
  if (storage && typeof storage.getStorageSync === 'function') return storage
  if (typeof uni !== 'undefined' && uni && typeof uni.getStorageSync === 'function') return uni
  return null
}

export function loadQueueState(storage) {
  const api = storageApi(storage)
  if (!api) return normalizeQueueState(null)
  try {
    return normalizeQueueState(api.getStorageSync(QUEUE_STORAGE_KEY))
  } catch (e) {
    return normalizeQueueState(null)
  }
}

export function saveQueueState(state, storage) {
  const next = normalizeQueueState(state)
  const api = storageApi(storage)
  if (api && typeof api.setStorageSync === 'function') {
    api.setStorageSync(QUEUE_STORAGE_KEY, next)
  }
  return next
}

export function enqueueMessage(queue, text, max = MAX_QUEUE_SIZE) {
  const item = createQueueItem(text)
  const list = Array.isArray(queue) ? queue : []
  if (!item.text) return { queue: list, item: null, overflow: false }
  if (list.length >= max) return { queue: list, item: null, overflow: true }
  return { queue: list.concat(item), item, overflow: false }
}

export function dequeueMessage(queue) {
  const list = Array.isArray(queue) ? queue : []
  if (!list.length) return { queue: list, item: null }
  return { queue: list.slice(1), item: list[0] }
}

export function removeQueueItem(queue, id) {
  const list = Array.isArray(queue) ? queue : []
  return list.filter((item) => item.id !== id)
}

export function previewQueue(queue, expanded, previewCount = QUEUE_PREVIEW_COUNT) {
  const list = Array.isArray(queue) ? queue : []
  if (expanded || list.length <= previewCount) {
    return { visible: list, hiddenCount: 0, collapsed: false }
  }
  return {
    visible: list.slice(0, previewCount),
    hiddenCount: list.length - previewCount,
    collapsed: true,
  }
}

export function previewChatMessages(
  messages,
  expanded,
  keepTail = CHAT_KEEP_TAIL,
  threshold = CHAT_COLLAPSE_THRESHOLD,
) {
  const list = Array.isArray(messages) ? messages : []
  if (expanded || list.length <= threshold) {
    return { visible: list, hiddenCount: 0, collapsed: false }
  }
  const head = list[0] && list[0].id === 'welcome' ? [list[0]] : []
  const rest = head.length ? list.slice(1) : list
  const tail = rest.slice(-keepTail)
  const hiddenCount = list.length - head.length - tail.length
  if (hiddenCount <= 0) {
    return { visible: list, hiddenCount: 0, collapsed: false }
  }
  return { visible: head.concat(tail), hiddenCount, collapsed: true }
}

/**
 * 当前正在生成的那条用户消息，相对已加载历史处于什么状态。
 * 后端按整轮原子入库，所以通常只有 idle / done / missing。
 */
export function findInflightStatus(messages, inflightText) {
  const text = String(inflightText || '').trim()
  if (!text) return 'idle'
  const list = (messages || []).filter((m) => m && m.id !== 'welcome')
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].role === 'user' && String(list[i].content || '').trim() === text) {
      const next = list[i + 1]
      if (next && next.role === 'assistant') return 'done'
      return 'pending'
    }
  }
  return 'missing'
}
