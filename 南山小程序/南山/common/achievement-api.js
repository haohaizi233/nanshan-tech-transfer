/**
 * 成果 API（主包轻量版）
 *
 * 主包页面（index.vue、search.vue）不能 require 子分包模块，
 * 请求基础设施见 common/api-core.js。
 * 子分包页面仍使用 api/achievement.js → client.js（含自动 bootstrap/refresh）。
 */

import { apiRequest } from './api-core.js'
import { getPublicationStatus } from './review-status.js'

export async function getAchievements(params = {}) {
  const { page = 1, pageSize = 10, keyword = '', category = '', maturityLevel = '' } = params
  const query = {}
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (keyword) query.keyword = keyword
  if (category) query.category = category
  if (maturityLevel) query.maturityLevel = maturityLevel
  return apiRequest('GET', '/achievements', query)
}

export async function getAchievementDetail(id) {
  return apiRequest('GET', `/achievements/${id}`)
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

export async function searchAchievements(params = {}) {
  const { keyword = '', page = 1, pageSize = 10 } = params
  const query = { type: 'achievement' }
  if (keyword) query.keyword = keyword
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  return apiRequest('GET', '/search', query)
}

export async function getAchievementCategories() {
  return apiRequest('GET', '/achievements/categories')
}

/** 成果报价展示文案（面议 / X 万 / X–Y 万） */
export function formatAchPrice(item) {
  const modeLabels = {
    negotiable: '面议',
    license: '许可',
    transfer: '转让',
    cooperation: '合作'
  }
  if (item.pricingMode === 'negotiable' || !item.priceMinWan) {
    return modeLabels[item.pricingMode] || '面议'
  }
  const min = item.priceMinWan
  const max = item.priceMaxWan
  if (min && max) return `${min}–${max} 万`
  return `${min} 万`
}
