import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import * as patentApi from '../subpackages/tech-transfer/api/patent.js'
import {
  buildPatentDetailSeed,
  mergePatentDetail,
} from '../subpackages/tech-transfer/utils/patent-detail-state.mjs'
import { getScannedHttpUrl } from '../subpackages/tech-transfer/utils/scanned-url.mjs'

const LEAK = /googleapis|patents\.google|googleusercontent|patentimages\.storage|pdf_url/

test('patent type labels stay user-facing', () => {
  assert.equal(patentApi.getPatentTypeLabel('invention'), '发明专利')
  assert.equal(patentApi.getPatentTypeLabel('utility_model'), '实用新型')
  assert.equal(patentApi.getPatentTypeLabel('design'), '外观设计')
})

test('patent search client provides server-backed recent-query methods', () => {
  assert.equal(typeof patentApi.getPatentSearchHistory, 'function')
  assert.equal(typeof patentApi.savePatentSearchHistory, 'function')
})

test('patent detail decodes every routed preview field before rendering', () => {
  const seed = buildPatentDetailSeed({
    no: 'CN110313154B',
    title: '%E5%85%B7%E6%9C%89%E5%9F%BA%E4%BA%8E%E6%84%8F%E5%9B%BE%E7%9A%84%E4%BF%A1%E6%81%AF%E8%BE%A8%E6%9E%90',
    applicant: '%E5%BE%AE%E8%BD%AF%E6%8A%80%E6%9C%AF%E8%AE%B8%E5%8F%AF%E6%9C%89%E9%99%90%E8%B4%A3%E4%BB%BB%E5%85%AC%E5%8F%B8',
    inventor: 'O%E3%83%BB%E6%89%80%E7%BD%97%E9%97%A8',
    language: 'zh',
  })

  assert.equal(seed.title, '具有基于意图的信息辨析')
  assert.equal(seed.applicant, '微软技术许可有限责任公司')
  assert.equal(seed.inventor, 'O・所罗门')
  assert.equal(seed.language, 'zh')
})

test('patent detail keeps the title language shown in the search preview', () => {
  const detail = mergePatentDetail(
    { title: '具有基于意图的信息辨析', applicant: '', language: 'zh' },
    { title: 'Intelligent assistant with intent-based information resolution', applicant: '微软技术许可有限责任公司' },
  )

  assert.equal(detail.title, '具有基于意图的信息辨析')
  assert.equal(detail.applicant, '微软技术许可有限责任公司')
})

test('scan results accept only complete http URLs for direct navigation', () => {
  assert.equal(getScannedHttpUrl(' https://example.com/path?a=1 '), 'https://example.com/path?a=1')
  assert.equal(getScannedHttpUrl('www.example.com'), '')
  assert.equal(getScannedHttpUrl('javascript:alert(1)'), '')
})

test('scan recognizes HTTPS in a WeChat runtime without the browser URL API', () => {
  const originalUrl = globalThis.URL
  try {
    globalThis.URL = undefined
    assert.equal(
      getScannedHttpUrl('https://achievementexpo.siat.ac.cn/view/#\n/activePage/10400002'),
      'https://achievementexpo.siat.ac.cn/view/#/activePage/10400002',
    )
  } finally {
    globalThis.URL = originalUrl
  }
})

test('in-app web view uses the same Mini Program-safe URL validation', () => {
  const webView = readFileSync(
    new URL('../subpackages/tech-transfer/pages/web-view/web-view.vue', import.meta.url),
    'utf8',
  )
  assert.match(webView, /getScannedHttpUrl/)
  assert.doesNotMatch(webView, /new URL/)
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
