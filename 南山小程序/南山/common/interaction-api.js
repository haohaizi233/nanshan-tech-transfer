/**
 * 交互域 API：收藏 + 对接意向（基于真实后端）
 *
 * 后端契约：openapi.yaml paths /favorites/{targetType}/{targetId}、
 * /me/favorites、/cooperations、/me/cooperations
 * 前端 type（demand | result）与后端 targetType（demand | achievement）在此做映射。
 */

import { apiRequest } from './api-core.js'

/** 前端 type → 后端 targetType */
export function toTargetType(type) {
  return type === 'result' ? 'achievement' : 'demand'
}

/** 后端 targetType → 前端 type */
export function toFeType(targetType) {
  return targetType === 'achievement' ? 'result' : 'demand'
}

function toTargetId(id) {
  const n = parseInt(id, 10)
  if (isNaN(n)) throw new Error('目标 ID 无效')
  return n
}

// ── 收藏 ─────────────────────────────────────────────────────

export async function addFavorite(type, id) {
  return apiRequest('PUT', `/favorites/${toTargetType(type)}/${toTargetId(id)}`)
}

export async function removeFavorite(type, id) {
  return apiRequest('DELETE', `/favorites/${toTargetType(type)}/${toTargetId(id)}`)
}

/** 我的收藏列表（type 为前端 type；返回 { total, list }，内嵌 targetSummary） */
export async function getMyFavorites(type, params = {}) {
  const { page = 1, pageSize = 10 } = params
  return apiRequest('GET', '/me/favorites', {
    targetType: toTargetType(type),
    page,
    pageSize,
  })
}

/** 当前用户对某类目标的收藏 ID 集合（String 形式，便于与页面 id 比对） */
export async function getFavoriteIdSet(type) {
  const data = await getMyFavorites(type, { page: 1, pageSize: 50 })
  const set = new Set()
  ;(data.list || []).forEach((item) => set.add(String(item.targetId)))
  return set
}

// ── 对接意向 ─────────────────────────────────────────────────

/**
 * 合作意向选项：由用户每次发起对接时选择，与账号主体类型/合作方向画像解耦。
 * 枚举与后端 modules/cooperation/service.py 的 INTENT_TYPES 保持一致。
 */
export const INTENT_TYPE_OPTIONS = {
  demand: [
    { value: 'provide_solution', label: '提供技术方案' },
    { value: 'provide_achievement', label: '提供现有成果' },
    { value: 'joint_rnd', label: '联合研发' },
    { value: 'provide_service', label: '提供技术服务' },
    { value: 'investment', label: '投融资支持' },
    { value: 'other', label: '其他' }
  ],
  result: [
    { value: 'purchase', label: '技术购买' },
    { value: 'license', label: '技术许可' },
    { value: 'joint_rnd', label: '联合研发' },
    { value: 'commercialization', label: '成果转化' },
    { value: 'pilot_validation', label: '场景验证' },
    { value: 'investment', label: '投融资' },
    { value: 'other', label: '其他' }
  ]
}

export function getIntentTypeOptions(type) {
  return INTENT_TYPE_OPTIONS[type] || []
}

export function getIntentTypeLabel(type, intentType) {
  if (!intentType) return ''
  const found = getIntentTypeOptions(type).find((o) => o.value === intentType)
  return found ? found.label : ''
}

export async function createCooperation({ type, id, intentType, message }) {
  return apiRequest('POST', '/cooperations', null, {
    targetType: toTargetType(type),
    targetId: toTargetId(id),
    intentType: intentType || undefined,
    message: message || undefined,
  })
}

export async function getCooperationDetail(intentId) {
  return apiRequest('GET', `/cooperations/${parseInt(intentId, 10)}`)
}

/** 我参与的意向列表：role = initiator | target | both */
export async function getMyCooperations(params = {}) {
  const { role = 'both', status = '', page = 1, pageSize = 10 } = params
  const query = { role, page, pageSize }
  if (status) query.status = status
  return apiRequest('GET', '/me/cooperations', query)
}

/**
 * 我对某目标是否已有进行中的意向（active：pending/accepted/confirmed）
 * 后端唯一键保证一个用户对同一目标最多一条活跃意向
 */
export async function getMyActiveIntentForTarget(type, id) {
  const data = await getMyCooperations({ role: 'initiator', page: 1, pageSize: 50 })
  const targetType = toTargetType(type)
  const targetId = String(id)
  const actives = (data.list || []).filter(
    (item) =>
      item.targetType === targetType &&
      String(item.targetId) === targetId &&
      ['pending', 'accepted', 'confirmed'].indexOf(item.status) >= 0
  )
  return actives.length > 0 ? actives[0] : null
}

// ── 状态机（均需乐观锁 version） ─────────────────────────────

export async function acceptCooperation(intentId, version) {
  return apiRequest('POST', `/cooperations/${parseInt(intentId, 10)}/accept`, null, { version })
}

export async function rejectCooperation(intentId, version, reason) {
  return apiRequest('POST', `/cooperations/${parseInt(intentId, 10)}/reject`, null, {
    version,
    reason: reason || '暂不考虑',
  })
}

export async function confirmCooperation(intentId, version) {
  return apiRequest('POST', `/cooperations/${parseInt(intentId, 10)}/confirm`, null, { version })
}

export async function cancelCooperation(intentId, version, reason) {
  return apiRequest('POST', `/cooperations/${parseInt(intentId, 10)}/cancel`, null, {
    version,
    reason: reason || '取消对接',
  })
}

export async function completeCooperation(intentId, version, remark) {
  return apiRequest('POST', `/cooperations/${parseInt(intentId, 10)}/complete`, null, {
    version,
    remark: remark || undefined,
  })
}

export async function getCooperationEvents(intentId, params = {}) {
  const { page = 1, pageSize = 20 } = params
  return apiRequest('GET', `/cooperations/${parseInt(intentId, 10)}/events`, { page, pageSize })
}

// ── 展示辅助 ─────────────────────────────────────────────────

/** 意向状态 → 中文标签 / 样式类 */
export const COOP_STATUS_META = {
  pending: { label: '待定', cls: 'pending' },
  accepted: { label: '已同意', cls: 'accepted' },
  confirmed: { label: '已确认', cls: 'success' },
  completed: { label: '已完成', cls: 'success' },
  rejected: { label: '已拒绝', cls: 'rejected' },
  cancelled: { label: '已取消', cls: 'rejected' }
}

export function getCoopStatusLabel(status) {
  const meta = COOP_STATUS_META[status]
  return meta ? meta.label : '待定'
}

export function getCoopStatusCls(status) {
  const meta = COOP_STATUS_META[status]
  return meta ? meta.cls : 'pending'
}
