/**
 * 个人资料 API —— 页面获取自身信息的唯一入口
 */

import { request } from './client.js'
import { getStoredUser, getRefreshToken, clearSession } from '../../../host/local-adapter.js'

export function getCachedUser() {
  return getStoredUser()
}

export async function getCurrentUser() {
  return request({ method: 'GET', path: '/me' })
}

export async function updateMyProfile(updates) {
  return request({
    method: 'PATCH',
    path: '/me/profile',
    body: updates,
  })
}

export async function logout() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    clearSession()
    return
  }
  try {
    await request({
      method: 'POST',
      path: '/auth/logout',
      body: { refreshToken },
    })
  } finally {
    clearSession()
  }
}
