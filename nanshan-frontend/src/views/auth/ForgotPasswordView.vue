<script setup>
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api/client'

const router = useRouter()

// 步骤：1-输入账号与渠道 2-验证凭证 3-设置新密码 4-完成
const step = ref(1)
const loading = ref(false)
const errorMsg = ref('')
const countdown = ref(0)
let timer = null

const form = reactive({
  account: '',
  channel: 'sms', // 'sms' | 'email_otp' | 'email_link'
  challengeId: '',
  maskedDestination: '',
  code: '',
  recoveryGrant: '',
  newPassword: '',
  confirmPassword: '',
})

const showPassword = ref(false)
const showConfirmPassword = ref(false)

const startCountdown = () => {
  countdown.value = 60
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    if (countdown.value > 0) {
      countdown.value--
    } else {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

const handleSendChallenge = async () => {
  if (!form.account.trim()) {
    errorMsg.value = '请输入登录账号、安全手机号或安全邮箱'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api('/auth/recovery/start', {
      method: 'POST',
      body: {
        account: form.account.trim(),
        channel: form.channel,
      },
      skipAuthRefresh: true,
    })
    form.challengeId = res.challengeId || ''
    form.maskedDestination = res.maskedDestination || ''
    startCountdown()
    if (form.channel === 'email_link') {
      step.value = 2 // 邮件链接直接展示前往邮箱查收提示
    } else {
      step.value = 2 // 前往输入验证码
    }
  } catch (err) {
    errorMsg.value = err.message || '发送验证信息失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const handleVerifyCode = async () => {
  if (!form.code.trim()) {
    errorMsg.value = '请输入验证码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api('/auth/recovery/verify', {
      method: 'POST',
      body: {
        challengeId: form.challengeId,
        code: form.code.trim(),
      },
      skipAuthRefresh: true,
    })
    form.recoveryGrant = res.recoveryGrant
    step.value = 3 // 进入设置新密码步骤
  } catch (err) {
    errorMsg.value = err.message || '验证码校验失败'
  } finally {
    loading.value = false
  }
}

const handleResetPassword = async () => {
  if (form.newPassword.length < 8 || form.newPassword.length > 128) {
    errorMsg.value = '新密码长度须为 8-128 位'
    return
  }
  if (form.newPassword !== form.confirmPassword) {
    errorMsg.value = '两次输入的新密码不一致'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    await api('/auth/recovery/complete', {
      method: 'POST',
      body: {
        recoveryGrant: form.recoveryGrant,
        newPassword: form.newPassword,
      },
      skipAuthRefresh: true,
    })
    step.value = 4 // 完成
  } catch (err) {
    errorMsg.value = err.message || '重置密码失败'
  } finally {
    loading.value = false
  }
}

const goLogin = () => {
  router.push('/login')
}
</script>

<template>
  <div class="recovery-page">
    <div class="recovery-card">
      <div class="card-header">
        <h2>找回密码</h2>
        <p class="subtitle">南山科转通统一安全中心</p>
      </div>

      <!-- 步骤指示器 -->
      <div class="steps-bar">
        <div class="step-item" :class="{ active: step >= 1, current: step === 1 }">
          <span class="step-num">1</span>
          <span class="step-text">确认账号</span>
        </div>
        <div class="step-line" :class="{ active: step >= 2 }"></div>
        <div class="step-item" :class="{ active: step >= 2, current: step === 2 }">
          <span class="step-num">2</span>
          <span class="step-text">身份核验</span>
        </div>
        <div class="step-line" :class="{ active: step >= 3 }"></div>
        <div class="step-item" :class="{ active: step >= 3, current: step === 3 }">
          <span class="step-num">3</span>
          <span class="step-text">重置密码</span>
        </div>
      </div>

      <!-- 步骤1：输入账号与选择渠道 -->
      <div v-if="step === 1" class="form-body">
        <div class="form-item">
          <label>账号 / 手机号 / 邮箱</label>
          <input
            v-model="form.account"
            type="text"
            placeholder="请输入您的登录账号或绑定的安全联系方式"
            class="input-control"
            :disabled="loading"
          />
        </div>

        <div class="form-item">
          <label>选择验证方式</label>
          <div class="channel-picker">
            <label class="channel-option" :class="{ selected: form.channel === 'sms' }">
              <input v-model="form.channel" type="radio" value="sms" />
              <span>短信验证码</span>
            </label>
            <label class="channel-option" :class="{ selected: form.channel === 'email_otp' }">
              <input v-model="form.channel" type="radio" value="email_otp" />
              <span>邮箱验证码</span>
            </label>
            <label class="channel-option" :class="{ selected: form.channel === 'email_link' }">
              <input v-model="form.channel" type="radio" value="email_link" />
              <span>邮件重置链接</span>
            </label>
          </div>
        </div>

        <p v-if="errorMsg" class="form-error">{{ errorMsg }}</p>

        <button class="primary-btn" :disabled="loading" @click="handleSendChallenge">
          {{ loading ? '发送中…' : '下一步，发送验证信息' }}
        </button>

        <div class="bottom-action">
          <button type="button" class="back-link" @click="goLogin">返回登录</button>
        </div>
      </div>

      <!-- 步骤2：输入验证码（或邮件链接说明） -->
      <div v-else-if="step === 2" class="form-body">
        <div v-if="form.channel === 'email_link'" class="email-notice-box">
          <p class="notice-title">重置链接已发送</p>
          <p class="notice-desc">
            若您的账号绑定了安全邮箱，系统已向该邮箱派发一次性重置链接，链接在 5 分钟内有效。
          </p>
          <p class="notice-tip">请前往您的电子邮箱查收邮件并点击链接完成密码重置。</p>
          <button class="primary-btn" @click="goLogin">返回登录页</button>
        </div>

        <div v-else>
          <div class="dest-tip">
            验证码已发送至预留安全联系方式 <span class="highlight">{{ form.maskedDestination || '***' }}</span>
          </div>

          <div class="form-item">
            <label>验证码</label>
            <div class="code-row">
              <input
                v-model="form.code"
                type="text"
                maxlength="6"
                placeholder="请输入6位验证码"
                class="input-control"
                :disabled="loading"
              />
              <button
                type="button"
                class="resend-btn"
                :disabled="countdown > 0 || loading"
                @click="handleSendChallenge"
              >
                {{ countdown > 0 ? `${countdown}秒后重发` : '重新获取' }}
              </button>
            </div>
          </div>

          <p v-if="errorMsg" class="form-error">{{ errorMsg }}</p>

          <button class="primary-btn" :disabled="loading" @click="handleVerifyCode">
            {{ loading ? '核验中…' : '验证并继续' }}
          </button>

          <div class="bottom-action">
            <button type="button" class="back-link" @click="step = 1">返回上一步</button>
          </div>
        </div>
      </div>

      <!-- 步骤3：设置新密码 -->
      <div v-else-if="step === 3" class="form-body">
        <div class="form-item">
          <label>新密码</label>
          <div class="password-wrapper">
            <input
              v-model="form.newPassword"
              :type="showPassword ? 'text' : 'password'"
              placeholder="请输入新密码（8-128位）"
              class="input-control"
              :disabled="loading"
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
              class="input-control"
              :disabled="loading"
            />
            <button type="button" class="eye-toggle" @click="showConfirmPassword = !showConfirmPassword">
              {{ showConfirmPassword ? '隐藏' : '显示' }}
            </button>
          </div>
        </div>

        <p v-if="errorMsg" class="form-error">{{ errorMsg }}</p>

        <button class="primary-btn" :disabled="loading" @click="handleResetPassword">
          {{ loading ? '提交中…' : '确认重置密码' }}
        </button>
      </div>

      <!-- 步骤4：重置成功 -->
      <div v-else-if="step === 4" class="success-box">
        <div class="success-icon">✓</div>
        <h3>密码重置成功</h3>
        <p class="success-desc">
          您的账号密码已更新，所有现有设备会话已安全退出。请使用新密码重新登录。
        </p>
        <button class="primary-btn" @click="goLogin">前往登录</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.recovery-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f4f6fa;
  padding: 24px;
}
.recovery-card {
  width: 100%;
  max-width: 520px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06);
  padding: 40px;
}
.card-header {
  text-align: center;
  margin-bottom: 28px;
}
.card-header h2 {
  font-size: 24px;
  color: #1e293b;
  margin-bottom: 8px;
}
.subtitle {
  font-size: 14px;
  color: #64748b;
}
.steps-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32px;
}
.step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}
.step-item.active .step-num {
  background: #0256ff;
  color: #fff;
}
.step-text {
  font-size: 12px;
  color: #64748b;
}
.step-item.current .step-text {
  color: #0256ff;
  font-weight: 600;
}
.step-line {
  flex: 1;
  height: 2px;
  background: #e2e8f0;
  margin: 0 12px 18px;
}
.step-line.active {
  background: #0256ff;
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
  transition: border-color 0.2s;
}
.input-control:focus {
  border-color: #0256ff;
}
.channel-picker {
  display: flex;
  gap: 12px;
}
.channel-option {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #475569;
  transition: all 0.2s;
}
.channel-option.selected {
  border-color: #0256ff;
  background: #f0f5ff;
  color: #0256ff;
  font-weight: 500;
}
.channel-option input {
  display: none;
}
.code-row {
  display: flex;
  gap: 10px;
}
.resend-btn {
  white-space: nowrap;
  padding: 0 16px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
}
.resend-btn:disabled {
  color: #94a3b8;
  cursor: not-allowed;
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
  transition: background 0.2s;
}
.primary-btn:hover:not(:disabled) {
  background: #0045d6;
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
  margin-top: 18px;
}
.back-link {
  background: none;
  border: none;
  color: #64748b;
  font-size: 14px;
  cursor: pointer;
}
.back-link:hover {
  color: #0256ff;
}
.dest-tip {
  font-size: 14px;
  color: #475569;
  margin-bottom: 18px;
}
.highlight {
  color: #0256ff;
  font-weight: 600;
}
.email-notice-box {
  text-align: center;
  padding: 20px 0;
}
.notice-title {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 12px;
}
.notice-desc {
  font-size: 14px;
  color: #475569;
  line-height: 1.6;
  margin-bottom: 8px;
}
.notice-tip {
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 24px;
}
.success-box {
  text-align: center;
  padding: 24px 0;
}
.success-icon {
  width: 56px;
  height: 56px;
  background: #22c55e;
  color: #fff;
  font-size: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 18px;
}
.success-desc {
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
  margin: 12px 0 24px;
}
</style>
