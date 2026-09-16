import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('demand and achievement publishing expose an optional, unlimited-by-default capacity', () => {
  for (const page of [
    '../subpackages/tech-transfer/pages/post-demand/post-demand.vue',
    '../subpackages/tech-transfer/pages/post-result/post-result.vue',
  ]) {
    const source = read(page)
    assert.match(source, /可对接名额/)
    assert.match(source, /留空表示不限量/)
    assert.match(source, /cooperationCapacity/)
  }
})
