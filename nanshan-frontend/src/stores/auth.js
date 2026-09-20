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

// 多标签会话同步：监听 storage 事件，当其他标签更新/清除 token/user 时
// 同步刷新本标签的 store 状态，避免一边登出后另一边仍显示已登录。
const TOKEN_KEY = 'nanshan_admin_token'
const USER_KEY = 'nanshan_admin_user'
const REFRESH_KEY = 'nanshan_admin_refresh_token'

// 持有当前 store 实例引用，供 storage 监听器同步状态。
let piniaStoreRef = null

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== TOKEN_KEY && event.key !== USER_KEY && event.key !== REFRESH_KEY) return
    const nextToken = getToken()
    const nextUser = getSavedUser()
    // 通过全局事件总线式赋值：直接写当前 store 实例（如果已创建）。
    const store = piniaStoreRef
    if (store) {
      store.token = nextToken
      store.user = nextUser
    }
  })
}

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
    if (!roles.includes('admin') && !roles.includes('org_admin')) {
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

  function setUser(nextUser) {
    user.value = nextUser
    saveSession(token.value, nextUser, getRefreshToken())
  }

  async function refreshUser() {
    const data = await api('/me')
    setUser(data)
    return data
  }

  // 暴露响应式状态给模块级 storage 监听器，实现多标签同步。
  piniaStoreRef = { get token() { return token.value }, set token(v) { token.value = v }, get user() { return user.value }, set user(v) { user.value = v } }

  return { token, user, isLoggedIn, displayName, login, logout, setUser, refreshUser }
})
