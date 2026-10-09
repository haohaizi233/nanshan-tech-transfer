/**
 * 搜索：历史记录（纯 UI 本地状态）+ 统一搜索 /search
 * 需求/成果历史分开保存，各最多 10 条
 */

import { apiRequest, publicRequest, getCurrentUser } from './client.js'

const DEMAND_HISTORY_KEY = 'ns_search_history_demand'
const RESULT_HISTORY_KEY = 'ns_search_history_result'
const HISTORY_MAX = 10

function readHistory(key) {
  try {
    const list = uni.getStorageSync(key)
    return Array.isArray(list) ? list : []
  } catch (e) {
    return []
  }
}

function writeHistory(key, list) {
  uni.setStorageSync(key, list)
}

export function getDemandSearchHistory() {
  return readHistory(DEMAND_HISTORY_KEY)
}

export function getResultSearchHistory() {
  return readHistory(RESULT_HISTORY_KEY)
}

export function addDemandSearchHistory(keyword) {
  return addHistory(DEMAND_HISTORY_KEY, keyword)
}

export function addResultSearchHistory(keyword) {
  return addHistory(RESULT_HISTORY_KEY, keyword)
}

function addHistory(key, keyword) {
  const kw = (keyword || '').trim()
  if (!kw) return readHistory(key)
  let list = readHistory(key).filter((item) => item !== kw)
  list.unshift(kw)
  if (list.length > HISTORY_MAX) {
    list = list.slice(0, HISTORY_MAX)
  }
  writeHistory(key, list)
  return list
}

export function clearDemandSearchHistory() {
  uni.removeStorageSync(DEMAND_HISTORY_KEY)
  return []
}

export function clearResultSearchHistory() {
  uni.removeStorageSync(RESULT_HISTORY_KEY)
  return []
}

/**
 * 统一搜索（Phase B 双类型聚合）
 * @param {string} q 关键词（后端必填、≤64 字符）
 * @param {'achievement'|'demand'|'all'} type
 * @returns {Promise<{achievements:{total,page,pageSize,totalPages,list}, demands:{...}}>}
 */
export async function searchAll(q, type = 'all', page = 1, pageSize = 10) {
  const query = { q, type }
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  return getCurrentUser()
    ? apiRequest('GET', '/search', query)
    : publicRequest('GET', '/search', query)
}
