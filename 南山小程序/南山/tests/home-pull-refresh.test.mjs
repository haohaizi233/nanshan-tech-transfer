import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const root = new URL('../', import.meta.url)
const home = readFileSync(new URL('subpackages/tech-transfer/pages/home/home.vue', root), 'utf8')
const pages = readFileSync(new URL('pages.json', root), 'utf8')

test('首页需求和成果展示支持下拉刷新当前标签', () => {
  assert.match(home, /onPullDownRefresh\(\)/)
  assert.match(home, /await this\.refreshList\(this\.currentTabKey\)/)
  assert.match(home, /uni\.stopPullDownRefresh\(\)/)
  assert.match(home, /const shouldRefreshDemand = target !== 'result'/)
  assert.match(home, /const shouldRefreshResult = target !== 'demand'/)
  assert.match(pages, /"pages\/home\/home"[\s\S]*?"enablePullDownRefresh": true/)
})
