<script setup>
import { ref, computed, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { validateEmail, validatePhone } from '../../utils/contactValidation.js'
import { alertDialog } from '../../utils/appDialog.js'

defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle'])

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const showUserMenu = ref(false)

const displayName = computed(() => authStore.displayName)

const pageMap = {
  '/admin/overview': {
    parent: '首页',
    name: '数据概览'
  },

  '/admin/achievements': {
    parent: '成果管理',
    name: '成果列表'
  },

  '/admin/requirements': {
    parent: '需求管理',
    name: '需求列表'
  },

  '/admin/cooperation': {
    parent: '合作对接管理',
    name: '对接列表'
  },

  '/admin/institutions': {
    parent: '机构管理',
    name: '机构列表'
  },

  '/admin/users': {
    parent: '用户管理',
    name: '用户列表'
  },

  '/admin/ai': {
    parent: 'AI推荐管理',
    name: '推荐列表'
  },

  '/admin/content': {
    parent: '内容管理',
    name: '轮播图管理'
  },

  '/admin/system': {
    parent: '系统管理',
    name: '系统设置'
  },

  '/admin/logs': {
    parent: '操作日志',
    name: '日志列表'
  },

  '/admin/capital': {
    parent: '资本对接管理',
    name: '资源列表'
  }
}

const breadcrumb = computed(() => {
  return {
    parent:
      route.meta.parent ||
      '首页',

    name:
      route.meta.title ||
      '数据概览'
  }
})

const toggleUserMenu = () => {
  showUserMenu.value = !showUserMenu.value
}

const logout = async () => {
  showUserMenu.value = false
  await authStore.logout()
  router.push('/login')
}

const profileVisible = ref(false)
const passwordVisible = ref(false)
const profileLoading = ref(false)
const profileSaving = ref(false)
const profileError = ref('')
const passwordError = ref('')
const passwordSaving = ref(false)

const profileForm = reactive({
  userNo: '',
  displayName: '',
  phone: '',
  email: '',
  wechat: '',
  roles: '',
  version: 1,
})

const passwordForm = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const openProfile = async () => {
  showUserMenu.value = false
  profileVisible.value = true
  profileError.value = ''
  profileLoading.value = true
  try {
    const data = await api('/me')
    profileForm.userNo = data.userNo || ''
    profileForm.displayName = data.displayName || ''
    profileForm.phone = data.phone || ''
    profileForm.email = data.email || ''
    profileForm.wechat = data.wechat || ''
    profileForm.roles = (data.roles || []).join('、')
    profileForm.version = data.version || 1
  } catch (err) {
    profileError.value = err.message || '加载个人信息失败'
  } finally {
    profileLoading.value = false
  }
}

const saveProfile = async () => {
  const phoneCheck = validatePhone(profileForm.phone, { required: false })
  if (!phoneCheck.ok) {
    profileError.value = phoneCheck.message
    return
  }
  const emailCheck = validateEmail(profileForm.email, { required: false })
  if (!emailCheck.ok) {
    profileError.value = emailCheck.message
    return
  }
  profileSaving.value = true
  profileError.value = ''
  try {
    const data = await api('/me/profile', {
      method: 'PATCH',
      body: {
        version: profileForm.version,
        displayName: profileForm.displayName.trim() || undefined,
        phone: phoneCheck.value || undefined,
        email: emailCheck.value || undefined,
        wechat: profileForm.wechat.trim() || undefined,
      },
    })
    authStore.setUser(data)
    profileVisible.value = false
    await alertDialog({ title: '已保存', message: '个人信息已更新' })
  } catch (err) {
    profileError.value = err.message || '保存失败'
  } finally {
    profileSaving.value = false
  }
}

const openPassword = () => {
  showUserMenu.value = false
  passwordVisible.value = true
  passwordError.value = ''
  passwordForm.currentPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
}

const savePassword = async () => {
  if (!passwordForm.currentPassword) {
    passwordError.value = '请填写当前密码'
    return
  }
  if (passwordForm.newPassword.length < 8) {
    passwordError.value = '新密码至少需要 8 位'
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    passwordError.value = '两次输入的新密码不一致'
    return
  }
  passwordSaving.value = true
  passwordError.value = ''
  try {
    await api('/me/password', {
      method: 'POST',
      body: {
        currentPassword: passwordForm.currentPassword,
        newPassword: passwordForm.newPassword,
      },
    })
    passwordVisible.value = false
    await alertDialog({ title: '已更新', message: '密码已修改，请牢记新密码' })
  } catch (err) {
    passwordError.value = err.message || '修改密码失败'
  } finally {
    passwordSaving.value = false
  }
}
</script>

<template>
  <header class="admin-header">
    <div class="header-left">
      <button
        class="hamburger-button"
        type="button"
        @click="emit('toggle')"
      >
        <span></span>
        <span></span>
        <span></span>
      </button>

      <div class="breadcrumb">
        <span class="breadcrumb-main">
          {{ breadcrumb.parent }}
        </span>

        <span class="separator">
          /
        </span>

        <span class="breadcrumb-sub">
          {{ breadcrumb.name }}
        </span>
      </div>
    </div>

    <div class="header-right">
      <button
        type="button"
        class="notification-button"
        title="通知（开发中）"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
        >
          <path
            d="M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"
          />

          <path d="M10 21h4" />
        </svg>
      </button>

      <div class="vertical-line"></div>

      <div class="user-area">
        <button
          type="button"
          class="user-button"
          @click="toggleUserMenu"
        >
          <div class="avatar">
            <div class="avatar-head"></div>
            <div class="avatar-body"></div>
          </div>

          <span class="username">
            {{ displayName }}
          </span>

          <span
            class="arrow"
            :class="{ open: showUserMenu }"
          ></span>
        </button>

        <div
          v-if="showUserMenu"
          class="user-dropdown"
        >
          <button
            type="button"
            @click="openProfile"
          >
            个人信息
          </button>

          <button
            type="button"
            @click="openPassword"
          >
            修改密码
          </button>

          <div class="dropdown-line"></div>

          <button
            type="button"
            class="logout-button"
            @click="logout"
          >
            退出登录
          </button>
        </div>
      </div>
    </div>
  </header>

  <div
    v-if="profileVisible"
    class="account-mask"
    @click.self="profileVisible = false"
  >
    <section class="account-modal">
      <header>
        <h2>个人信息</h2>
        <button type="button" class="account-close" @click="profileVisible = false">×</button>
      </header>
      <p v-if="profileLoading" class="account-hint">加载中…</p>
      <p v-else-if="profileError" class="account-error">{{ profileError }}</p>
      <div v-else class="account-form">
        <label>用户编号<input :value="profileForm.userNo" disabled /></label>
        <label>角色<input :value="profileForm.roles" disabled /></label>
        <label>姓名<input v-model="profileForm.displayName" placeholder="请输入姓名" /></label>
        <label>手机号<input v-model="profileForm.phone" placeholder="11位手机号" /></label>
        <label>邮箱<input v-model="profileForm.email" placeholder="请输入邮箱" /></label>
        <label>微信<input v-model="profileForm.wechat" placeholder="请输入微信号" /></label>
      </div>
      <footer>
        <button type="button" class="ghost-btn" @click="profileVisible = false">取消</button>
        <button type="button" class="primary-btn" :disabled="profileLoading || profileSaving" @click="saveProfile">
          {{ profileSaving ? '保存中…' : '保存' }}
        </button>
      </footer>
    </section>
  </div>

  <div
    v-if="passwordVisible"
    class="account-mask"
    @click.self="passwordVisible = false"
  >
    <section class="account-modal">
      <header>
        <h2>修改密码</h2>
        <button type="button" class="account-close" @click="passwordVisible = false">×</button>
      </header>
      <p v-if="passwordError" class="account-error">{{ passwordError }}</p>
      <div class="account-form">
        <label>当前密码<input v-model="passwordForm.currentPassword" type="password" placeholder="请输入当前密码" /></label>
        <label>新密码<input v-model="passwordForm.newPassword" type="password" placeholder="至少 8 位" /></label>
        <label>确认新密码<input v-model="passwordForm.confirmPassword" type="password" placeholder="再次输入新密码" /></label>
      </div>
      <footer>
        <button type="button" class="ghost-btn" @click="passwordVisible = false">取消</button>
        <button type="button" class="primary-btn" :disabled="passwordSaving" @click="savePassword">
          {{ passwordSaving ? '提交中…' : '确认修改' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.admin-header {
  position: sticky;
  z-index: 50;
  top: 0;

  display: flex;
  align-items: center;
  justify-content: space-between;

  height: 74px;

  padding: 0 34px;

  border-bottom: 1px solid #edf1f6;

  background: #ffffff;
}

.header-left {
  display: flex;
  align-items: center;
}

.hamburger-button {
  display: flex;
  flex-direction: column;
  justify-content: space-between;

  width: 25px;
  height: 21px;

  margin-right: 28px;
  padding: 1px 0;

  border: 0;
  background: transparent;
}

.hamburger-button span {
  display: block;

  width: 21px;
  height: 2px;

  border-radius: 2px;

  background: #26384e;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 15px;

  font-size: 17px;
}

.breadcrumb-main {
  color: #1f2938;
  font-weight: 700;
}

.separator {
  color: #bdc5d0;
}

.breadcrumb-sub {
  color: #98a3b3;
}

.header-right {
  display: flex;
  align-items: center;
}

.notification-button {
  position: relative;

  width: 36px;
  height: 36px;

  padding: 6px;

  border: 0;

  background: transparent;

  color: #27394e;
}

.notification-button svg {
  width: 24px;
  height: 24px;

  stroke-width: 1.8;
}

.notification-count {
  position: absolute;
  right: -3px;
  top: -4px;

  display: flex;
  align-items: center;
  justify-content: center;

  min-width: 20px;
  height: 20px;

  padding: 0 5px;

  border: 2px solid white;
  border-radius: 12px;

  background: #ff3f4b;

  color: white;

  font-size: 10px;
  font-weight: 700;
}

.vertical-line {
  width: 1px;
  height: 28px;

  margin: 0 19px;

  background: #e6ebf1;
}

.user-area {
  position: relative;
}

.user-button {
  display: flex;
  align-items: center;

  border: 0;
  background: transparent;
}

.avatar {
  position: relative;

  width: 38px;
  height: 38px;

  overflow: hidden;

  border: 2px solid #ddecf8;
  border-radius: 50%;

  background:
    linear-gradient(
      180deg,
      #cbeeff,
      #79bddf
    );
}

.avatar-head {
  position: absolute;

  left: 12px;
  top: 6px;

  width: 11px;
  height: 12px;

  border-radius: 50%;

  background: #33485a;
}

.avatar-body {
  position: absolute;

  left: 8px;
  bottom: 2px;

  width: 19px;
  height: 17px;

  border-radius: 12px 12px 4px 4px;

  background: #26394b;
}

.username {
  margin-left: 12px;

  color: #273345;

  font-size: 15px;
  font-weight: 600;
}

.arrow {
  width: 7px;
  height: 7px;

  margin-left: 10px;
  margin-top: -4px;

  border-right: 1.5px solid #6f7a89;
  border-bottom: 1.5px solid #6f7a89;

  transform: rotate(45deg);

  transition: transform 0.2s;
}

.arrow.open {
  margin-top: 4px;
  transform: rotate(225deg);
}

.user-dropdown {
  position: absolute;

  right: 0;
  top: 50px;

  width: 140px;

  padding: 7px;

  border: 1px solid #e5eaf1;
  border-radius: 7px;

  background: white;

  box-shadow:
    0 10px 30px rgba(43, 63, 86, 0.12);
}

.user-dropdown button {
  width: 100%;
  height: 38px;

  padding: 0 12px;

  border: 0;
  border-radius: 5px;

  background: transparent;

  color: #4a5667;

  text-align: left;
}

.user-dropdown button:hover {
  background: #f4f7fb;
}

.dropdown-line {
  height: 1px;

  margin: 5px 0;

  background: #edf0f4;
}

.user-dropdown .logout-button {
  color: #f0525d;
}

.account-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(18, 32, 48, 0.35);
}

.account-modal {
  width: 460px;
  max-width: calc(100vw - 40px);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 18px 50px rgba(30, 48, 70, 0.18);
}

.account-modal header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 0;
}

.account-modal h2 {
  margin: 0;
  font-size: 18px;
  color: #1f2938;
}

.account-close {
  border: 0;
  background: transparent;
  font-size: 22px;
  color: #8a95a5;
  cursor: pointer;
}

.account-form {
  display: grid;
  gap: 12px;
  padding: 18px 22px;
}

.account-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #536073;
  font-size: 13px;
}

.account-form input {
  height: 38px;
  padding: 0 12px;
  border: 1px solid #e5eaf1;
  border-radius: 6px;
  color: #273345;
}

.account-form input:disabled {
  background: #f5f7fa;
  color: #8a95a5;
}

.account-hint,
.account-error {
  margin: 12px 22px 0;
  font-size: 13px;
}

.account-error {
  color: #ef4f5d;
}

.account-modal footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 0 22px 18px;
}

.ghost-btn,
.primary-btn {
  height: 36px;
  padding: 0 16px;
  border-radius: 6px;
  border: 1px solid #dbe3ee;
  background: #fff;
  color: #4a5667;
}

.primary-btn {
  border: 0;
  background: #1a7fff;
  color: #fff;
}

.primary-btn:disabled {
  opacity: 0.6;
}
</style>