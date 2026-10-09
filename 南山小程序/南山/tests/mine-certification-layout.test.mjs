import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../subpackages/tech-transfer/pages/mine/mine.vue', import.meta.url),
  'utf8',
)

test('organization certification places the administrator role on the title row', () => {
  assert.doesNotMatch(source, /class="'org-status org-status-' \+ certification\.status"/)
  assert.match(
    source,
    /class="org-card-heading">\s*<text class="org-card-title">机构认证<\/text>\s*<text class="org-role admin"/,
  )
  assert.match(
    source,
    /<view v-if="m\.role === 'admin'" class="org-actions">\s*<button class="org-manage-btn"/,
  )
  assert.match(source, /\.org-card-certified_admin\s*\{/)
  assert.doesNotMatch(source, /\.org-card-certified-admin\s*\{/)
})

test('profile card stacks identity, company, and contact instead of a cramped side-by-side row', () => {
  assert.match(source, /class="profile-head"/)
  assert.match(source, /class="name-row"/)
  assert.match(source, /<view v-if="displayCompany" class="company-row">/)
  assert.match(source, /class="contact-list"/)
  assert.match(source, /<text class="contact-label">电话<\/text>/)
  assert.doesNotMatch(source, /class="profile-divider"/)
  assert.doesNotMatch(source, /class="contact-side"/)
})
