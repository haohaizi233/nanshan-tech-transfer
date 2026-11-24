<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api/client'
import { parseResetCredentialsFromLocation } from '../../utils/emailSecurity.js'

const route = useRoute()
const router = useRouter()

const hasValidParams = ref(false)
const submitting = ref(false)
const errorMsg = ref('')
const resetSuccess = ref(false)

const showPassword = ref(false)
const showConfirmPassword = ref(false)

// 敏感凭据仅存组件内存；绝不写入 localStorage / sessionStorage；页面卸载立即清空
const credentials = reactive({
  challengeId: '',
  token: '',
  recoveryGrant: '',
})

const form = reactive({
  newPassword: '',
  confirmPassword: '',
})

const clearSensitiveState = () => {
  credentials.challengeId = ''
  credentials.token = ''
  credentials.recoveryGrant = ''
  form.newPassword = ''
  form.confirmPassword = ''
}

onMounted(() => {
  // 页面加载仅读取 URL Fragment/Query 并立即清理地址栏，严禁自动触发 POST /recovery/verify，
  // 防止邮件安全扫描器、链接预览预加载提前消费一次性重置 Token。
  const { challengeId, token } = parseResetCredentialsFromLocation({
    hash: typeof window !== 'undefined' ? window.location.hash : '',
    query: route.query,
  })

  if (typeof window !== 'undefined' && window.history && window.history.replaceState) {
    window.history.replaceState({}, document.title, window.location.pathname)
  }

  if (!challengeId || !token) {
    hasValidParams.value = false
    errorMsg.value = '重置链接无效或已缺少凭据，请重新申请密码找回'
    return
  }

  credentials.challengeId = challengeId
  credentials.token = token
  hasValidParams.value = true
})

onUnmounted(() => {
  clearSensitiveState()
})

const handleComplete = async () => {
  if (submitting.value) return
  if (form.newPassword.length < 8 || form.newPassword.length > 128) {
    errorMsg.value = '新密码长度须为 8-128 位'
    return
  }
  if (form.newPassword !== form.confirmPassword) {
    errorMsg.value = '两次输入的新密码不一致'
    return
  }

  submitting.value = true
  errorMsg.value = ''
  try {
    // 1. 仅在用户主动确认提交后核验一次性链接 Token 并换取短期 Recovery Grant
    if (!credentials.recoveryGrant) {
      const verifyRes = await api('/auth/recovery/verify', {
        method: 'POST',
        body: {
          challengeId: credentials.challengeId,
          code: credentials.token,
        },
        skipAuthRefresh: true,
      })
      credentials.recoveryGrant = verifyRes.recoveryGrant
      credentials.token = ''
    }

    // 2. 使用 Recovery Grant 完成密码重置并吊销全部旧会话
    await api('/auth/recovery/complete', {
      method: 'POST',
      body: {
        recoveryGrant: credentials.recoveryGrant,
        newPassword: form.newPassword,
      },
      skipAuthRefresh: true,
    })

    clearSensitiveState()
    resetSuccess.value = true
  } catch (err) {
    errorMsg.value = err.message || '重置链接已失效或密码更新失败，请重新申请'
  } finally {
    submitting.value = false
  }
}

const goLogin = () => {
  clearSensitiveState()
  router.push('/login')
}
</script>

