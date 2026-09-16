import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const read = (relativePath) => fs.readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('public preview cards can open docking details without logging in', () => {
  for (const page of ['../subpackages/tech-transfer/pages/home/home.vue', '../subpackages/tech-transfer/pages/search/search.vue']) {
    const source = read(page)
    assert.match(source, /openDetail\(type, id\)\s*\{/, `${page} should keep an openDetail handler`)
    assert.doesNotMatch(source, /openDetail\(type, id\)\s*\{\s*if\s*\(\s*!ensureLoginForDock\(\)\s*\)/,
      `${page} must not gate public detail viewing behind login`)
  }
})

test('only the actual cooperation submission retains the login guard', () => {
  const achievement = read('../subpackages/tech-transfer/pages/achievement-detail/achievement-detail.vue')
  const dockDetail = read('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue')
  assert.doesNotMatch(achievement, /onProposeDock\(\)\s*\{\s*if\s*\(\s*!ensureLoginForDock\(\)\s*\)/)
  assert.match(dockDetail, /onProposeDock\(\)\s*\{\s*if\s*\(\s*!ensureLoginForDock\(\)\s*\)/)
})
