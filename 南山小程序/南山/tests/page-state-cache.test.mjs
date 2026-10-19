import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  clearPageStateScope,
  cancelAllPageStateWrites,
  createPageStateMixin,
  invalidatePageState,
  invalidatePageStateKeys,
  PAGE_STATE_STALE_RETENTION,
  PAGE_STATE_TTL,
  readPageState,
  writePageState,
  schedulePageStateWrite,
} from '../subpackages/tech-transfer/api/page-state-cache.mjs'

function createStorage() {
  const values = new Map()
  return {
    values,
    getStorageSync: key => values.get(key),
    setStorageSync: (key, value) => values.set(key, value),
    removeStorageSync: key => values.delete(key),
    getStorageInfoSync: () => ({ keys: [...values.keys()] }),
  }
}

test('page cache marks list, detail, dictionary and draft entries with their own TTLs', () => {
  const storage = createStorage()
  writePageState('home', 'u1', 'list', { count: 1 }, storage, 10_000)
  writePageState('detail/7', 'u1', 'detail', { id: 7 }, storage, 10_000)
  writePageState('categories', 'u1', 'dictionary', ['x'], storage, 10_000)
  writePageState('draft/result', 'u1', 'draft', { title: 'x' }, storage, 10_000)
  assert.equal(readPageState('home', 'u1', 'list', storage, 129_999).fresh, true)
  assert.equal(readPageState('home', 'u1', 'list', storage, 130_001).fresh, false)
  assert.equal(readPageState('detail/7', 'u1', 'detail', storage, 309_999).fresh, true)
  assert.equal(readPageState('categories', 'u1', 'dictionary', storage, 1_809_999).fresh, true)
  assert.equal(readPageState('draft/result', 'u1', 'draft', storage, 86_409_999).fresh, true)
})

test('expired and malformed entries are removed and treated as a cache miss', () => {
  const storage = createStorage()
  writePageState('list', 'u1', 'list', [1], storage, 0)
  assert.equal(readPageState('list', 'u1', 'list', storage, 120_001).stale, true)
  assert.equal(readPageState('list', 'u1', 'list', storage, 120_001 + PAGE_STATE_STALE_RETENTION), null)
  writePageState('broken', 'u1', 'list', [1], storage, 0)
  const brokenKey = [...storage.values.keys()].find(key => key.includes('broken'))
  storage.values.set(brokenKey, { version: -1 })
  assert.equal(readPageState('broken', 'u1', 'list', storage, 1), null)
  assert.equal(storage.values.has(brokenKey), false)
})

test('re-saving a stale snapshot does not extend its stale-retention window', () => {
  const storage = createStorage()
  const validatedAt = 1_000
  writePageState('list', 'u1', 'list', { items: [], __pageCacheValidatedAt: validatedAt }, storage, validatedAt)
  const reSavedAt = validatedAt + PAGE_STATE_TTL.list + 60_000
  writePageState('list', 'u1', 'list', { items: [], __pageCacheValidatedAt: validatedAt }, storage, reSavedAt)
  assert.equal(readPageState('list', 'u1', 'list', storage, reSavedAt).stale, true)
  assert.equal(readPageState('list', 'u1', 'list', storage,
    validatedAt + PAGE_STATE_TTL.list + PAGE_STATE_STALE_RETENTION + 1), null)
})

test('anonymous and different user namespaces never share page state', () => {
  const storage = createStorage()
  writePageState('mine', 'u1', 'list', ['private'], storage, 1)
  assert.equal(readPageState('mine', 'u2', 'list', storage, 2), null)
  assert.equal(readPageState('mine', '', 'list', storage, 2), null)
})

test('invalidation removes only the selected page in the selected account scope', () => {
  const storage = createStorage()
  writePageState('home', 'u1', 'list', [1], storage, 1)
  writePageState('home', 'u2', 'list', [2], storage, 1)
  writePageState('search', 'u1', 'list', [3], storage, 1)
  invalidatePageState('home', 'u1', storage)
  assert.equal(readPageState('home', 'u1', 'list', storage, 2), null)
  assert.deepEqual(readPageState('home', 'u2', 'list', storage, 2).value, [2])
  assert.deepEqual(readPageState('search', 'u1', 'list', storage, 2).value, [3])
})

