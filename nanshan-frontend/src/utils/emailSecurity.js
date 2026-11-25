/** 邮箱安全找回与换绑前端纯辅助逻辑（无持久存储敏感凭证，保留前导零）。 */

export const STEP_UP_METHOD_LABELS = {
  password: '验证当前登录密码',
  old_email_otp: '通过原安全邮箱接收验证码',
  old_phone_otp: '通过原安全手机号接收验证码',
  recent_auth: '使用当前近期安全会话继续',
}

/**
 * 保留前导零的 6 位数字验证码清洗（绝不转换为 Number）。
 */
export function sanitizeOtpCode(raw) {
  return String(raw == null ? '' : raw).replace(/\D/g, '').slice(0, 6)
}

/**
 * 从 URL Fragment (#challengeId=...&token=...) 优先解析一次性凭据，兼容 query 参数。
 */
export function parseResetCredentialsFromLocation({ hash = '', query = {} } = {}) {
  let challengeId = ''
  let token = ''
  const rawHash = String(hash || '').replace(/^#/, '')
  if (rawHash) {
    const hashQuery = rawHash.includes('?') ? rawHash.slice(rawHash.indexOf('?') + 1) : rawHash
    const params = new URLSearchParams(hashQuery)
    challengeId = (params.get('challengeId') || '').trim()
    token = (params.get('token') || '').trim()
  }
  if (!challengeId && query && query.challengeId) {
    challengeId = String(query.challengeId).trim()
  }
  if (!token && query && query.token) {
    token = String(query.token).trim()
  }
  return { challengeId, token }
}

/**
 * 规范化服务端找回能力开关并挑选默认可用找回通道。
 */
export function normalizeRecoveryCapabilities(caps) {
  const data = caps && typeof caps === 'object' ? caps : {}
  const sms = Boolean(data.sms)
  const emailOtp = Boolean(data.emailOtp)
  const emailLink = Boolean(data.emailLink)
  const codeTtlSeconds = Number(data.codeTtlSeconds) > 0 ? Number(data.codeTtlSeconds) : 300
  const cooldownSeconds = Number(data.cooldownSeconds) > 0 ? Number(data.cooldownSeconds) : 60

  let defaultChannel = ''
  if (sms) defaultChannel = 'sms'
  else if (emailOtp) defaultChannel = 'email_otp'
  else if (emailLink) defaultChannel = 'email_link'

  return {
    sms,
    emailOtp,
    emailLink,
    hasAny: sms || emailOtp || emailLink,
    codeTtlSeconds,
    cooldownSeconds,
    defaultChannel,
  }
}

/**
 * 从错误对象提取服务端 Retry-After 秒数。
 */
export function resolveRetryAfterSeconds(err, fallback = 0) {
  const candidates = [err?.retryAfter, err?.details?.retryAfter]
  for (const val of candidates) {
    const parsed = Number.parseInt(String(val ?? ''), 10)
    if (Number.isFinite(parsed) && parsed > 0) {
      return Math.min(3600, parsed)
    }
  }
  return fallback
}

/**
 * 生成随机不透明 HTTP 幂等键（绝不嵌入手机号、邮箱或用户 ID）。
 */
export function createIdempotencyKey(prefix = 'sec') {
  const cleanPrefix = String(prefix || 'sec').replace(/[^A-Za-z0-9_.:-]/g, '').slice(0, 16) || 'sec'
  if (typeof globalThis !== 'undefined' && globalThis.crypto?.randomUUID) {
    return `${cleanPrefix}-${globalThis.crypto.randomUUID()}`
  }
  const randA = Math.random().toString(36).slice(2, 10)
  const randB = Math.random().toString(36).slice(2, 10)
  return `${cleanPrefix}-${Date.now().toString(36)}-${randA}${randB}`
}

/**
 * 判断异常是否属于网络/超时/网关未知结果，仅此时保留 Idempotency-Key 供安全重试。
 */
export function shouldReuseIdempotencyKeyOnError(err) {
  const status = Number(err?.status ?? 0)
  if (status === 0) return true
  return status === 502 || status === 503 || status === 504
}
