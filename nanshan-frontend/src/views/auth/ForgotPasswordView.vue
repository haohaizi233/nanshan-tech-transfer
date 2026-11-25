<script setup>
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api/client'
import {
  createIdempotencyKey,
  normalizeRecoveryCapabilities,
  resolveRetryAfterSeconds,
  sanitizeOtpCode,
  shouldReuseIdempotencyKeyOnError,
} from '../../utils/emailSecurity.js'

const router = useRouter()

// 步骤：1-输入账号与渠道 2-验证凭证 3-设置新密码 4-完成
const step = ref(1)
const loading = ref(false)
const capsLoaded = ref(false)
const errorMsg = ref('')
const countdown = ref(0)
let timer = null
let requestSeq = 0
let challengeIdempotencyKey = ''

const capabilities = reactive({
  sms: true,
  emailOtp: false,
  emailLink: false,
  hasAny: true,
  codeTtlSeconds: 300,
  cooldownSeconds: 60,
})

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

const clearTimer = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

const clearSensitiveState = () => {
  challengeIdempotencyKey = ''
  form.challengeId = ''
  form.maskedDestination = ''
  form.code = ''
  form.recoveryGrant = ''
  form.newPassword = ''
  form.confirmPassword = ''
}

const resetStaleChallenge = () => {
  requestSeq += 1
  challengeIdempotencyKey = ''
  form.challengeId = ''
  form.maskedDestination = ''
  form.code = ''
  form.recoveryGrant = ''
  errorMsg.value = ''
}

const startCountdown = (seconds = capabilities.cooldownSeconds || 60) => {
  const duration = Math.max(1, Number(seconds) || 60)
  countdown.value = duration
  clearTimer()
  timer = setInterval(() => {
    if (countdown.value > 0) {
      countdown.value--
    } else {
      clearTimer()
    }
  }, 1000)
}

const loadCapabilities = async () => {
  try {
    const res = await api('/auth/recovery/capabilities', {
      skipAuthRefresh: true,
      skipErrorToast: true,
    })
    const norm = normalizeRecoveryCapabilities(res)
    capabilities.sms = norm.sms
    capabilities.emailOtp = norm.emailOtp
    capabilities.emailLink = norm.emailLink
    capabilities.hasAny = norm.hasAny
    capabilities.codeTtlSeconds = norm.codeTtlSeconds
    capabilities.cooldownSeconds = norm.cooldownSeconds
    if (norm.defaultChannel && !isChannelEnabled(form.channel)) {
      form.channel = norm.defaultChannel
    }
  } catch {
    // 能力探测失败时保持保守默认，服务端仍会独立校验功能开关
  } finally {
    capsLoaded.value = true
  }
}

const isChannelEnabled = (ch) => {
  if (ch === 'sms') return capabilities.sms
  if (ch === 'email_otp') return capabilities.emailOtp
  if (ch === 'email_link') return capabilities.emailLink
  return false
}

watch(
  () => form.channel,
  () => {
    resetStaleChallenge()
    clearTimer()
    countdown.value = 0
    if (step.value > 1 && step.value < 4) {
      step.value = 1
    }
  }
)

watch(
  () => form.account,
  () => {
    if (form.challengeId || form.recoveryGrant) {
      resetStaleChallenge()
    }
  }
)

onMounted(() => {
  loadCapabilities()
})

onUnmounted(() => {
  clearTimer()
  clearSensitiveState()
})

const onOtpInput = (event) => {
  const cleaned = sanitizeOtpCode(event?.target?.value ?? form.code)
  form.code = cleaned
}

const handleSendChallenge = async () => {
  if (loading.value) return
  if (!capabilities.hasAny) {
    errorMsg.value = '系统暂未启用在线自助找回密码通道，请联系管理员'
    return
  }
  if (!isChannelEnabled(form.channel)) {
    errorMsg.value = '当前所选验证通道未启用，请切换其他可用验证方式'
    return
  }
  if (!form.account.trim()) {
    errorMsg.value = '请输入登录账号、安全手机号或安全邮箱'
    return
  }
  if (!challengeIdempotencyKey) {
    challengeIdempotencyKey = createIdempotencyKey('rec')
  }
  const currentSeq = ++requestSeq
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api('/auth/recovery/start', {
      method: 'POST',
      headers: { 'Idempotency-Key': challengeIdempotencyKey },
      body: {
        account: form.account.trim(),
        channel: form.channel,
      },
      skipAuthRefresh: true,
    })
    if (currentSeq !== requestSeq) return
    challengeIdempotencyKey = ''
    form.challengeId = res.challengeId || ''
    form.maskedDestination = res.maskedDestination || ''
    form.code = ''
    form.recoveryGrant = ''
    startCountdown(capabilities.cooldownSeconds)
    step.value = 2
  } catch (err) {
    if (currentSeq !== requestSeq) return
    if (!shouldReuseIdempotencyKeyOnError(err)) {
      challengeIdempotencyKey = ''
    }
    const retryAfter = resolveRetryAfterSeconds(err, 0)
    if (retryAfter > 0) startCountdown(retryAfter)
    errorMsg.value = err.message || '发送验证信息失败，请稍后重试'
  } finally {
    if (currentSeq === requestSeq) {
      loading.value = false
    }
  }
}

