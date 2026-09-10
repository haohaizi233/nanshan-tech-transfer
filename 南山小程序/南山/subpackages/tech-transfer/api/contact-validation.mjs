/** Shared phone / email format checks for publication, profile, and org forms. */

export const PHONE_PATTERN = /^\d{11}$/
export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

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