test('prefix invalidation removes dynamic detail keys without touching other pages', () => {
  const storage = createStorage()
  writePageState('pages/detail/detail:1', 'u1', 'detail', { id: 1 }, storage, 1)
  writePageState('pages/detail/detail:2', 'u1', 'detail', { id: 2 }, storage, 1)
  writePageState('pages/home/home:list', 'u1', 'list', [1], storage, 1)
  invalidatePageState('pages/detail/detail:*', 'u1', storage)
  assert.equal(readPageState('pages/detail/detail:1', 'u1', 'detail', storage, 2), null)
  assert.equal(readPageState('pages/detail/detail:2', 'u1', 'detail', storage, 2), null)
  assert.deepEqual(readPageState('pages/home/home:list', 'u1', 'list', storage, 2).value, [1])
})

test('prefix invalidation cancels pending writes for matching page keys', async () => {
  const storage = createStorage()
  schedulePageStateWrite('pages/detail/detail:3', 'u1', 'detail', { id: 3 }, 20, storage)
  invalidatePageState('pages/detail/detail:*', 'u1', storage)
  await new Promise(resolve => setTimeout(resolve, 35))
  assert.equal(readPageState('pages/detail/detail:3', 'u1', 'detail', storage), null)
})

test('business invalidation removes parameterized lists without touching other groups or accounts', () => {
  const storage = createStorage()
  const key = 'pages/my-list/my-list:list'
  for (const suffix of ['', ':type=favorite', ':type=demand']) {
    writePageState(key + suffix, 'u1', 'list', { list: ['old'] }, storage)
  }
  writePageState(key + ':type=favorite', 'u2', 'list', { list: ['other user'] }, storage)
  writePageState(key + 'Extra', 'u1', 'list', { list: ['other group'] }, storage)
  invalidatePageStateKeys([key], 'u1', storage)
  for (const suffix of ['', ':type=favorite', ':type=demand']) {
    assert.equal(readPageState(key + suffix, 'u1', 'list', storage), null)
  }
  assert.deepEqual(readPageState(key + ':type=favorite', 'u2', 'list', storage).value.list, ['other user'])
  assert.deepEqual(readPageState(key + 'Extra', 'u1', 'list', storage).value.list, ['other group'])
})

test('business invalidation cancels queued writes of parameterized pages', async () => {
  const storage = createStorage()
  const key = 'pages/my-list/my-list:list:type=favorite'
  schedulePageStateWrite(key, 'u1', 'list', { list: ['old'] }, 20, storage)
  invalidatePageStateKeys(['pages/my-list/my-list:list'], 'u1', storage)
  await new Promise(resolve => setTimeout(resolve, 35))
  assert.equal(readPageState(key, 'u1', 'list', storage), null)
})

test('H5 localStorage fallback can invalidate parameterized pages', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const values = new Map()
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
    get length() { return values.size },
    key: index => [...values.keys()][index] ?? null,
  } })
  try {
    const key = 'pages/my-list/my-list:list:type=favorite'
    writePageState(key, 'u1', 'list', { list: ['old'] })
    assert.ok(readPageState(key, 'u1', 'list'))
    invalidatePageStateKeys(['pages/my-list/my-list:list'], 'u1')
    assert.equal(readPageState(key, 'u1', 'list'), null)
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor)
    else delete globalThis.localStorage
  }
})

test('scope clearing preserves all other accounts', () => {
  const storage = createStorage()
  writePageState('mine', 'u1', 'list', [1], storage, 1)
  writePageState('mine', 'u2', 'list', [2], storage, 1)
  clearPageStateScope('u1', storage)
  assert.equal(readPageState('mine', 'u1', 'list', storage, 2), null)
  assert.deepEqual(readPageState('mine', 'u2', 'list', storage, 2).value, [2])
})

test('scope clearing cancels delayed writes so logout cannot recreate cache entries', async () => {
  const storage = createStorage()
  schedulePageStateWrite('mine', 'u1', 'draft', { form: { title: 'private' } }, 20, storage)
  clearPageStateScope('u1', storage)
  await new Promise(resolve => setTimeout(resolve, 35))
  assert.equal(readPageState('mine', 'u1', 'draft', storage), null)
  cancelAllPageStateWrites()
})

test('write removes local temporary paths while retaining uploaded remote URLs', () => {
  const storage = createStorage()
  assert.equal(writePageState('draft', 'u1', 'draft', {
    file: { tempFilePath: 'wxfile://tmp/image.png', url: 'https://cdn.example/image.png' },
  }, storage, 1), true)
  assert.deepEqual(readPageState('draft', 'u1', 'draft', storage, 2).value, {
    file: { url: 'https://cdn.example/image.png' },
  })
})

