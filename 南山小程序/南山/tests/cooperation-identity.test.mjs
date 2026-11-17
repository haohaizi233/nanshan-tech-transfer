import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
const source = readFileSync(new URL('../subpackages/tech-transfer/pages/my-list/my-list.vue', import.meta.url), 'utf8')
const body = source.slice(source.indexOf('mapIntentionRows(rows) {') + 'mapIntentionRows(rows) {'.length, source.indexOf('\n\t\t\tasync loadList()')).replace(/},\s*$/, '')
const map = new Function('rows', 'toFeType', 'getIntentTypeLabel', 'getCooperationDisplayLabel', 'getCooperationDisplayCls', 'getAssistedHint', body)
for (const name of ['张先生', '深圳科技有限公司'.repeat(12), '', '对方用户']) {
  for (const tab of [0, 1]) test(`identity and intent mapping ${name.slice(0,8)} tab ${tab}`, () => {
    const [row] = map.call({intentTab: tab}, [{ id: 8, targetId: 9, targetType: 'demand', status: 'cancelled', counterpartDisplayName: name, targetSummary: { title: '长标题'.repeat(60) }}], x => x, () => '提供技术方案', () => '已取消', () => 'cancelled', () => '')
    assert.equal(row._counterpartName, name || '对方用户')
    assert.equal(row._counterpartPrefix, tab === 0 ? '对接对象：' : '来自：')
    assert.equal(row._intentLabel, '提供技术方案')
    assert.equal(row._intentId, 8)
    assert.equal(row._openId, 9)
    assert.equal(row._status, 'cancelled')
  })
}
test('identity and intention have separate template rows; labels wrap below title', () => {
  assert.match(source, /v-if="item\._counterpartName"/)
  assert.match(source, /v-if="item\._intentLabel"/)
  assert.match(source, /\.card-title\s*\{[^}]*flex-basis:\s*100%/)
  assert.match(source, /\.badge-wrap\s*\{[^}]*flex-wrap:\s*wrap/)
})
