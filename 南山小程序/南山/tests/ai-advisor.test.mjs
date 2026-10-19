import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { WELCOME, getChatSuggestions } from '../subpackages/tech-transfer/api/ai-chat.mjs'

test('AI onboarding offers introductions, recommendations and platform guidance', () => {
  assert.match(WELCOME, /介绍/)
  assert.match(WELCOME, /推荐/)
  assert.match(WELCOME, /操作/)
  assert.ok(getChatSuggestions().some(item => item.includes('怎么发布')))
  assert.ok(getChatSuggestions().some(item => item.includes('推荐')))
})

test('AI cards distinguish published facts, AI interpretation and unresolved conditions', () => {
  const source = readFileSync(new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url), 'utf8')
  assert.match(source, /card\.advisorSummary/)
  assert.match(source, /card\.advisorInsight/)
  assert.match(source, /card\.advisorCautions/)
  assert.match(source, /发布资料摘要/)
  assert.match(source, /AI适配解读/)
  assert.match(source, /待确认/)
  assert.doesNotMatch(source, /v-html/)
})
