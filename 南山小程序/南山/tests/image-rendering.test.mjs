import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
const root = new URL('../subpackages/tech-transfer/pages/', import.meta.url)
const patent = readFileSync(new URL('patent-list/patent-list.vue', root), 'utf8')
const mine = readFileSync(new URL('mine/mine.vue', root), 'utf8')
test('patent empty state uses readable native text instead of enlarging the thumbnail', () => {
  assert.doesNotMatch(patent, /patent-search-empty\.png/)
  assert.match(patent, /class="state-title">暂未找到相关专利/)
  assert.match(patent, /class="state-title">开启专利探索之旅/)
})
test('certification background fills the card without a white rectangle seam', () => {
  assert.match(mine, /class="org-card-bg"[^>]*mode="aspectFill"/)
  assert.match(mine, /\.org-card-bg\s*\{[^}]*left:\s*0;[^}]*width:\s*100%/)
})
