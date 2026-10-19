import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as cache from '../subpackages/tech-transfer/api/page-state-cache.mjs'
import { toDemandCard } from '../subpackages/tech-transfer/api/demand.js'

function loadPage(name, overrides = {}) {
  const values = new Map([
    ['tt_auth_mode', 'account'],
    ['tt_current_user', { userId: 7 }],
  ])
  const storage = {
    getStorageSync: key => values.get(key),
    setStorageSync: (key, value) => values.set(key, value),
    removeStorageSync: key => values.delete(key),
    getStorageInfoSync: () => ({ keys: [...values.keys()] }),
  }
  const bindings = {
    ...cache,
    getPageStateScope: () => cache.getPageStateScope(storage),
    invalidatePageStateKeys: keys => cache.invalidatePageStateKeys(keys, '7', storage),
    createPageStateMixin: options => cache.createPageStateMixin({ ...options, storage, scope: () => '7' }),
    AI_FEATURE_ENABLED: true,
    HostBridge: { getStorage: () => 'test-session' },
    uni: { stopPullDownRefresh() {} },
    toDemandCard,
    ...overrides,
  }
  const source = readFileSync(new URL(`../subpackages/tech-transfer/pages/${name}/${name}.vue`, import.meta.url), 'utf8')
  const script = source.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/^\s*import[\s\S]*?\sfrom\s+['"][^'"]+['"];?/gm, '')
    .replace('export default', 'return')
  const component = new Function(...Object.keys(bindings), script)(...Object.values(bindings))
  const page = component.data()
  page.$data = page
  for (const mixin of component.mixins) Object.assign(page, mixin.methods)
  Object.assign(page, component.methods)
  return { component, page, storage }
}

test('opening a recently cached favorite list fetches the new cards immediately', async () => {
  const { component, page } = loadPage('my-list', {
    getMyFavorites: async type => ({ list: type === 'demand' ? [{
      targetId: 42, targetSummary: { title: '新收藏', status: 'published', desc: '新内容' },
    }] : [] }),
  })
  page.pageType = 'favorite'
  component.mixins[0].onLoad.call(page, { type: 'favorite' })
  page.listContext = page.currentListContext()
  page.markPageStateFresh('list')
  assert.equal(page.shouldRevalidatePageState('list'), false)
  await component.onShow.call(page)
  assert.equal(page.list[0]?._title, '新收藏')
})

test('dock refresh replaces a cached pending status with the published owner action', async () => {
  const { component, page } = loadPage('dock-detail', {
    getDemandDetail: async () => ({ id: 42, title: '已审核', status: 'published', isMine: true, version: 2 }),
  })
  component.mixins[0].onLoad.call(page, { id: 42, type: 'demand' })
  page.detail = { id: 42, status: 'pending_review', isMine: true }
  page.markPageStateFresh('detail')
  page.loadIntent = async () => {}
  assert.equal(component.computed.actionMode.call(page), 'blocked')
  await page.refreshDockState(42)
  assert.equal(component.computed.actionMode.call(page), 'offline')
  assert.equal(page.detail.version, 2)
})

test('automatic intent polling reuses fresh details while still updating cooperation state', async () => {
  let detailReads = 0
  let intentReads = 0
  const { component, page } = loadPage('dock-detail', {
    getDemandDetail: async () => {
      detailReads++
      return { id: 42, status: 'published', isMine: true }
    },
  })
  component.mixins[0].onLoad.call(page, { id: 42, type: 'demand' })
  page.detail = { id: 42, status: 'published', isMine: true }
  page.markPageStateFresh('detail')
  page.loadIntent = async () => { intentReads++ }
  await page.refreshDockState(42, { force: false })
  assert.equal(detailReads, 0)
  assert.equal(intentReads, 1)
})

test('favorite list pull refresh fetches cards and always stops the indicator', async () => {
  let stopped = 0
  const { component, page } = loadPage('my-list', {
    getMyFavorites: async type => ({ list: type === 'result' ? [{
      targetId: 43, targetSummary: { title: '刷新后的成果', status: 'published' },
    }] : [] }),
    uni: { stopPullDownRefresh() { stopped++ } },
  })
  page.pageType = 'favorite'
  component.mixins[0].onLoad.call(page, { type: 'favorite' })
  await component.onPullDownRefresh.call(page)
  assert.equal(page.list[0]?._title, '刷新后的成果')
  assert.equal(stopped, 1)
})

test('dock pull refresh stops the indicator even when revalidation fails', async () => {
  let stopped = 0
  const { component, page } = loadPage('dock-detail', {
    uni: { stopPullDownRefresh() { stopped++ } },
  })
  page.loadedId = 42
  page.refreshDockState = async () => { throw new Error('offline') }
  await assert.rejects(() => component.onPullDownRefresh.call(page), /offline/)
  assert.equal(stopped, 1)
})

test('removing a favorite from the list invalidates the personal-center count', async () => {
  const { page, storage } = loadPage('my-list', {
    removeFavorite: async () => null,
    uni: { showToast() {} },
  })
  page.loadList = async () => {}
  const key = 'pages/mine/mine:dashboard'
  cache.writePageState(key, '7', 'list', { favoriteDemandCount: 1 }, storage)
  await page.onRemoveFavorite({ _type: 'demand', id: 42 })
  assert.equal(cache.readPageState(key, '7', 'list', storage), null)
})

test('an older favorite response cannot restore a card after its removal', async () => {
  let resolveOlder
  let demandReads = 0
  const { component, page } = loadPage('my-list', {
    getMyFavorites: type => {
      if (type === 'demand' && ++demandReads === 1) {
        return new Promise(resolve => { resolveOlder = resolve })
      }
      return Promise.resolve({ list: [] })
    },
    removeFavorite: async () => null,
    uni: { showToast() {} },
  })
  page.pageType = 'favorite'
  component.mixins[0].onLoad.call(page, { type: 'favorite' })
  const older = component.onShow.call(page)
  await page.onRemoveFavorite({ _type: 'demand', id: 42 })
  assert.deepEqual(page.list, [])
  resolveOlder({ list: [{ targetId: 42, targetSummary: { title: '已取消的收藏', status: 'published' } }] })
  await older
  assert.deepEqual(page.list, [])
})

for (const change of ['filter', 'account']) {
  test(`a favorite response is discarded after the ${change} changes`, async () => {
    let resolveResponse
    const { page, storage } = loadPage('my-list', {
      getMyFavorites: type => type === 'demand'
        ? new Promise(resolve => { resolveResponse = resolve })
        : Promise.resolve({ list: [] }),
    })
    page.pageType = 'favorite'
    const pending = page.loadList()
    if (change === 'filter') page.pageType = 'result'
    else storage.setStorageSync('tt_current_user', { userId: 8 })
    resolveResponse({ list: [{ targetId: 42, targetSummary: { title: '旧页面内容', status: 'published' } }] })
    await pending
    assert.deepEqual(page.list, [])
  })
}