<template>
  <div class="reset-page">
    <div class="reset-card">
      <div class="card-header">
        <h2>重置登录密码</h2>
        <p class="subtitle">南山科转通统一安全中心</p>
      </div>

      <div v-if="!hasValidParams && !resetSuccess" class="error-state">
        <div class="error-icon">!</div>
        <h3>链接无效</h3>
        <p class="error-desc">{{ errorMsg }}</p>
        <button class="primary-btn" @click="router.push('/forgot-password')">重新申请找回密码</button>
      </div>

      <div v-else-if="resetSuccess" class="success-box">
        <div class="success-icon">✓</div>
        <h3>密码重置成功</h3>
        <p class="success-desc">
          您的账号密码已更新，所有现有设备会话已安全退出。请使用新密码重新登录。
        </p>
        <button class="primary-btn" @click="goLogin">前往登录</button>
      </div>

      <form v-else class="form-body" @submit.prevent="handleComplete">
        <div class="safe-notice">
          为防止邮件预加载或安全扫描器误触发，请在下方主动填写并确认提交新密码以完成重置。
        </div>

        <div class="form-item">
          <label>设置新密码</label>
          <div class="password-wrapper">
            <input
              v-model="form.newPassword"
              :type="showPassword ? 'text' : 'password'"
              placeholder="请输入新密码（8-128位）"
              autocomplete="new-password"
              class="input-control"
              :disabled="submitting"
            />
            <button type="button" class="eye-toggle" @click="showPassword = !showPassword">
              {{ showPassword ? '隐藏' : '显示' }}
            </button>
          </div>
        </div>

        <div class="form-item">
          <label>确认新密码</label>
          <div class="password-wrapper">
            <input
              v-model="form.confirmPassword"
              :type="showConfirmPassword ? 'text' : 'password'"
              placeholder="请再次输入新密码"
              autocomplete="new-password"
              class="input-control"
              :disabled="submitting"
            />
            <button type="button" class="eye-toggle" @click="showConfirmPassword = !showConfirmPassword">
              {{ showConfirmPassword ? '隐藏' : '显示' }}
            </button>
          </div>
        </div>

        <p v-if="errorMsg" class="form-error">{{ errorMsg }}</p>

        <button class="primary-btn" type="submit" :disabled="submitting">
          {{ submitting ? '确认并提交中…' : '确认并重置密码' }}
        </button>

        <div class="bottom-action">
          <button type="button" class="back-link" @click="router.push('/forgot-password')">
            链接已失效？重新申请找回密码
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.reset-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f4f6fa;
  padding: 24px;
}
.reset-card {
  width: 100%;
  max-width: 480px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06);
  padding: 40px;
}
.card-header {
  text-align: center;
  margin-bottom: 24px;
}
.card-header h2 {
  font-size: 22px;
  color: #1e293b;
  margin-bottom: 8px;
}
.subtitle {
  font-size: 14px;
  color: #64748b;
}
.safe-notice {
  background: #f0f5ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  font-size: 13px;
  line-height: 1.5;
  padding: 10px 12px;
  border-radius: 6px;
  margin-bottom: 20px;
}
.error-state {
  text-align: center;
  padding: 30px 0;
  color: #64748b;
}
.error-icon {
  width: 50px;
  height: 50px;
  background: #ef4444;
  color: #fff;
  font-size: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
  font-weight: bold;
}
.error-desc {
  margin: 12px 0 24px;
  font-size: 14px;
  color: #475569;
}
.form-item {
  margin-bottom: 20px;
}
.form-item label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #334155;
  margin-bottom: 8px;
}
.input-control {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}
.input-control:focus {
  border-color: #0256ff;
}
.password-wrapper {
  position: relative;
}
.eye-toggle {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #64748b;
  font-size: 12px;
  cursor: pointer;
}
.primary-btn {
  width: 100%;
  padding: 12px 0;
  background: #0256ff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  margin-top: 10px;
}
.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.form-error {
  color: #ef4444;
  font-size: 13px;
  margin-bottom: 12px;
}
.bottom-action {
  text-align: center;
  margin-top: 16px;
}
.back-link {
  background: none;
  border: none;
  color: #64748b;
  font-size: 13px;
  cursor: pointer;
}
.back-link:hover {
  color: #0256ff;
}
.success-box {
  text-align: center;
  padding: 20px 0;
}
.success-icon {
  width: 52px;
  height: 52px;
  background: #22c55e;
  color: #fff;
  font-size: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}
.success-desc {
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
  margin: 12px 0 24px;
}
</style>
