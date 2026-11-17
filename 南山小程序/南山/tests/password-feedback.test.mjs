import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const user = readFileSync(new URL('../subpackages/tech-transfer/api/user.js', import.meta.url), 'utf8')
const mine = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')

test('password POST success is not replaced by an expired-token profile request', async () => {
  const source = user.slice(user.indexOf('export async function changePassword('), user.indexOf('/** 获取安全中心概要'))
  const calls = []
  const fn = new Function('apiRequest', 'getCurrentUser', 'setCurrentUser', `${source.replace('export ', '')}; return changePassword`)(
    async (method, path) => {
      calls.push(path)
      if (method === 'GET') throw new Error('旧Token已失效')
      return { message: '密码修改成功' }
    }, () => ({ userId: 1 }), () => {},
  )
  assert.deepEqual(await fn('old-password', 'new-password'), { message: '密码修改成功' })
  assert.deepEqual(calls, ['/me/password'])
})

function submit(overrides = {}) {
  const start = mine.indexOf('async submitChangePassword()')
  const source = mine.slice(start, mine.indexOf('async onRevokeAllSessions()', start)).trim().replace(/,$/, '')
  const modals = []
  const method = new Function('changePassword', 'setInitialPassword', 'logout', 'uni', `return ({${source}}).submitChangePassword`)(
    overrides.changePassword || (async () => ({})), async () => ({}), async () => {},
    { showToast() {}, showModal: modal => modals.push(modal) },
  )
  const ctx = { passwordBusy: false, isSettingInitial: false, pwdModalCurrent: 'old-password',
    pwdModalNew: 'new-password', pwdModalConfirm: 'new-password', passwordError: '', authForm: {password:'old-password'},
    closePasswordModal() {}, refresh() { throw new Error('must not refresh with revoked token') }, ...overrides }
  return { ctx, modals, run: () => method.call(ctx) }
}

test('failed submission keeps a visible inline error', async () => {
  const task = submit({ changePassword: async () => { throw new Error('当前密码不正确') } })
  await task.run()
  assert.equal(task.ctx.passwordError, '当前密码不正确')
  assert.equal(task.ctx.passwordBusy, false)
})

test('successful submission acknowledges success and clears password fields', async () => {
  const task = submit()
  await task.run()
  assert.equal(task.modals[0]?.title, '密码修改成功')
  assert.equal(task.ctx.pwdModalNew, '')
  assert.equal(task.ctx.pwdModalCurrent, '')
  await task.modals[0].success()
  assert.equal(task.ctx.viewMode, 'auth')
  assert.equal(task.ctx.authForm.password, '')
})

test('an in-flight submission cannot trigger another request', async () => {
  let calls = 0
  const task = submit({ passwordBusy: true, changePassword: async () => { calls++ } })
  await task.run()
  assert.equal(calls, 0)
})
