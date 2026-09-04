import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  api,
  clearSession,
  getRefreshToken,
  getSavedUser,
  getToken,
  saveSession
} from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const user = ref(getSavedUser())

  const isLoggedIn = computed(() => Boolean(token.value))
  const displayName = computed(() => {
    const u = user.value
    return (u && (u.displayName || u.userNo)) || '管理员'
  })

  // 真实账号密码登录（后端 user_credential 表校验，PBKDF2 哈希）
  async function login(username, password) {
    if (!username || !password) {
      throw new Error('请输入账号和密码')
    }
    const data = await api('/auth/login', {
      method: 'POST',
      body: { username: username.trim(), password },
      skipAuthRefresh: true
    })

    const roles = (data.user && data.user.roles) || []
    if (!roles.includes('admin')) {
      throw new Error('该账号不是管理员，无法登录后台')
    }

    token.value = data.accessToken
    user.value = data.user
    saveSession(data.accessToken, data.user, data.refreshToken)
    return data.user
  }

  async function logout() {
    // 吊销后端 refresh 会话（失败不阻塞本地登出）
    const refreshToken = getRefreshToken()
    if (refreshToken) {
      try {
        await api('/auth/logout', {
          method: 'POST',
          body: { refreshToken },
          skipAuthRefresh: true
        })
      } catch {
        /* 本地照常清理 */
      }
    }
    token.value = ''
    user.value = null
    clearSession()
  }

  return { token, user, isLoggedIn, displayName, login, logout }
})
