// 游客发布草稿：仅在用户主动提交而尚未登录时保存，用于登录后原路恢复。
const KEY = 'tech_transfer_pending_publish_draft'

const ROUTES = {
  demand: 'pages/post-demand/post-demand',
  achievement: 'pages/post-result/post-result',
}

export function savePublishDraft(kind, form) {
  const route = ROUTES[kind]
  if (!route) return
  uni.setStorageSync(KEY, { kind, form: { ...form }, route, savedAt: Date.now() })
}

export function restorePublishDraft(kind) {
  const value = uni.getStorageSync(KEY)
  if (!value || value.kind !== kind || !value.form) return null
  return { ...value.form }
}

export function getPendingPublishRoute() {
  const value = uni.getStorageSync(KEY)
  return value && ROUTES[value.kind] === value.route ? value.route : null
}

export function clearPublishDraft(kind) {
  const value = uni.getStorageSync(KEY)
  if (value && (!kind || value.kind === kind)) uni.removeStorageSync(KEY)
}
