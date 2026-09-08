import assert from 'node:assert/strict'
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
