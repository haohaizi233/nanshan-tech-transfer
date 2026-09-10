import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { getPatentTypeLabel } from '../subpackages/tech-transfer/api/patent.js'

const LEAK = /googleapis|patents\.google|googleusercontent|patentimages\.storage|pdf_url/

test('patent type labels stay user-facing', () => {
  assert.equal(getPatentTypeLabel('invention'), '发明专利')
  assert.equal(getPatentTypeLabel('utility_model'), '实用新型')
  assert.equal(getPatentTypeLabel('design'), '外观设计')
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
})

test('patent client talks only to the local patents API', () => {
  const api = readFileSync(
    new URL('../subpackages/tech-transfer/api/patent.js', import.meta.url),
    'utf8',
  )
  assert.match(api, /apiRequest\('GET', '\/patents'/)
  assert.match(api, /\/patents\/\$\{encodeURIComponent\(publicationNo\)\}/)
  assert.doesNotMatch(api, LEAK)
})
