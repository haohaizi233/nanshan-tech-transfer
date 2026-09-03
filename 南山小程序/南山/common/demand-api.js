/**
 * 需求 API（主包轻量版）
 *
 * 与 achievement-api.js 同模式：主包/分包页面均可引用，
 * 直接用 uni.request + storage token，自动 bootstrap。
 * 后端契约：openapi.yaml paths /demands、/me/demands
 */

import { API_BASE } from './config.js'
import { getMockTicket } from '../host/mock-identity.js'

const API_PREFIX = '/api/tech-transfer/v1'
const ACCESS_TOKEN_KEY = 'tt_access_token'
const TOKEN_EXPIRES_KEY = 'tt_token_expires_at'

function buildURL(path, query) {
  let url = API_BASE + API_PREFIX + path
  if (query && Object.keys(query).length > 0) {
    const qs = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&')
    if (qs) url += '?' + qs
  }
  return url
}

function getToken() {
  try {
    const expiresAt = uni.getStorageSync(TOKEN_EXPIRES_KEY)
    if (!expiresAt || Date.now() >= expiresAt) return null
    return uni.getStorageSync(ACCESS_TOKEN_KEY) || null
  } catch (e) {
    return null
  }
}

async function ensureToken() {
  let token = getToken()
  if (token) return token
  const res = await new Promise((resolve, reject) => {
    uni.request({
      url: buildURL('/auth/bootstrap', null),
      method: 'POST',
      data: { hostCredential: getMockTicket() },
      header: { 'Content-Type': 'application/json' },
      timeout: 30000,
      success: (res) => resolve(res.data),
      fail: (err) => reject(err),
    })
  })
  if (res.code === 0 && res.data) {
    uni.setStorageSync(ACCESS_TOKEN_KEY, res.data.accessToken)
    uni.setStorageSync('tt_refresh_token', res.data.refreshToken)
    uni.setStorageSync('tt_current_user', res.data.user)
    uni.setStorageSync(TOKEN_EXPIRES_KEY, Date.now() + (res.data.expiresIn || 7200) * 1000)
    return res.data.accessToken
  }
  throw new Error('Bootstrap failed: ' + (res.message || 'unknown'))
}

async function apiRequest(method, path, query, body) {
  const token = await ensureToken()
  const header = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + token,
  }
  if (method === 'POST' || method === 'PATCH') {
    header['X-Idempotency-Key'] = 'tt_' + Date.now() + '_' + Math.floor(Math.random() * 100000)
  }
  const res = await new Promise((resolve, reject) => {
    uni.request({
      url: buildURL(path, query),
      method: method.toUpperCase(),
      data: body,
      header,
      timeout: 30000,
      success: (res) => resolve(res.data),
      fail: (err) => reject(err),
    })
  })
  if (res.code === 0) return res.data
  const err = new Error(res.message || 'Request failed')
  err.code = res.code
  throw err
}

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

/** 需求状态 → 中文标签 / 样式类（my-list 状态标签用） */
const DEMAND_STATUS_META = {
  draft: { label: '草稿', cls: 'draft' },
  pending_review: { label: '待审核', cls: 'pending' },
  published: { label: '已发布', cls: 'success' },
  matched: { label: '已匹配', cls: 'accepted' },
  closed: { label: '已关闭', cls: 'rejected' },
  rejected: { label: '已驳回', cls: 'rejected' },
  cancelled: { label: '已取消', cls: 'rejected' }
}

/** 需求列表/详情 → 卡片展示模型 */
export function toDemandCard(d) {
  const budget = d.budgetNegotiable
    ? '面议'
    : d.budgetMinWan || d.budgetMaxWan
      ? (d.budgetMinWan ? `${d.budgetMinWan}–${d.budgetMaxWan || ''}` : `${d.budgetMaxWan || ''}`) + ' 万'
      : ''
  const meta = DEMAND_STATUS_META[d.status] || { label: d.status, cls: 'draft' }
  return {
    id: d.id,
    title: d.title,
    company: d.orgName || '',
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
    isMine: !!d.isMine,
    version: d.version || null,
    contactName: d.contactName || '',
    contactTitle: d.contactTitle || '',
    phone: d.contactPhone || '',
    email: d.contactEmail || '',
    wechat: d.contactWechat || ''
  }
}