const handleVerifyCode = async () => {
  if (loading.value) return
  const cleanCode = sanitizeOtpCode(form.code)
  form.code = cleanCode
  if (cleanCode.length !== 6) {
    errorMsg.value = '请输入完整的 6 位数字验证码'
    return
  }
  if (!form.challengeId) {
    errorMsg.value = '验证会话已过期，请返回重新获取验证码'
    return
  }
  const currentSeq = ++requestSeq
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api('/auth/recovery/verify', {
      method: 'POST',
      body: {
        challengeId: form.challengeId,
        code: cleanCode,
      },
      skipAuthRefresh: true,
    })
    if (currentSeq !== requestSeq) return
    form.recoveryGrant = res.recoveryGrant
    step.value = 3
  } catch (err) {
    if (currentSeq !== requestSeq) return
    const retryAfter = resolveRetryAfterSeconds(err, 0)
    if (retryAfter > 0) startCountdown(retryAfter)
    errorMsg.value = err.message || '验证码校验失败'
  } finally {
    if (currentSeq === requestSeq) {
      loading.value = false
    }
  }
}

const handleResetPassword = async () => {
  if (loading.value) return
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
    clearSensitiveState()
    clearTimer()
    step.value = 4
  } catch (err) {
    errorMsg.value = err.message || '重置密码失败'
  } finally {
    loading.value = false
  }
}

const goLogin = () => {
  clearSensitiveState()
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
            <label
              class="channel-option"
              :class="{ selected: form.channel === 'sms', disabled: !capabilities.sms }"
            >
              <input v-model="form.channel" type="radio" value="sms" :disabled="!capabilities.sms" />
              <span>短信验证码{{ !capabilities.sms && capsLoaded ? '（未启用）' : '' }}</span>
            </label>
            <label
              class="channel-option"
              :class="{ selected: form.channel === 'email_otp', disabled: !capabilities.emailOtp }"
            >
              <input v-model="form.channel" type="radio" value="email_otp" :disabled="!capabilities.emailOtp" />
              <span>邮箱验证码{{ !capabilities.emailOtp && capsLoaded ? '（未启用）' : '' }}</span>
            </label>
            <label
              class="channel-option"
              :class="{ selected: form.channel === 'email_link', disabled: !capabilities.emailLink }"
            >
              <input v-model="form.channel" type="radio" value="email_link" :disabled="!capabilities.emailLink" />
              <span>邮件重置链接{{ !capabilities.emailLink && capsLoaded ? '（未启用）' : '' }}</span>
            </label>
          </div>
          <p v-if="capsLoaded && !capabilities.hasAny" class="form-error">
            当前平台暂未开放短信及邮件自助找回密码功能，请联系管理员协助重置。
          </p>
        </div>

        <p v-if="errorMsg" class="form-error">{{ errorMsg }}</p>

        <button class="primary-btn" :disabled="loading || (capsLoaded && !capabilities.hasAny)" @click="handleSendChallenge">
          {{ loading ? '提交中…' : '下一步，发送验证信息' }}
        </button>

        <div class="bottom-action">
          <button type="button" class="back-link" @click="goLogin">返回登录</button>
        </div>
      </div>

      <!-- 步骤2：输入验证码（或邮件链接说明） -->
      <div v-else-if="step === 2" class="form-body">
        <div v-if="form.channel === 'email_link'" class="email-notice-box">
          <p class="notice-title">重置请求已受理</p>
          <p class="notice-desc">
            如果账号存在且已绑定可用的安全邮箱，系统将尝试发送一次性密码重置链接。请检查您的收件箱及垃圾邮件夹。
          </p>
          <p class="notice-tip">请求受理不代表邮件已立即到达；若数分钟后仍未收到，可返回更换其他验证方式。</p>
          <button class="primary-btn" @click="goLogin">返回登录页</button>
        </div>

        <div v-else>
          <div class="dest-tip">
            验证请求已提交。如果该账号存在且已绑定可用的安全联系方式，6 位验证码将发送至对应地址（约 {{ Math.max(1, Math.floor(capabilities.codeTtlSeconds / 60)) }} 分钟内有效）。
          </div>

          <div class="form-item">
            <label>6 位验证码</label>
            <div class="code-row">
              <input
                :value="form.code"
                type="text"
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="6"
                placeholder="请输入6位数字验证码"
                class="input-control"
                :disabled="loading"
                @input="onOtpInput"
              />
              <button
                type="button"
                class="resend-btn"
                :disabled="countdown > 0 || loading"
                @click="handleSendChallenge"
              >
                {{ countdown > 0 ? `${countdown}秒后可重新提交请求` : '重新提交' }}
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
              autocomplete="new-password"
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
              autocomplete="new-password"
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
  max-width: 540px;
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
  gap: 10px;
}
.channel-option {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 6px;
  padding: 10px 8px;
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
.channel-option.disabled {
  opacity: 0.48;
  background: #f8fafc;
  cursor: not-allowed;
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
  margin-top: 8px;
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
  line-height: 1.6;
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
