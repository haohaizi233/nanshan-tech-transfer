/**
 * 用户/认证 API（主包轻量版）
 *
 * 会话与 token 管理统一复用 common/api-core.js（同一套 storage key +
 * 认证模式标记），本模块仅保留子分包 mine 页需要的薄封装：
 * - getCachedUser：读缓存（含 mock 会话，供本地开发自动登录页展示）
 * - getCurrentUser：GET /me（后端实时资料）
 * - updateMyProfile：PATCH /me/profile
 * - logout：吊销会话并清缓存
 */

import { apiRequest, authLogout } from './api-core.js'

const USER_KEY = 'tt_current_user'

export function getCachedUser() {
  try {
    return uni.getStorageSync(USER_KEY) || null
  } catch (e) {
    return null
  }
}

export async function getCurrentUser() {
  return apiRequest('GET', '/me')
}

export async function updateMyProfile(updates) {
  return apiRequest('PATCH', '/me/profile', null, updates)
}

export async function logout() {
  return authLogout()
}
