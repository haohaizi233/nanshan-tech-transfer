/** Shared phone / email format checks for admin profile, register, and capital forms. */

export const PHONE_PATTERN = /^\d{11}$/
export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
export const CONTACT_WAY_PATTERN = /^[\d+() （）\s-]{5,32}$/

export function normalizeContact(value) {
  return String(value == null ? '' : value).trim()
}

export function isValidPhone(value) {
  const text = normalizeContact(value)
  return PHONE_PATTERN.test(text)
}

export function isValidEmail(value) {
  const text = normalizeContact(value)
  return EMAIL_PATTERN.test(text)
}

export function validatePhone(value, { required = false, label = '手机号' } = {}) {
  const text = normalizeContact(value)
  if (!text) {
    return required ? { ok: false, message: `请填写${label}` } : { ok: true, value: '' }
  }
  if (!PHONE_PATTERN.test(text)) {
    return { ok: false, message: `${label}须为11位数字` }
  }
  return { ok: true, value: text }
}

export function validateEmail(value, { required = false, label = '邮箱' } = {}) {
  const text = normalizeContact(value)
  if (!text) {
    return required ? { ok: false, message: `请填写${label}` } : { ok: true, value: '' }
  }
  if (!EMAIL_PATTERN.test(text)) {
    return { ok: false, message: `${label}格式不正确` }
  }
  return { ok: true, value: text }
}

export function isValidContactWay(value) {
  const text = normalizeContact(value)
  return CONTACT_WAY_PATTERN.test(text)
}

export function validateContactWay(value, { required = false, label = '联系方式' } = {}) {
  const text = normalizeContact(value)
  if (!text) {
    return required ? { ok: false, message: `请填写${label}` } : { ok: true, value: '' }
  }
  if (text.length > 64 || !CONTACT_WAY_PATTERN.test(text)) {
    return { ok: false, message: `${label}格式不正确` }
  }
  return { ok: true, value: text }
}
