/**
 * 成果 API（主包轻量版）
 *
 * 主包页面（index.vue、search.vue）不能 require 子分包模块，
 * 因此本模块直接用 uni.request + storage token，
 * 与子分包的 api/client.js 共享同一套 storage key。
 *
 * 子分包页面仍使用 api/achievement.js → client.js（含自动 bootstrap/refresh）。
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
  const res = await new Promise((resolve, reject) => {
    uni.request({
      url: buildURL(path, query),
      method: method.toUpperCase(),
      data: body,
      header: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
      },
      timeout: 30000,
      success: (res) => resolve(res.data),
      fail: (err) => reject(err),
    })
  })
  if (res.code === 0) return res.data
  throw new Error(res.message || 'Request failed')
}

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
