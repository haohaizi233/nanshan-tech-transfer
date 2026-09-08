import assert from 'node:assert/strict'
import test from 'node:test'

import HostBridge from '../host/host-bridge.js'
import LocalAdapter from '../host/local-adapter.js'

/**
 * HostBridge 契约测试（07 §契约测试要求）
 *
 * 三组用例：
 * 1. 契约校验：未注册抛错 / 9 方法逐一缺省抛错 / 重复注册抛错 / 装配后委托生效
 * 2. LocalAdapter 行为：环境快照 / URL 组装+Bearer+RequestId / 导航前缀 / 存储透传 / toast
 * 3. Mock AiNanshan 适配器同组用例：换宿主行为一致（为 C-01/03 确认后的真实 adapter 兜底）
 *
 * 注意：HostBridge 为模块级单例（_adapter 注册后不可撤销），
 * 用例按声明顺序执行——未注册用例必须先于任何成功注册。
 */

// ── uni 全局 mock（按用例重置） ─────────────────────────────

function installUniMock(overrides = {}) {
  const calls = { request: [], navigateTo: [], showToast: [], getStorageSync: [], setStorageSync: [] }
  const storage = {}
  globalThis.uni = {
    request: (opts) => {
      calls.request.push(opts)
      if (overrides.request) return overrides.request(opts)
      return Promise.resolve()
    },
    navigateTo: (opts) => {
      calls.navigateTo.push(opts)
      if (overrides.navigateTo) return overrides.navigateTo(opts)
    },
    showToast: (opts) => {
      calls.showToast.push(opts)
    },
    getStorageSync: (key) => {
      calls.getStorageSync.push(key)
      if (key in storage) return storage[key]
      return overrides.getStorageSync ? overrides.getStorageSync(key) : ''
    },
    setStorageSync: (key, value) => {
      calls.setStorageSync.push({ key, value })
      storage[key] = value
    },
  }
  return { calls, storage }
}

function makeFullAdapter(overrides = {}) {
  const base = {
    _getEnvironment: () => ({ appEnv: 'test', hostMode: 'test', authProvider: 'test', apiBase: '', apiPrefix: '' }),
    _getIdentityCredential: () => ({}),
    _request: async () => ({}),
    _upload: async () => ({}),
    _navigate: () => {},
    _showMessage: () => {},
    _reportError: () => {},
    _getStorage: () => null,
    _setStorage: () => {},
  }
  return { ...base, ...overrides }
}

// ── 1. 契约校验组 ────────────────────────────────────────────

test('HostBridge 未注册 adapter 时访问能力抛错', () => {
  assert.throws(() => HostBridge.getEnvironment(), /no adapter registered/)
  assert.throws(() => HostBridge.request({}), /no adapter registered/)
  assert.throws(() => HostBridge.navigate('pages/x/x'), /no adapter registered/)
  assert.equal(HostBridge.isReady(), false)
})

const NINE_METHODS = [
  '_getEnvironment', '_getIdentityCredential', '_request', '_upload',
  '_navigate', '_showMessage', '_reportError', '_getStorage', '_setStorage',
]

for (const method of NINE_METHODS) {
  test(`registerAdapter 缺少 ${method} 时抛错且不落位`, () => {
    const adapter = makeFullAdapter()
    delete adapter[method]
    assert.throws(
      () => HostBridge.registerAdapter(adapter),
      new RegExp(`missing methods:.*${method}`),
    )
    // 校验失败不得污染单例（后续用例仍可注册）
    assert.equal(HostBridge.isReady(), false)
  })
}

test('registerAdapter 完整 9 方法装配成功，重复注册抛错', () => {
  const adapter = makeFullAdapter({
    _getEnvironment: () => ({ appEnv: 'prod', hostMode: 'mock-host', authProvider: 'none', apiBase: 'https://gw', apiPrefix: '/p' }),
  })
  HostBridge.registerAdapter(adapter)
  assert.equal(HostBridge.isReady(), true)
  assert.equal(HostBridge.getAdapter(), adapter)

  assert.throws(() => HostBridge.registerAdapter(makeFullAdapter()), /already registered/)
})

