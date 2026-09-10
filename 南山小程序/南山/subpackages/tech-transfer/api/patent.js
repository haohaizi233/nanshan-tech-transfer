/**
 * 专利检索 API
 *
 * 只走本服务 /patents；上游地址与密钥不下发。
 */

import { apiRequest } from './client.js'
import HostBridge from '../../../host/host-bridge.js'

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
  return apiRequest('GET', '/patents', query)
}

export async function getPatentDetail(publicationNo) {
  return apiRequest('GET', `/patents/${encodeURIComponent(publicationNo)}`)
}

function apiOrigin() {
  const env = HostBridge.getEnvironment() || {}
  if (env.apiBase) return String(env.apiBase).replace(/\/$/, '')
  try {
    if (typeof location !== 'undefined' && location.origin) return location.origin
  } catch (e) {
    // ignore
  }
  return ''
}

export function getPatentPdfUrl(publicationNo) {
  const env = HostBridge.getEnvironment() || {}
  const prefix = env.apiPrefix || '/api/tech-transfer/v1'
  return `${apiOrigin()}${prefix}/patents/${encodeURIComponent(publicationNo)}/pdf`
}

export function openPatentPdf(publicationNo) {
  const token = HostBridge.getStorage('tt_access_token') || ''
  const url = getPatentPdfUrl(publicationNo)
  return new Promise((resolve, reject) => {
    uni.downloadFile({
      url,
      header: token ? { Authorization: 'Bearer ' + token } : {},
      timeout: 60000,
      success(res) {
        if (res.statusCode !== 200) {
          reject(new Error('说明书获取失败'))
          return
        }
        uni.openDocument({
          filePath: res.tempFilePath,
          fileType: 'pdf',
          showMenu: true,
          success: resolve,
          fail: reject,
        })
      },
      fail: reject,
    })
  })
}
