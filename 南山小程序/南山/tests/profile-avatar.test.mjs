import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function userApi(overrides = {}) {
  let current = { userId: 7, version: 2 }
  const calls = []
  const bindings = {
    getCurrentUser: () => current,
    setCurrentUser: value => { current = value },
    validateEmail: value => ({ ok: true, value }),
    validatePhone: value => ({ ok: true, value }),
    getActiveMemberships: () => [],
    uploadContentFile: async path => { calls.push(['upload', path]); return { id: 9 } },
    apiRequest: async (...args) => { calls.push(args); return { ...current, avatar: '/files/9', avatarFileId: 9 } },
    uni: { showToast() {} },
    ...overrides,
  }
  const source = readFileSync(new URL('../subpackages/tech-transfer/api/user.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?\sfrom\s+['"][^'"]+['"];?/gm, '')
    .replace(/export /g, '')
  const api = new Function(...Object.keys(bindings), source + '\nreturn { saveUserProfile, getUserProfile, setInitialPassword }')(...Object.values(bindings))
  return { ...api, calls, setUser: value => { current = value } }
}

test('saving a selected temporary avatar uploads it and persists only the file id', async () => {
  const api = userApi()
  await api.saveUserProfile({ avatar: 'wxfile://tmp/avatar.png', avatarFileId: null, nickname: '昵称' })
  assert.deepEqual(api.calls[0], ['upload', 'wxfile://tmp/avatar.png'])
  assert.equal(api.calls[1][3].avatarFileId, 9)
  assert.equal(api.calls[1][3].avatar, undefined)
  assert.equal(api.getUserProfile().avatarFileId, 9)
})

test('unchanged avatar reuses its server file id instead of uploading its URL', async () => {
  const api = userApi()
  await api.saveUserProfile({ avatar: '/files/9', avatarFileId: 9, nickname: '昵称' })
  assert.equal(api.calls.length, 1)
  assert.equal(api.calls[0][3].avatarFileId, 9)
})

test('failed avatar uploads do not pretend the profile has been saved', async () => {
  const api = userApi({ uploadContentFile: async () => { throw new Error('network unavailable') } })
  assert.equal(await api.saveUserProfile({ avatar: 'blob:avatar', nickname: '昵称' }), null)
  assert.equal(api.calls.length, 0)
})

test('avatar upload completion cannot write a profile into a different account', async () => {
  let finish
  const api = userApi({ uploadContentFile: () => new Promise(resolve => { finish = resolve }) })
  const saving = api.saveUserProfile({ avatar: 'wxfile://tmp/avatar.png', nickname: '昵称' })
  api.setUser({ userId: 8, version: 1 })
  finish({ id: 9 })
  assert.equal(await saving, null)
  assert.equal(api.calls.length, 0)
})

test('avatar sheet is constrained to the H5 application viewport', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
  const sheet = source.match(/\.sheet-mask\s*\{([^}]+)/)[1]
  assert.match(sheet, /left:\s*var\(--window-left,\s*0px\)/)
  assert.match(sheet, /right:\s*var\(--window-right,\s*0px\)/)
})

test('initial password uses the same whitespace normalization as password login', async () => {
  const api = userApi()
  await api.setInitialPassword(' 12345678 ')
  assert.equal(api.calls[0][3].newPassword, '12345678')
  await assert.rejects(api.setInitialPassword(' short '), /8/)
  assert.equal(api.calls.length, 2)
})
