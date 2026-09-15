import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const mine = readFileSync(new URL('subpackages/tech-transfer/pages/mine/mine.vue', root), 'utf8')
const home = readFileSync(new URL('subpackages/tech-transfer/pages/home/home.vue', root), 'utf8')

const mineIcons = [
  'certification-badge.png',
  'phone.png',
  'email.png',
  'wechat.png',
  'org-certification.png',
  'demand.png',
  'result.png',
  'favorite.png',
  'intention.png',
]

test('uses the supplied visual resources on the mine page', () => {
  for (const icon of mineIcons) {
    assert.match(mine, new RegExp(`/static/icons/mine/${icon}`))
    assert.equal(existsSync(new URL(`static/icons/mine/${icon}`, root)), true)
  }
  assert.match(mine, /\/static\/images\/mine\/org-certification-bg\.png/)
  assert.equal(existsSync(new URL('static/images/mine/org-certification-bg.png', root)), true)
})

test('replaces the home demand and result text glyphs with the supplied icons', () => {
  assert.match(home, /src="\/static\/icons\/mine\/demand\.png"/)
  assert.match(home, /src="\/static\/icons\/mine\/result\.png"/)
  assert.doesNotMatch(home, /class="action-icon-text">[需果]<\/text>/)
})
