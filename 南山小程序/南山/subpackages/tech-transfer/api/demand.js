/**
 * 需求 API —— 列表、详情、写接口、我的需求
 * 后端契约：openapi.yaml paths /demands、/me/demands
 */

import { apiRequest } from './client.js'
import { getPublicationStatus } from '../constants/review-status.js'

export async function getDemands(params = {}) {
  const { page = 1, pageSize = 10, keyword = '', categoryCode = '', includeMine = false } = params
  const query = {}
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (keyword) query.keyword = keyword
  if (categoryCode) query.categoryCode = categoryCode
  if (includeMine) query.includeMine = 'true'
  return apiRequest('GET', '/demands', query)
}

export async function getDemandDetail(id) {
  return apiRequest('GET', `/demands/${id}`)
}

export async function createDemand(payload) {
  return apiRequest('POST', '/demands', null, payload)
}

export async function updateDemand(id, payload) {
  return apiRequest('PATCH', `/demands/${id}`, null, payload)
}

export async function submitDemand(id, version) {
  return apiRequest('POST', `/demands/${id}/submit`, null, { version })
}

export async function cancelDemand(id, version) {
  return apiRequest('POST', `/demands/${id}/cancel`, null, { version })
}

export async function closeDemand(id, version) {
  return apiRequest('POST', `/demands/${id}/close`, null, { version })
}

export async function getMyDemands(params = {}) {
  const { page = 1, pageSize = 20, status = '' } = params
  const query = {}
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (status) query.status = status
  return apiRequest('GET', '/me/demands', query)
}

/** 需求列表/详情 → 卡片展示模型 */
export function toDemandCard(d) {
  const budget = d.budgetNegotiable
    ? '面议'
    : d.budgetMinWan || d.budgetMaxWan
      ? (d.budgetMinWan ? `${d.budgetMinWan}–${d.budgetMaxWan || ''}` : `${d.budgetMaxWan || ''}`) + ' 万'
      : ''
  const meta = getPublicationStatus(d)
  return {
    id: d.id,
    title: d.title,
    company: d.orgName || '',
    orgCertified: !!d.orgCertified,
    orgId: d.orgId || null,
    companyIntro: d.orgIntro || '',
    location: d.region || '',
    budget,
    demandDesc: d.description || '',
    cooperationType: (d.coopMode || []).join(' / '),
    deadline: d.deadlineDesc || '',
    industry: d.categoryName || '',
    tags: d.tags || [],
    status: d.status,
    statusLabel: meta.label,
    statusCls: meta.cls,
    statusHint: meta.hint,
    rejectReason: d.rejectReason || '',
    isMine: !!d.isMine,
    version: d.version || null,
    contactName: d.contactName || '',
    contactTitle: d.contactTitle || '',
    phone: d.contactPhone || '',
    email: d.contactEmail || '',
    wechat: d.contactWechat || ''
  }
}
