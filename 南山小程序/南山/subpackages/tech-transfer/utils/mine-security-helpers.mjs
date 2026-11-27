/**
 * mine.vue 安全与认证表单纯逻辑辅助函数（双端 H5 / 微信小程序通用）。
 * 保持 OTP 前导零、防并发状态判定与联系校验逻辑独立可测。
 */

export function normalizeOtpInput(raw) {
  return String(raw ?? '').replace(/\D+/g, '').slice(0, 6)
}

export function isValidPhoneNumber(phone) {
  const cleaned = String(phone || '').trim().replace(/[\s-]/g, '').replace(/^\+86/, '')
  return /^1[3-9]\d{9}$/.test(cleaned)
}

export function isValidEmailAddress(email) {
  const value = String(email || '').trim()
  return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(value)
}

export function computeCooldownSeconds(untilMs, nowMs = Date.now()) {
  if (!untilMs || untilMs <= nowMs) return 0
  return Math.ceil((untilMs - nowMs) / 1000)
}

export function buildContactVerifyPayload({ type, value, code, stepUpGrant = '' }) {
  const payload = {
    type,
    value: String(value || '').trim(),
    code: normalizeOtpInput(code),
  }
  if (stepUpGrant) {
    payload.stepUpGrant = stepUpGrant
  }
  return payload
}
