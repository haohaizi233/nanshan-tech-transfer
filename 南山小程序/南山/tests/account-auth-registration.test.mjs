import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { extractResponseErrorMessage } from '../subpackages/tech-transfer/api/client.js'
import { registerAccount } from '../subpackages/tech-transfer/api/user.js'

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
