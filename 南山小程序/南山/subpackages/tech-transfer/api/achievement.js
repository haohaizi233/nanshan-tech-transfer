/**
 * 成果 API —— 列表、详情、搜索、分类、我的发布、写接口
 *
 * 后端契约：openapi.yaml paths /achievements、/me/achievements、
 * /search?type=achievement（Phase B 统一搜索）
 */

import { apiRequest, publicRequest, getCurrentUser } from './client.js'
import { getPublicationStatus } from '../constants/review-status.js'

export async function getAchievements(params = {}) {
  const { page = 1, pageSize = 10, keyword = '', category = '', maturityLevel = '', industryId = '' } = params
  const query = {}
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (keyword) query.keyword = keyword
  if (category) query.category = category
  if (maturityLevel) query.maturityLevel = maturityLevel
  if (industryId) query.industryId = industryId
  return getCurrentUser()
    ? apiRequest('GET', '/achievements', query)
    : publicRequest('GET', '/achievements', query)
}

export async function getAchievementDetail(id) {
  // 游客只读取公开详情；实际对接仍由 cooperation API 在提交时强制登录。
  return getCurrentUser()
    ? apiRequest('GET', `/achievements/${id}`)
    : publicRequest('GET', `/achievements/${id}`)
}

/** 本人发布的成果：包含全量审核状态。 */
export async function getMyAchievements(params = {}) {
  const { page = 1, pageSize = 20, status = '' } = params
  const query = {}
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (status) query.status = status
  return apiRequest('GET', '/me/achievements', query)
}

/** 成果列表/详情 → “我的发布”卡片展示模型。 */
export function toAchievementCard(item) {
  const meta = getPublicationStatus(item)
  return {
    id: item.id,
    title: item.title || '',
    sourceOrgName: item.sourceOrgName || '',
    techIntro: item.techIntro || '',
    cover: item.cover || (item.media || []).find((media) => media.role === 'cover') || null,
    categoryName: item.categoryName || '',
    status: item.status,
    statusLabel: meta.label,
    statusCls: meta.cls,
    statusHint: meta.hint,
    rejectReason: item.rejectReason || '',
    version: item.version || null,
    publishedAt: item.publishedAt || null,
  }
}

/** 统一搜索（成果侧）：GET /search?q=&type=achievement，取 data.achievements */
export async function searchAchievements(params = {}) {
  const { keyword = '', page = 1, pageSize = 10, categoryCode = '', maturityLevel = '' } = params
  const query = { type: 'achievement' }
  if (keyword) query.q = keyword
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (categoryCode) query.categoryCode = categoryCode
  if (maturityLevel) query.maturityLevel = maturityLevel
  const data = getCurrentUser()
    ? await apiRequest('GET', '/search', query)
    : await publicRequest('GET', '/search', query)
  return data.achievements
}

export async function getAchievementCategories() {
  return getCurrentUser()
    ? apiRequest('GET', '/achievements/categories')
    : publicRequest('GET', '/achievements/categories')
}

export async function getAchievementIndustries() {
  return getCurrentUser()
    ? apiRequest('GET', '/achievements/industries')
    : publicRequest('GET', '/achievements/industries')
}

// ── 写接口（post-result 发布链路） ───────────────────────────

/** 创建成果（draft） */
export async function createAchievement(payload) {
  return apiRequest('POST', '/achievements', null, payload)
}

/** 编辑成果（owner + 乐观锁 + draft/rejected 状态门） */
export async function updateAchievement(id, payload) {
  return apiRequest('PATCH', `/achievements/${id}`, null, payload)
}

/** 提交审核（draft/rejected → pending_review） */
export async function submitAchievement(id, version) {
  return apiRequest('POST', `/achievements/${id}/submit`, null, { version })
}

/** 下线成果（published → offline） */
export async function offlineAchievement(id, version) {
  return apiRequest('POST', `/achievements/${id}/offline`, null, { version })
}

/** 成果报价展示文案（面议 / X 万 / X–Y 万） */
export function formatAchPrice(item) {
  const modeLabels = {
    negotiable: '面议',
    license: '许可',
    transfer: '转让',
    cooperation: '合作'
  }
  if (item.pricingMode === 'negotiable') return '面议'
  const min = item.priceMinWan
  const max = item.priceMaxWan
  if (min && max) return `${min}–${max} 万`
  if (min) return `${min} 万`
  return modeLabels[item.pricingMode] || ''
}
