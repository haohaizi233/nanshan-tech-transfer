import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, clearSession, getSavedUser, getToken, saveSession } from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const user = ref(getSavedUser())

  const isLoggedIn = computed(() => Boolean(token.value))
  const displayName = computed(() => {
    const u = user.value
    return (u && (u.displayName || u.userNo)) || '管理员'
  })

  // 本地联调：后端 MockIdentityProvider 票据 = local-dev-ticket-{subject}
  // dev-user-001 为内置管理员账号
  async function login(username, password) {
    if (!username || !password) {
      throw new Error('请输入账号和密码')
    }
    const data = await api('/auth/bootstrap', {
      method: 'POST',
      body: { hostCredential: `local-dev-ticket-${username}` }
    })

    const roles = (data.user && data.user.roles) || []
    if (!roles.includes('admin')) {
      throw new Error('该账号不是管理员，无法登录后台')
    }

    token.value = data.accessToken
    user.value = data.user
    saveSession(data.accessToken, data.user)
    return data.user
  }

  async function logout() {
    token.value = ''
    user.value = null
    clearSession()
  }

  return { token, user, isLoggedIn, displayName, login, logout }
})