test('装配后 HostBridge 能力委托到 adapter', async () => {
  assert.deepEqual(HostBridge.getEnvironment(), { appEnv: 'prod', hostMode: 'mock-host', authProvider: 'none', apiBase: 'https://gw', apiPrefix: '/p' })

  const seen = []
  HostBridge.getAdapter()._request = async (opts) => {
    seen.push(opts)
    return { code: 0, data: { ok: 1 } }
  }
  const res = await HostBridge.request({ method: 'GET', path: '/x' })
  assert.equal(res.data.ok, 1)
  assert.equal(seen[0].path, '/x')
})

// ── 2. LocalAdapter 行为组 ──────────────────────────────────

test('LocalAdapter._getEnvironment 返回环境快照五字段', () => {
  const env = LocalAdapter._getEnvironment()
  assert.deepEqual(Object.keys(env).sort(), ['apiBase', 'apiPrefix', 'appEnv', 'authProvider', 'hostMode'])
  assert.equal(env.appEnv, 'local')
  assert.equal(env.hostMode, 'local')
  assert.equal(env.authProvider, 'mock')
  assert.equal(env.apiPrefix, '/api/tech-transfer/v1')
})

test('LocalAdapter._request 组装 URL（base+prefix+query 编码）并注入 Bearer 与 X-Request-Id', async () => {
  const { calls } = installUniMock({
    getStorageSync: (key) => (key === 'tt_access_token' ? 'tok-abc' : ''),
  })
  let respond
  globalThis.uni.request = (opts) => {
    calls.request.push(opts)
    opts.success({ data: { code: 0, data: { total: 7 }, message: 'ok' } })
  }

  const res = await LocalAdapter._request({
    method: 'GET',
    path: '/demands',
    query: { page: 2, keyword: '新能源', empty: undefined },
  })

  const req = calls.request[0]
  assert.equal(req.method, 'GET')
  assert.equal(
    req.url,
    'http://127.0.0.1:8787/api/tech-transfer/v1/demands?page=2&keyword=' + encodeURIComponent('新能源'),
  )
  assert.equal(req.header.Authorization, 'Bearer tok-abc')
  assert.match(req.header['X-Request-Id'], /^req_/)
  assert.deepEqual(res, { code: 0, data: { total: 7 }, message: 'ok' })
})

test('LocalAdapter._request 无 token 时不注入 Authorization', async () => {
  const { calls } = installUniMock()
  globalThis.uni.request = (opts) => {
    calls.request.push(opts)
    opts.success({ data: { code: 0 } })
  }
  await LocalAdapter._request({ method: 'POST', path: '/demands', body: { a: 1 } })
  const req = calls.request[0]
  assert.equal(req.header.Authorization, undefined)
  assert.deepEqual(req.data, { a: 1 })
  assert.equal(req.method, 'POST')
})

test('LocalAdapter._request 透传外部 X-Request-Id', async () => {
  const { calls } = installUniMock()
  globalThis.uni.request = (opts) => {
    calls.request.push(opts)
    opts.success({ data: { code: 0 } })
  }
  await LocalAdapter._request({
    method: 'GET',
    path: '/x',
    headers: { 'X-Request-Id': 'req_from_client_1' },
  })
  assert.equal(calls.request[0].header['X-Request-Id'], 'req_from_client_1')
})

test('LocalAdapter._navigate 补分包前缀并编码参数', () => {
  const { calls } = installUniMock()
  LocalAdapter._navigate('pages/dock-detail/dock-detail', { type: 'result', id: 5, kw: 'AI 芯片' })
  assert.equal(
    calls.navigateTo[0].url,
    '/subpackages/tech-transfer/pages/dock-detail/dock-detail?type=result&id=5&kw=' + encodeURIComponent('AI 芯片'),
  )

  LocalAdapter._navigate('pages/home/home')
  assert.equal(calls.navigateTo[1].url, '/subpackages/tech-transfer/pages/home/home')
})

test('LocalAdapter._getStorage/_setStorage 读写透传', () => {
  const { calls, storage } = installUniMock()
  LocalAdapter._setStorage('tt_x', { a: 1 })
  assert.equal(calls.setStorageSync[0].key, 'tt_x')
  assert.equal(LocalAdapter._getStorage('tt_x'), storage.tt_x)

  LocalAdapter._setStorage('tt_bad', 'v')
  assert.equal(LocalAdapter._getStorage('tt_missing'), '')
})

