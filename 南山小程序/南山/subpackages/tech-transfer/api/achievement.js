/**
 * 成果 API —— 列表、详情、搜索、分类
 */

import { request } from './client.js'

export async function getAchievements(params = {}) {
  const { page = 1, pageSize = 10, keyword = '', category = '', maturityLevel = '' } = params
  const query = {}
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  if (keyword) query.keyword = keyword
  if (category) query.category = category
  if (maturityLevel) query.maturityLevel = maturityLevel
  return request({ method: 'GET', path: '/achievements', query })
}

export async function getAchievementDetail(id) {
  return request({ method: 'GET', path: `/achievements/${id}` })
}

export async function searchAchievements(params = {}) {
  const { keyword = '', page = 1, pageSize = 10 } = params
  const query = { type: 'achievement' }
  if (keyword) query.keyword = keyword
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  return request({ method: 'GET', path: '/search', query })
}

export async function getAchievementCategories() {
  return request({ method: 'GET', path: '/achievements/categories' })
}
