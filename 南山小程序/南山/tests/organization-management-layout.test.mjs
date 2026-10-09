import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const mine = readFileSync(new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url), 'utf8')
const manage = readFileSync(new URL('../subpackages/tech-transfer/pages/org-manage/org-manage.vue', import.meta.url), 'utf8')

test('places the certification badge on the organization-certification title row', () => {
  assert.match(mine, /class="org-card-heading">\s*<text class="org-card-title">机构认证<\/text>\s*<text class="org-role admin"/)
  assert.match(mine, /\.org-card-heading\s*\{[\s\S]*justify-content:\s*space-between/)
})

test('keeps application approve and reject actions on one row', () => {
  assert.match(manage, /\.action-row\s*\{[\s\S]*flex-direction:\s*row/)
  assert.match(manage, /\.action-row\s+\.mini-btn\s*\{[\s\S]*margin:/)
})

test('keeps the revoke dialog as a centered card instead of a full-width overlay', () => {
  assert.match(manage, /\.dialog-panel\s*\{[\s\S]*?width:\s*560rpx/)
  assert.match(manage, /left:\s*var\(--window-left,\s*0px\)/)
  assert.match(manage, /right:\s*var\(--window-right,\s*0px\)/)
})
