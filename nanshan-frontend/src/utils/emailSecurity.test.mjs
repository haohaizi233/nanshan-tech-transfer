import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  STEP_UP_METHOD_LABELS,
  createIdempotencyKey,
  sanitizeOtpCode,
  parseResetCredentialsFromLocation,
  normalizeRecoveryCapabilities,
  resolveRetryAfterSeconds,
  shouldReuseIdempotencyKeyOnError,
} from './emailSecurity.js'

test('sanitizeOtpCode preserves leading zeros and strips non-digits', () => {
  assert.equal(sanitizeOtpCode('007412'), '007412')
  assert.equal(sanitizeOtpCode(' 01a2b3c4d567 '), '012345')
  assert.equal(sanitizeOtpCode(null), '')
})

test('parseResetCredentialsFromLocation prioritizes URL fragment and falls back to query', () => {
  const fromHash = parseResetCredentialsFromLocation({
    hash: '#challengeId=99&token=hash-secret-token',
    query: { challengeId: '11', token: 'query-token' },
  })
  assert.deepEqual(fromHash, { challengeId: '99', token: 'hash-secret-token' })

  const fromQueryFallback = parseResetCredentialsFromLocation({
    hash: '',
    query: { challengeId: '11', token: 'query-token' },
  })
  assert.deepEqual(fromQueryFallback, { challengeId: '11', token: 'query-token' })
})

test('normalizeRecoveryCapabilities picks enabled default channel safely', () => {
  const allOff = normalizeRecoveryCapabilities({ sms: false, emailOtp: false, emailLink: false })
  assert.equal(allOff.hasAny, false)
  assert.equal(allOff.defaultChannel, '')

  const emailOnly = normalizeRecoveryCapabilities({
    sms: false,
    emailOtp: false,
    emailLink: true,
    cooldownSeconds: 90,
  })
  assert.equal(emailOnly.hasAny, true)
  assert.equal(emailOnly.defaultChannel, 'email_link')
  assert.equal(emailOnly.cooldownSeconds, 90)
})

test('resolveRetryAfterSeconds bounds retry countdown safely', () => {
  assert.equal(resolveRetryAfterSeconds({ retryAfter: '45' }), 45)
  assert.equal(resolveRetryAfterSeconds({ details: { retryAfter: 99999 } }), 3600)
  assert.equal(resolveRetryAfterSeconds({}, 60), 60)
})

test('STEP_UP_METHOD_LABELS defines all supported methods', () => {
  assert.ok(STEP_UP_METHOD_LABELS.password)
  assert.ok(STEP_UP_METHOD_LABELS.old_email_otp)
  assert.ok(STEP_UP_METHOD_LABELS.old_phone_otp)
  assert.ok(STEP_UP_METHOD_LABELS.recent_auth)
})

test('ResetPasswordView does not verify link in onMounted and strips URL state', () => {
  const vueSrc = readFileSync(new URL('../views/auth/ResetPasswordView.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(vueSrc, /onMounted[\s\S]*verifyPasswordRecovery/)
  assert.match(vueSrc, /replaceState/)
  assert.match(vueSrc, /parseResetCredentialsFromLocation/)
})

test('createIdempotencyKey generates opaque ASCII keys without PII', () => {
  const k1 = createIdempotencyKey('rec')
  const k2 = createIdempotencyKey('rec')
  assert.notEqual(k1, k2)
  assert.match(k1, /^rec-[A-Za-z0-9_.:-]{12,120}$/)
  assert.doesNotMatch(k1, /@/)
})

test('shouldReuseIdempotencyKeyOnError reuses key only for transient network or gateway errors', () => {
  assert.equal(shouldReuseIdempotencyKeyOnError({ status: 0 }), true)
  assert.equal(shouldReuseIdempotencyKeyOnError({ status: 503 }), true)
  assert.equal(shouldReuseIdempotencyKeyOnError({ status: 504 }), true)
  assert.equal(shouldReuseIdempotencyKeyOnError({ status: 400 }), false)
  assert.equal(shouldReuseIdempotencyKeyOnError({ status: 409 }), false)
  assert.equal(shouldReuseIdempotencyKeyOnError({ status: 429 }), false)
})
