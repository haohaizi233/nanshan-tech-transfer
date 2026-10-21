import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dock = readFileSync(new URL('../subpackages/tech-transfer/pages/dock-detail/dock-detail.vue', import.meta.url), 'utf8')
const postDemand = readFileSync(new URL('../subpackages/tech-transfer/pages/post-demand/post-demand.vue', import.meta.url), 'utf8')
const postResult = readFileSync(new URL('../subpackages/tech-transfer/pages/post-result/post-result.vue', import.meta.url), 'utf8')
const orgApply = readFileSync(new URL('../subpackages/tech-transfer/pages/org-apply/org-apply.vue', import.meta.url), 'utf8')
const orgManage = readFileSync(new URL('../subpackages/tech-transfer/pages/org-manage/org-manage.vue', import.meta.url), 'utf8')
const myList = readFileSync(new URL('../subpackages/tech-transfer/pages/my-list/my-list.vue', import.meta.url), 'utf8')

test('dock-detail prefers incoming intent actions over owner offline mode', () => {
  assert.match(dock, /actionMode\(\)\s*\{[\s\S]*const row = this\.intention[\s\S]*if \(row\) \{/)
  assert.match(dock, /if \(!this\.intention && op !== 'offline'\) return/)
})

test('publication forms bind the first certified organization by default', () => {
  assert.match(postDemand, /if \(this\.organizations\.length && !this\.form\.orgId\) this\.form\.orgId = this\.organizations\[0\]\.orgId/)
  assert.match(postResult, /if \(this\.organizations\.length && !this\.form\.orgId\) this\.form\.orgId = this\.organizations\[0\]\.orgId/)
})

test('org-apply keeps type picker computeds alongside certification hint', () => {
  assert.equal((orgApply.match(/^\s*computed:\s*\{/gm) || []).length, 1)
  assert.match(orgApply, /typeIndex\(\)/)
  assert.match(orgApply, /certificationHint\(\)/)
})

test('org-manage restores cached members and always refreshes them on show', () => {
  assert.match(orgManage, /if \(this\.currentOrgId\) this\.loadList\(\)/)
  assert.match(orgManage, /this\.invalidatePageState\('list'\)/)
})

test('my-list keeps demand reject hints and does not mark matched favorites offline', () => {
  assert.match(myList, /_type: 'demand'[\s\S]*_statusHint: card\.statusHint/)
  assert.match(myList, /const offline = \['offline', 'closed', 'cancelled'\]\.includes\(sum\.status\)/)
  assert.match(myList, /if \(this\.pageType === 'result'\)/)
})

test('dock-detail keeps the favorite star available after confirmation', () => {
  assert.match(dock, /:class="favorited \? 'star-btn star-on' : 'star-btn'"/)
  assert.match(dock, /async onToggleFavorite\(\)/)
  assert.doesNotMatch(dock, /onToggleFavorite[\s\S]{0,200}status === 'published'/)
})
