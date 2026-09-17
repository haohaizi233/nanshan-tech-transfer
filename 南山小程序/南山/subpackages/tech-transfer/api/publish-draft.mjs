// 游客发布草稿：仅在用户主动提交而尚未登录时保存，用于登录后原路恢复。
// 存储时做一次 JSON 克隆，避免页面的响应式数组在登录跳转期间继续被修改。
const KEY = 'tech_transfer_pending_publish_draft'
const VERSION = 1

const ROUTES = {
  demand: 'pages/post-demand/post-demand',
  achievement: 'pages/post-result/post-result',
}

export function savePublishDraft(kind, form) {
  const route = ROUTES[kind]
  if (!route) return
  const snapshot = JSON.parse(JSON.stringify(form || {}))
  uni.setStorageSync(KEY, { version: VERSION, kind, form: snapshot, route, savedAt: Date.now() })
}

export function restorePublishDraft(kind) {
  const value = uni.getStorageSync(KEY)
  if (!value || value.kind !== kind || !value.form) return null
  return JSON.parse(JSON.stringify(value.form))
}

export function getPendingPublishRoute() {
  const value = uni.getStorageSync(KEY)
  return value && ROUTES[value.kind] === value.route ? value.route : null
}

export function clearPublishDraft(kind) {
  const value = uni.getStorageSync(KEY)
  if (value && (!kind || value.kind === kind)) uni.removeStorageSync(KEY)
}
