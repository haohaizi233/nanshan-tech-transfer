import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const frontend = readFileSync(new URL('../src/views/auth/ForgotPasswordView.vue', import.meta.url), 'utf8')
const mini = readFileSync(new URL('../../南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')

test('recovery screens describe request acceptance without claiming delivery or exposing eligibility', () => {
const recoveryTemplate = mini.slice(mini.indexOf('<!-- 弹窗 3：找回密码 -->'), mini.indexOf('<!-- 弹窗 4:', mini.indexOf('<!-- 弹窗 3：找回密码 -->')))
  for (const source of [frontend, recoveryTemplate]) {
    assert.match(source, /验证请求已提交/)
    assert.match(source, /如果账号存在/)
  }
  assert.doesNotMatch(recoveryTemplate, /已发送验证码至/)
  assert.doesNotMatch(mini, /若账号已绑定有效联系方式，验证信息已发送/)
  assert.doesNotMatch(frontend, /重置链接已发送/)
  assert.doesNotMatch(frontend, /系统已向该邮箱派发/)
})

test('recovery countdown is presented as a retry cooldown', () => {
  assert.match(frontend, /秒后可重新提交请求/)
  assert.match(mini, /秒后可重新提交请求/)
})