test('storage failures fall back safely without throwing or returning unsaved data', () => {
  const storage = {
    getStorageSync() { throw new Error('unavailable') },
    setStorageSync() { throw new Error('full') },
    removeStorageSync() { throw new Error('unavailable') },
    getStorageInfoSync() { throw new Error('unavailable') },
  }
  assert.equal(writePageState('x', 'u1', 'list', [1], storage, 1), false)
  assert.equal(readPageState('x', 'u1', 'list', storage, 2), null)
  assert.doesNotThrow(() => invalidatePageState('x', 'u1', storage))
  assert.doesNotThrow(() => clearPageStateScope('u1', storage))
})

test('cache refuses oversized or sensitive payloads', () => {
  const storage = createStorage()
  assert.equal(writePageState('huge', 'u1', 'draft', { text: 'x'.repeat(300_000) }, storage, 1), false)
  assert.equal(writePageState('secret', 'u1', 'draft', { accessToken: 'secret' }, storage, 1), false)
})

test('page mixin restores data before the page fetch and keys details by route params', () => {
  const storage = createStorage()
  const scope = () => 'u1'
  const mixin = createPageStateMixin({
    route: 'pages/detail/detail',
    groups: [{ name: 'detail', dataClass: 'detail', fields: ['id', 'detail'] }],
    scope,
    storage,
  })
  const first = { $data: { id: '', detail: null }, id: '', detail: null }
  Object.assign(first, mixin.methods)
  mixin.onLoad.call(first, { id: 7 })
  first.id = 7
  first.detail = { id: 7, title: 'cached' }
  first.markPageStateFresh('detail')
  mixin.onHide.call(first)

  const restored = { $data: { id: '', detail: null }, id: '', detail: null }
  Object.assign(restored, mixin.methods)
  mixin.onLoad.call(restored, { id: 7 })
  assert.deepEqual(restored.detail, { id: 7, title: 'cached' })
  assert.equal(restored.hasRestoredPageState('detail'), true)
  assert.equal(restored.shouldRevalidatePageState('detail'), false)

  const other = { $data: { id: '', detail: null }, id: '', detail: null }
  Object.assign(other, mixin.methods)
  mixin.onLoad.call(other, { id: 8 })
  assert.equal(other.detail, null)
})

test('page mixin resets in-memory user data when the active account changes', () => {
  const storage = createStorage()
  let currentUser = 'u1'
  const mixin = createPageStateMixin({
    route: 'pages/mine/mine',
    groups: [{ name: 'profile', dataClass: 'detail', fields: ['profile'] }],
    scope: () => currentUser,
    storage,
  })
  const page = {
    $data: { profile: null },
    $options: { data: () => ({ profile: { owner: currentUser } }) },
    profile: null,
  }
  Object.assign(page, mixin.methods)
  mixin.onLoad.call(page, {})
  page.profile = { owner: 'u1' }
  currentUser = 'u2'
  mixin.onShow.call(page)
  assert.deepEqual(page.profile, { owner: 'u2' })
  assert.equal(page.hasRestoredPageState('profile'), false)
})

test('page mixin schedules draft persistence and flushes it synchronously on hide', () => {
  const storage = createStorage()
  const mixin = createPageStateMixin({
    route: 'pages/post-result/post-result',
    groups: [{ name: 'draft', dataClass: 'draft', fields: ['form'] }],
    scope: () => 'u1',
    storage,
  })
  const page = { $data: { form: { title: '' } }, form: { title: '' } }
  Object.assign(page, mixin.methods)
  mixin.onLoad.call(page, {})
  page.form.title = 'draft title'
  mixin.watch.form.handler.call(page)
  mixin.onHide.call(page)
  const restored = { $data: { form: { title: '' } }, form: { title: '' } }
  Object.assign(restored, mixin.methods)
  mixin.onLoad.call(restored, {})
  assert.deepEqual(restored.form, { title: 'draft title' })
})

test('cleared drafts are not recreated by the page hide hook after successful submission', () => {
  const storage = createStorage()
  const mixin = createPageStateMixin({
    route: 'pages/post-result/post-result',
    groups: [{ name: 'draft', dataClass: 'draft', fields: ['form'] }],
    scope: () => 'u1',
    storage,
  })
  const page = { $data: { form: { title: '' } }, form: { title: 'submitted' } }
  Object.assign(page, mixin.methods)
  mixin.onLoad.call(page, {})
  page.clearPageState('draft')
  mixin.onHide.call(page)
  assert.equal(readPageState('pages/post-result/post-result:draft', 'u1', 'draft', storage), null)
})
