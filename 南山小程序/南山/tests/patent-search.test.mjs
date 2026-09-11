import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import * as patentApi from '../subpackages/tech-transfer/api/patent.js'

const LEAK = /googleapis|patents\.google|googleusercontent|patentimages\.storage|pdf_url/

test('patent type labels stay user-facing', () => {
  assert.equal(patentApi.getPatentTypeLabel('invention'), '发明专利')
  assert.equal(patentApi.getPatentTypeLabel('utility_model'), '实用新型')
  assert.equal(patentApi.getPatentTypeLabel('design'), '外观设计')
})

test('patent preview follows the LocalAdapter H5 API routing rule', () => {
  assert.equal(typeof patentApi.resolvePatentApiOrigin, 'function')
  if (typeof patentApi.resolvePatentApiOrigin !== 'function') return
  const env = {
    appEnv: 'local',
    hostMode: 'local',
    apiBase: 'http://127.0.0.1:8787',
  }
  assert.equal(
    patentApi.resolvePatentApiOrigin(env, { protocol: 'https:', hostname: 'inanshan.sjhcip.com', port: '443' }),
    '',
  )
  assert.equal(
    patentApi.resolvePatentApiOrigin(env, { protocol: 'http:', hostname: '192.168.1.8', port: '8077' }),
    'http://192.168.1.8:8076',
  )
})

test('home 检索 tab opens in-app patent search', () => {
  const home = readFileSync(new URL('../subpackages/tech-transfer/pages/home/home.vue', import.meta.url), 'utf8')
  assert.match(home, /pages\/patent-list\/patent-list/)
  assert.match(home, /key: 'search', name: '检索'/)
})

test('patent pages are registered and never mention upstream hosts', () => {
  const pages = readFileSync(new URL('../pages.json', import.meta.url), 'utf8')
  assert.match(pages, /pages\/patent-list\/patent-list/)
  assert.match(pages, /pages\/patent-detail\/patent-detail/)

  const files = [
    new URL('../subpackages/tech-transfer/api/patent.js', import.meta.url),
    new URL('../subpackages/tech-transfer/pages/patent-list/patent-list.vue', import.meta.url),
    new URL('../subpackages/tech-transfer/pages/patent-detail/patent-detail.vue', import.meta.url),
    new URL('../subpackages/tech-transfer/components/pdf-preview-overlay.vue', import.meta.url),
  ]
  for (const file of files) {
    const source = readFileSync(file, 'utf8')
    assert.doesNotMatch(source, LEAK)
    assert.doesNotMatch(source, /43\.138\.138\.200:8081/)
  }

  const detail = readFileSync(
    new URL('../subpackages/tech-transfer/pages/patent-detail/patent-detail.vue', import.meta.url),
    'utf8',
  )
  assert.match(detail, /detail\.abstract/)
  assert.match(detail, /detail\.claims/)
  assert.match(detail, /detail\.description/)
  assert.match(detail, /pdf-preview-overlay/)
  assert.match(detail, /pdfVisible/)
  assert.doesNotMatch(detail, /openDocument/)
})

test('patent client talks only to the local patents API', () => {
  const api = readFileSync(
    new URL('../subpackages/tech-transfer/api/patent.js', import.meta.url),
    'utf8',
  )
  assert.match(api, /apiRequest\('GET', '\/patents'/)
  assert.match(api, /\/patents\/\$\{encodeURIComponent\(publicationNo\)\}/)
  assert.match(api, /\/pdf\/pages/)
  assert.doesNotMatch(api, /openDocument/)
  assert.doesNotMatch(api, LEAK)
})

test('pdf preview overlay renders pages in-place with zoom', () => {
  const overlay = readFileSync(
    new URL('../subpackages/tech-transfer/components/pdf-preview-overlay.vue', import.meta.url),
    'utf8',
  )
  assert.match(overlay, /pdf-overlay/)
  assert.match(overlay, /zoomIn/)
  assert.match(overlay, /loadPatentPdfPage/)
  assert.doesNotMatch(overlay, /openDocument/)
  assert.doesNotMatch(overlay, LEAK)
})
