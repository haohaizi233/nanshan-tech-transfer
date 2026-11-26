import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

import { extractResponseErrorMessage } from '../subpackages/tech-transfer/api/client.js'
import { getRecoveryCapabilities, registerAccount, startRegistrationChallenge } from '../subpackages/tech-transfer/api/user.js'
import HostBridge from '../host/host-bridge.js'

test('registration sends the phone to the public SMS challenge endpoint', async context => {
  const challenge = { challengeId: 'registration-test', cooldownSeconds: 60 }
  context.mock.method(HostBridge, 'request', async ({ method, path, body }) => {
    assert.equal(method, 'POST')
    assert.equal(path, '/auth/register/challenge')
    assert.deepEqual(body, { phone: '13800138000' })
    return { code: 0, data: challenge }
  })
  assert.deepEqual(await startRegistrationChallenge('13800138000'), challenge)
})

test('password recovery loads capabilities through the public endpoint', async context => {
  const capabilities = { sms: true }
  context.mock.method(HostBridge, 'request', async ({ method, path }) => {
    assert.equal(method, 'GET')
    assert.equal(path, '/auth/recovery/capabilities')
    return { code: 0, data: capabilities }
  })
  assert.deepEqual(await getRecoveryCapabilities(), capabilities)
})

test('password and WeChat authentication cannot submit while the other is in flight', async () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
  const wechat = source.slice(source.indexOf('async onWechatLogin('), source.indexOf('onWechatPhone(event)'))
  const password = source.slice(source.indexOf('async onAuthSubmit('), source.indexOf('fillForm(profile) {', source.indexOf('async onAuthSubmit(')))
  const loginWithWechat = test.mock.fn(async () => ({ ok: false }))
  const loginAccount = test.mock.fn(async () => ({ ok: false }))
  const methods = vm.runInNewContext(`({${wechat}${password}})`, {
    isLoggedIn: () => false,
    loginWithWechat,
    loginAccount,
    uni: { showToast() {}, showLoading() {}, hideLoading() {} },
  })
  const state = {
    authBusy: true, wechatBusy: false, registrationSending: false, authMode: 'login',
    authForm: { phone: '13800138000', password: 'password' },
  }
  await methods.onWechatLogin.call(state)
  await methods.onAuthSubmit.call({ ...state, authBusy: false, wechatBusy: true })
  assert.equal(loginWithWechat.mock.callCount(), 0)
  assert.equal(loginAccount.mock.callCount(), 0)
})

test('extractResponseErrorMessage extracts details string over generic message', () => {
  const res = {
    code: 'TT_COMMON_40001',
    message: '请求参数无效',
    details: '密码至少8位',
    requestId: 'req_123',
  }
  assert.equal(extractResponseErrorMessage(res), '密码至少8位')
})

test('extractResponseErrorMessage extracts field validation message from details array', () => {
  const res = {
    code: 'TT_COMMON_42201',
    message: '请求参数校验失败',
    details: [{ field: 'password', message: '密码至少8位' }],
  }
  assert.equal(extractResponseErrorMessage(res), '密码至少8位')
})

test('extractResponseErrorMessage keeps specific business error message', () => {
  const res = {
    code: 'TT_AUTH_40901',
    message: '该手机号已注册，请直接登录',
  }
  assert.equal(extractResponseErrorMessage(res), '该手机号已注册，请直接登录')
})

test('registerAccount validates password length >= 8 before network request', async () => {
  const resShort = await registerAccount('13800138000', '123456')
  assert.equal(resShort.ok, false)
  assert.equal(resShort.message, '密码至少8位')

  const resEmpty = await registerAccount('13800138000', '')
  assert.equal(resEmpty.ok, false)
  assert.equal(resEmpty.message, '请输入密码')
})

test('mine.vue template uses 8-digit password placeholder and maxlength', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
  assert.match(source, /设置密码（至少8位）/)
  assert.doesNotMatch(source, /设置密码（至少6位）/)
})

test('switching between registration and login masks a revealed password without changing it', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
  const start = source.indexOf('toggleAuthMode() {')
  const end = source.indexOf('onAuthInput(key, e) {', start)
  const { toggleAuthMode } = vm.runInNewContext(`({${source.slice(start, end)}})`)
  const state = {
    authMode: 'register',
    authPasswordVisible: true,
    authForm: { password: 'example-password' },
    resetRegistrationChallenge() {},
  }
  toggleAuthMode.call(state)
  assert.equal(state.authMode, 'login')
  assert.equal(state.authPasswordVisible, false)
  assert.equal(state.authForm.password, 'example-password')
})

test('failed registration resend preserves the current challenge and code', async () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
  const start = source.indexOf('async sendRegistrationCode() {')
  const end = source.indexOf('toggleAuthMode() {', start)
  const { sendRegistrationCode } = vm.runInNewContext(`({${source.slice(start, end)}})`, {
    validatePhone: value => ({ ok: true, value }),
    startRegistrationChallenge: async () => { throw new Error('网络连接失败') },
  })
  const state = {
    authForm: { phone: '13800138000' },
    registrationRequestSeq: 0, registrationChallengeId: 'old', registrationCode: '012345',
    resetRegistrationChallenge() {
      this.registrationRequestSeq++
      this.registrationChallengeId = ''
      this.registrationCode = ''
    },
  }
  await sendRegistrationCode.call(state)
  assert.equal(state.registrationChallengeId, 'old')
  assert.equal(state.registrationCode, '012345')
  assert.equal(state.registrationSending, false)
})
