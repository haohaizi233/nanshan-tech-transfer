import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const patentDetail = readFileSync(new URL('subpackages/tech-transfer/pages/patent-detail/patent-detail.vue', root), 'utf8')
const mine = readFileSync(new URL('subpackages/tech-transfer/pages/mine/mine.vue', root), 'utf8')

test('keeps the patent reader navigation inside the H5 portrait shell', () => {
  assert.match(patentDetail, /\.reader-nav\s*\{[\s\S]*left:\s*var\(--window-left,\s*0px\)/)
  assert.match(patentDetail, /\.reader-nav\s*\{[\s\S]*right:\s*var\(--window-right,\s*0px\)/)
})

test('uses the certification artwork as a subtle right-side scene instead of a second card frame', () => {
  assert.match(mine, /\.org-card-bg\s*\{[\s\S]*left:\s*auto[\s\S]*width:\s*72%/)
  assert.match(mine, /\.org-card\s*\{[\s\S]*background:\s*linear-gradient/)
})

test('gives the supplied functional icons a larger display area', () => {
  assert.match(mine, /\.module-icon\s*\{[\s\S]*width:\s*92rpx[\s\S]*height:\s*92rpx/)
  assert.match(mine, /\.org-card-icon\s*\{[\s\S]*width:\s*112rpx[\s\S]*height:\s*112rpx/)
})

test('enlarges information icons without increasing contact row spacing', () => {
  assert.match(mine, /\.contact-icon\s*\{[\s\S]*width:\s*64rpx[\s\S]*height:\s*64rpx/)
  assert.match(mine, /\.contact-row\s*\{[\s\S]*padding:\s*12rpx 0/)
})
