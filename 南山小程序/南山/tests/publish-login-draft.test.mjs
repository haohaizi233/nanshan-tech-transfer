import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('guest publishing persists drafts and only requires login when submitting', () => {
  const demand = read('../subpackages/tech-transfer/pages/post-demand/post-demand.vue')
  const achievement = read('../subpackages/tech-transfer/pages/post-result/post-result.vue')
  for (const source of [demand, achievement]) {
    assert.doesNotMatch(source, /onLoad\(\)\s*\{\s*if\s*\(\s*!ensureLoginForDock/)
    assert.match(source, /savePublishDraft/)
    assert.match(source, /restorePublishDraft/)
  }
  assert.ok(existsSync(new URL('../subpackages/tech-transfer/api/publish-draft.mjs', import.meta.url)))
})

test('login and profile completion resume the saved publishing route', () => {
  const mine = read('../subpackages/tech-transfer/pages/mine/mine.vue')
  assert.match(mine, /resumePublishDraftAfterLogin/)
})
