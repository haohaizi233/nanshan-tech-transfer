import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
const source = readFileSync(new URL('../src/views/auth/RegisterView.vue', import.meta.url), 'utf8')
const validation = source.slice(source.indexOf('const validatePassword ='), source.indexOf('const submitUserRegistration ='))
const validate = vm.runInNewContext(validation + '; validatePassword')

test('registration waits before resending when the API returns a retry interval', async () => {
  const state = { requestSeq: 0, sending: false, countdown: 0, phone: '13800138000', challengeId: 'old', code: '012345' }
  const handler = source.slice(source.indexOf('const sendRegistrationCode ='), source.indexOf('const registrationProof ='))
  const send = vm.runInNewContext(handler + '; sendRegistrationCode', {
    mode: { value: 'user' },
    activeRegistration: () => ({ state, phone: '13800138000' }),
    submitting: { value: false },
    errorMessage: { value: '' },
    validatePhone: value => ({ ok: true, value }),
    clearChallenge: current => {
      current.requestSeq += 1
      current.challengeId = ''
      current.code = ''
    },
    api: async () => { throw Object.assign(new Error('请求过于频繁'), { retryAfter: 42 }) },
    startCountdown: (current, seconds) => { current.countdown = seconds },
  })
  await send()
  assert.equal(state.countdown, 42)
  assert.equal(state.sending, false)
  assert.equal(state.challengeId, 'old')
  assert.equal(state.code, '012345')
})
for (const length of [6, 7, 129]) {
  test(`registration rejects ${length} characters`, () => {
    const password = 'a'.repeat(length)
    assert.ok(validate({ username: 'test', password, confirmPassword: password }))
  })
}
for (const length of [8, 128]) {
  test(`registration accepts ${length} characters`, () => {
    const password = 'a'.repeat(length)
    assert.equal(validate({ username: 'test', password, confirmPassword: password }), '')
  })
}
