/**
 * 资本对接 API —— 统一机构接口 /institutions（公开数据，无需登录）
 *
 * Phase B 收口：legacy 平台基地/投资机构/服务机构三组并行接口与演示数据
 * 分支全部废弃，统一走 /institutions。子模块展示配置（CAPITAL_MODULES
 * 等）见 constants/capital-modules.js。
 */

import HostBridge from '../../../host/host-bridge.js'
import { publicRequest } from './client.js'

/** 相对 logoUrl（/api/file/xx）补全为可访问绝对地址 */
function absoluteLogoUrl(url) {
  const u = String(url || '')
  if (!u || u.indexOf('http') === 0) return u
  let base = ''
  try {
    base = HostBridge.getEnvironment().apiBase || ''
  } catch (e) {
    base = ''
  }
  return base + u
}

function normalizeList(data) {
  const list = (Array.isArray(data.list) ? data.list : []).map((item) =>
    Object.assign({}, item, { logoUrl: absoluteLogoUrl(item.logoUrl) })
  )
  return {
    list,
    total: Number(data.total) || 0,
    page: Number(data.page) || 1,
    pageSize: Number(data.pageSize) || 10,
    totalPages: Number(data.totalPages) || 0,
  }
}

/**
 * 平台列表（概念验证中心 / 中小试基地）
 * @param {'poc'|'pilot'|'all'} type
 */
export async function fetchPlatformList(type, keyword, page, pageSize) {
  const query = { kind: 'platform', type: type || 'all' }
  if (keyword && String(keyword).trim()) query.keyword = String(keyword).trim()
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  const data = await publicRequest('GET', '/institutions', query)
  return normalizeList(data)
}

/**
 * 机构列表（投资机构 / 银行融资）
 * @param {'bank'|'invest'} kind bank 映射为后端 service 类机构
 */
export async function fetchOrgList(kind, keyword, page, pageSize) {
  const query = { kind: kind === 'bank' ? 'service' : 'invest' }
  if (keyword && String(keyword).trim()) query.keyword = String(keyword).trim()
  if (page) query.page = page
  if (pageSize) query.pageSize = pageSize
  const data = await publicRequest('GET', '/institutions', query)
  return normalizeList(data)
}

/** 非数据库子模块的静态列表（当前非待定子模块均走接口，恒为空） */
export function listCapitalItems() {
  return []
}

export function getPlatformTypeLabel(type) {
  if (!type) return '平台'
  if (type === 'poc' || String(type).indexOf('概念验证') >= 0) return '概念验证中心'
  if (type === 'pilot' || String(type).indexOf('中小试') >= 0 || String(type).indexOf('中试') >= 0) {
    return String(type).indexOf('概念') >= 0 ? '概念验证中心' : (String(type) === 'pilot' ? '中小试基地' : String(type))
  }
  return String(type)
}