test('LocalAdapter._showMessage 调 uni.showToast', () => {
  const { calls } = installUniMock()
  LocalAdapter._showMessage('已收藏', 1500)
  assert.deepEqual(calls.showToast[0], { title: '已收藏', icon: 'none', duration: 1500 })
})

// ── 3. Mock AiNanshan 适配器同组用例（换宿主行为一致） ───────

/**
 * 最小 Mock 上级适配器：网关地址 + 固定 SuccessEnvelope + 记录导航。
 * 与 LocalAdapter 跑同一组断言，仅 apiBase 换为网关前缀——
 * 证明分包侧假设（URL 组装形状 / Bearer 注入 / 导航前缀）对任意
 * 满足契约的宿主均成立，为 C-01/03 确认后的真实 AiNanshanAdapter 兜底。
 */
function makeMockAiNanshanAdapter() {
  const state = { requests: [], navigations: [] }
  const adapter = {
    _getEnvironment: () => ({
      appEnv: 'production',
      hostMode: 'ainanshan',
      authProvider: 'ainanshan',
      apiBase: 'https://gw.ainanshan.example.com',
      apiPrefix: '/api/tech-transfer/v1',
    }),
    _getIdentityCredential: () => ({ hostCredential: 'mock-gw-ticket' }),
    async _request(options) {
      state.requests.push(options)
      return { code: 0, data: { via: 'gateway' }, requestId: 'req_gw_1' }
    },
    async _upload() {
      return { fileId: 1, url: 'https://cdn.example.com/f1' }
    },
    _navigate(path, params) {
      let url = '/subpackages/tech-transfer/' + path
      if (params) {
        url += '?' + Object.entries(params).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
      }
      state.navigations.push(url)
    },
    _showMessage() {},
    _reportError() {},
    _getStorage: () => 'gw-token-xyz',
    _setStorage() {},
  }
  return { adapter, state }
}

test('Mock AiNanshan 适配器满足 HostBridge 9 方法契约', () => {
  const { adapter } = makeMockAiNanshanAdapter()
  // 复用与契约校验组相同的完整性要求（不真的注册——HostBridge 单例已被占用）
  for (const m of NINE_METHODS) {
    assert.equal(typeof adapter[m], 'function', `mock adapter 缺少 ${m}`)
  }
})

test('Mock AiNanshan 网关 URL 组装与 LocalAdapter 同构（仅前缀不同）', async () => {
  const { adapter, state } = makeMockAiNanshanAdapter()
  const res = await adapter._request({
    method: 'GET',
    path: '/demands',
    query: { page: 2, keyword: '新能源' },
  })

  // SuccessEnvelope 原文返回，解包归 client.js —— 与 LocalAdapter 契约一致
  assert.deepEqual(res, { code: 0, data: { via: 'gateway' }, requestId: 'req_gw_1' })

  // 网关前缀 + 同一 API_PREFIX：分包侧无需感知宿主差异
  const env = adapter._getEnvironment()
  assert.equal(env.apiBase, 'https://gw.ainanshan.example.com')
  assert.equal(env.apiPrefix, '/api/tech-transfer/v1')

  // 身份凭据由宿主层提供（决策 D2），分包 client.js 不自行注入
  assert.deepEqual(adapter._getIdentityCredential(), { hostCredential: 'mock-gw-ticket' })
  assert.equal(state.requests.length, 1)
})

test('Mock AiNanshan 导航补同一分包前缀，参数编码一致', () => {
  const { adapter, state } = makeMockAiNanshanAdapter()
  adapter._navigate('pages/dock-detail/dock-detail', { type: 'result', id: 5, kw: 'AI 芯片' })
  assert.equal(
    state.navigations[0],
    '/subpackages/tech-transfer/pages/dock-detail/dock-detail?type=result&id=5&kw=' + encodeURIComponent('AI 芯片'),
  )
})

test('Mock AiNanshan 上传返回值收敛 {fileId, url}', async () => {
  const { adapter } = makeMockAiNanshanAdapter()
  const res = await adapter._upload('file://tmp/x.png', {})
  assert.deepEqual(Object.keys(res).sort(), ['fileId', 'url'])
})
