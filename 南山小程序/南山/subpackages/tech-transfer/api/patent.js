/**
 * 专利检索 API
 *
 * 只走本服务 /patents；上游地址与密钥不下发。
 */

import { apiRequest } from './client.js'
import { retryRequest } from './request-retry.js'
import HostBridge from '../../../host/host-bridge.js'
import { resolveServiceOrigin } from './api-origin.js'

const TYPE_LABEL = {
  invention: '发明专利',
  utility_model: '实用新型',
  design: '外观设计',
}

export function getPatentTypeLabel(type) {
  return TYPE_LABEL[type] || '专利'
}

export async function searchPatents(params = {}) {
  const { keyword = '', assignee = '', page = 1, pageSize = 10 } = params
  const query = { page, pageSize }
  if (keyword) query.keyword = keyword
  if (assignee) query.assignee = assignee
  return retryRequest(() => apiRequest('GET', '/patents', query), { attempts: 3 })
}

export function getPatentSearchHistory(mode = 'keyword') {
  return apiRequest('GET', '/patents/search-history', { mode })
}

export function mergePatentSearchHistory(keywordList, assigneeList, limit = 10) {
  const rows = []
  for (const item of [...(keywordList || []), ...(assigneeList || [])]) {
    if (!item || !item.keyword) continue
    rows.push({
      keyword: item.keyword,
      mode: item.mode === 'assignee' ? 'assignee' : 'keyword',
      updatedAt: item.updatedAt || '',
    })
  }
  rows.sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))
  const seen = new Set()
  const unique = []
  for (const item of rows) {
    const key = `${item.mode}:${item.keyword}`
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(item)
    if (unique.length >= limit) break
  }
  return unique
}

export async function getAllPatentSearchHistory() {
  const [keyword, assignee] = await Promise.all([
    getPatentSearchHistory('keyword'),
    getPatentSearchHistory('assignee'),
  ])
  return mergePatentSearchHistory(keyword && keyword.list, assignee && assignee.list)
}

export async function clearAllPatentSearchHistory() {
  const [keyword, assignee] = await Promise.all([
    clearPatentSearchHistory('keyword'),
    clearPatentSearchHistory('assignee'),
  ])
  return { keyword, assignee }
}

export function savePatentSearchHistory(keyword, mode = 'keyword') {
  return apiRequest('POST', '/patents/search-history', undefined, { keyword, mode })
}

export function clearPatentSearchHistory(mode = 'keyword') {
  return apiRequest('DELETE', '/patents/search-history', { mode })
}

export async function getPatentDetail(publicationNo, language = '') {
  const query = language ? { language } : undefined
  return retryRequest(
    () => apiRequest('GET', `/patents/${encodeURIComponent(publicationNo)}`, query),
    { attempts: 3 },
  )
}

export function resolvePatentApiOrigin(env = {}, pageLocation = globalThis.location) {
  return resolveServiceOrigin(env, pageLocation)
}

function apiOrigin() {
  return resolvePatentApiOrigin(HostBridge.getEnvironment() || {})
}

export function getPatentPdfPageImageUrl(publicationNo, page) {
  const env = HostBridge.getEnvironment() || {}
  const prefix = env.apiPrefix || '/api/tech-transfer/v1'
  return `${apiOrigin()}${prefix}/patents/${encodeURIComponent(publicationNo)}/pdf/pages/${encodeURIComponent(page)}`
}

export async function getPatentPdfPagesMeta(publicationNo) {
  return apiRequest('GET', `/patents/${encodeURIComponent(publicationNo)}/pdf/pages`)
}

function canUseBlobUrl() {
  try {
    return typeof document !== 'undefined' && typeof Blob !== 'undefined' && typeof URL !== 'undefined'
  } catch (e) {
    return false
  }
}

function authHeader() {
  const token = HostBridge.getStorage('tt_access_token') || ''
  return token ? { Authorization: 'Bearer ' + token } : {}
}

/** 拉一页说明书 PNG，返回本页 <image> 可用的本地地址（H5 为 blob，小程序为临时文件） */
export function loadPatentPdfPage(publicationNo, page) {
  const url = getPatentPdfPageImageUrl(publicationNo, page)
  const header = authHeader()
  if (canUseBlobUrl()) {
    return new Promise((resolve, reject) => {
      uni.request({
        url,
        method: 'GET',
        header,
        responseType: 'arraybuffer',
        timeout: 60000,
        success(res) {
          if (res.statusCode !== 200) {
            reject(new Error('说明书预览失败'))
            return
          }
          resolve(URL.createObjectURL(new Blob([res.data], { type: 'image/png' })))
        },
        fail: reject,
      })
    })
  }
  return new Promise((resolve, reject) => {
    uni.downloadFile({
      url,
      header,
      timeout: 60000,
      success(res) {
        if (res.statusCode !== 200) {
          reject(new Error('说明书预览失败'))
          return
        }
        resolve(res.tempFilePath)
      },
      fail: reject,
    })
  })
}
