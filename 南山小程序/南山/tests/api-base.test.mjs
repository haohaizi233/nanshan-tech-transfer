import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { resolveH5ApiBase } from '../host/local-adapter.js'

test('uses the paired public API port when the H5 page is served through the tunnel', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('http://43.138.138.200:8077/#/pages/index/index'),
    }),
    'http://43.138.138.200:8076',
  )
})

test('keeps the local API address for the H5 development server', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('http://127.0.0.1:5173/#/pages/index/index'),
    }),
    'http://127.0.0.1:8787',
  )
})

test('derives the same-host direct API for a LAN-visited H5 page (phone on same WiFi)', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('http://192.168.2.79:5173/#/pages/index/index'),
    }),
    'http://192.168.2.79:8787',
  )
})

test('keeps the configured local API when the page hostname is localhost', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('http://localhost:5173/#/pages/index/index'),
    }),
    'http://127.0.0.1:8787',
  )
})

test('falls back to the configured local API when there is no page location (mini-program)', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: null,
    }),
    'http://127.0.0.1:8787',
  )
})

test('uses same-origin API paths for a production H5 build', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'production',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('https://example.com/#/pages/index/index'),
    }),
    '',
  )
})

test('uses same-origin API paths when H5 is served through Caddy on :80', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('http://43.138.138.200/#/pages/index/index'),
    }),
    '',
  )
})

test('uses same-origin API paths when H5 is served through Caddy HTTPS', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('https://nanshan.example.com/pages/home/home'),
    }),
    '',
  )
})

test('uses same-origin API paths when H5 is under /h5 on the public Caddy host', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      pageLocation: new URL('https://inanshan.sjhcip.com/h5/#/pages/home/home'),
    }),
    '',
  )
})

test('LocalAdapter stays in the main package (WeChat whitescreens main→subpackage imports)', () => {
  const src = readFileSync(new URL('../host/local-adapter.js', import.meta.url), 'utf8')
  // 主包模块可生成分包页面路径；关键是不从分包源码 import，避免微信主包加载时报缺模块。
  assert.doesNotMatch(src, /from\s+['"][^'"]*subpackages\//)
  assert.doesNotMatch(src, /import\([^)]*subpackages\//)
})

test('WeChat mini program uses the public HTTPS API in devtools', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      weixinApiBase: 'https://inanshan.sjhcip.com',
      pageLocation: null,
      systemInfo: { uniPlatform: 'mp-weixin', platform: 'devtools' },
    }),
    'https://inanshan.sjhcip.com',
  )
})

test('WeChat mini program uses the public HTTPS API on a real phone', () => {
  assert.equal(
    resolveH5ApiBase({
      appEnv: 'local',
      localApiBase: 'http://127.0.0.1:8787',
      weixinApiBase: 'https://inanshan.sjhcip.com',
      pageLocation: null,
      systemInfo: { uniPlatform: 'mp-weixin', platform: 'ios' },
    }),
    'https://inanshan.sjhcip.com',
  )
})
