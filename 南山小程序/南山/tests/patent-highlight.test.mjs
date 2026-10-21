import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  hasPatentHighlight,
  splitHighlightSegments,
} from '../subpackages/tech-transfer/utils/patent-highlight.mjs'

const LIST_VUE = readFileSync(
  new URL('../subpackages/tech-transfer/pages/patent-list/patent-list.vue', import.meta.url),
  'utf8',
)

test('patent highlight splits text into hit and plain segments', () => {
  const segments = splitHighlightSegments('数据安全备份和安全恢复', ['安全'])
  assert.deepEqual(segments, [
    { text: '数据', hit: false },
    { text: '安全', hit: true },
    { text: '备份和', hit: false },
    { text: '安全', hit: true },
    { text: '恢复', hit: false },
  ])
})

test('patent highlight keeps whole text when no hit word matches', () => {
  const segments = splitHighlightSegments('数据安全备份', ['华为'])
  assert.deepEqual(segments, [{ text: '数据安全备份', hit: false }])
})

test('patent highlight returns plain segment without highlights', () => {
  const segments = splitHighlightSegments('数据安全备份', [])
  assert.deepEqual(segments, [{ text: '数据安全备份', hit: false }])
})

test('patent highlight marks every occurrence of a hit word', () => {
  const segments = splitHighlightSegments('华为与华为', ['华为'])
  assert.deepEqual(segments, [
    { text: '华为', hit: true },
    { text: '与', hit: false },
    { text: '华为', hit: true },
  ])
})

test('patent highlight prefers the longest overlapping hit word', () => {
  const segments = splitHighlightSegments('华为技术有限公司', ['华为', '华为技术'])
  assert.deepEqual(segments, [
    { text: '华为技术', hit: true },
    { text: '有限公司', hit: false },
  ])
})

test('patent highlight tolerates empty and invalid input', () => {
  assert.deepEqual(splitHighlightSegments('', ['华为']), [])
  assert.deepEqual(splitHighlightSegments(null, ['华为']), [])
  assert.deepEqual(splitHighlightSegments('华为', null), [{ text: '华为', hit: false }])
  assert.deepEqual(splitHighlightSegments('华为', ['  ']), [{ text: '华为', hit: false }])
})

test('patent highlight detects whether a result carries hit words', () => {
  assert.equal(hasPatentHighlight({ highlights: ['华为'] }), true)
  assert.equal(hasPatentHighlight({ highlights: [] }), false)
  assert.equal(hasPatentHighlight({ highlights: ['  '] }), false)
  assert.equal(hasPatentHighlight({}), false)
  assert.equal(hasPatentHighlight(null), false)
})

test('patent list renders server-provided highlight segments', () => {
  assert.ok(LIST_VUE.includes('titleSegments(item)'))
  assert.ok(LIST_VUE.includes("seg.hit ? 'hl-hit' : ''"))
  assert.ok(LIST_VUE.includes('splitHighlightSegments'))
  // 旧的纯文本渲染必须已经移除，否则高亮不会生效
  assert.ok(!LIST_VUE.includes('{{ item.title || item.publicationNo }}'))
})
