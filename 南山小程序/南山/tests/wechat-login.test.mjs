import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function clientRuntime(overrides = {}) {
  const storage = new Map()
  const requests = []
  const bindings = {
    HostBridge: {
      getStorage: key => storage.get(key),
      setStorage: (key, value) => storage.set(key, value),
      getEnvironment: () => ({ appEnv: 'production' }),
      request: async request => {
        requests.push(request)
        return { code: 0, data: { accessToken: 'access', refreshToken: 'refresh', expiresIn: 7200, user: { userId: 7 } } }
      },
      ...overrides,
    },
    uni: { login: options => options.success({ code: 'login-code' }) },
    TT_COMMON_40102: 'TT_COMMON_40102',
    TT_AUTH_40104: 'TT_AUTH_40104',
  }
  const source = readFileSync(new URL('../subpackages/tech-transfer/api/client.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?\sfrom\s+['"][^'"]+['"];?/gm, '').replace(/export /g, '')
  const api = new Function(...Object.keys(bindings), source + '\nreturn { authWechat, authLogout, ensureSession }')(...Object.values(bindings))
  return { ...api, storage, requests }
}

test('wechat login exchanges distinct login and phone codes without trusting client phone or openid', async () => {
  const api = clientRuntime()
  await api.authWechat('phone-code')
  assert.equal(api.requests[0].path, '/auth/wechat/login')
  assert.deepEqual(api.requests[0].body, { loginCode: 'login-code', phoneCode: 'phone-code' })
  assert.equal(api.storage.get('tt_auth_mode'), 'account')
  assert.equal(api.storage.get('tt_wechat_auto_login'), true)
})

test('explicit logout disables automatic wechat restoration', async () => {
  const api = clientRuntime()
  await api.authWechat('phone-code')
  await api.authLogout()
  await assert.rejects(api.ensureSession(), /未登录/)
  assert.equal(api.storage.get('tt_wechat_auto_login'), '')
})

test('a late wechat login response cannot undo explicit logout', async () => {
  let finish
  const api = clientRuntime({ request: () => new Promise(resolve => { finish = resolve }) })
  const login = api.authWechat('phone-code')
  await Promise.resolve()
  await api.authLogout()
  finish({ code: 0, data: { accessToken: 'late', user: { userId: 7 } } })
  await assert.rejects(login)
  assert.equal(api.storage.get('tt_access_token'), '')
})

test('silent restore does not request a new phone authorization', async () => {
  const api = clientRuntime()
  api.storage.set('tt_wechat_auto_login', true)
  assert.equal(await api.ensureSession(), true)
  assert.equal(api.requests[0].body.phoneCode, undefined)
})

test('concurrent requests share one silent wechat restoration', async () => {
  const api = clientRuntime()
  api.storage.set('tt_wechat_auto_login', true)
  assert.deepEqual(await Promise.all([api.ensureSession(), api.ensureSession(), api.ensureSession()]), [true, true, true])
  assert.equal(api.requests.length, 1)
})

test('a late refresh cannot restore a session after explicit logout', async () => {
  let finish
  const api = clientRuntime({ request: request => request.path === '/auth/refresh'
    ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ code: 0 }) })
  api.storage.set('tt_refresh_token', 'old-refresh')
  const restoring = api.ensureSession()
  await api.authLogout()
  finish({ code: 0, data: { accessToken: 'late-refresh', user: { userId: 7 } } })
  await assert.rejects(restoring)
  assert.equal(api.storage.get('tt_access_token'), '')
})
