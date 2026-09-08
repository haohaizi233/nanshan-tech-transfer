/**
 * 个人资料 API —— 页面获取自身信息的唯一入口
 */

import { request, getCurrentUser, authLogout } from './client.js'

export function getCachedUser() {
  return getCurrentUser()
}

export async function getCurrentUserProfile() {
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
  return authLogout()
}
