import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  AI_BADGE_CAPTION,
  AI_EVAL_NOTICE,
  AI_FOOTER_NOTICE,
  AI_GENERATED_PHRASE,
  AI_GENERATED_TAG,
  AI_MATCH_NOTICE,
} from '../subpackages/tech-transfer/api/ai-disclosure.mjs'

test('AI disclosure copy uses the required WeChat wording', () => {
  assert.equal(AI_GENERATED_TAG, 'AI生成')
  assert.equal(AI_GENERATED_PHRASE, '人工智能生成')
  assert.match(AI_MATCH_NOTICE, /人工智能生成/)
  assert.match(AI_EVAL_NOTICE, /人工智能生成/)
  assert.match(AI_BADGE_CAPTION, /人工智能生成/)
  assert.match(AI_FOOTER_NOTICE, /人工智能生成/)
})

test('AI pages keep a prominent generated-content mark', () => {
  const mark = readFileSync(
    new URL('../subpackages/tech-transfer/components/ai-generated-mark.vue', import.meta.url),
    'utf8',
  )
  const matchPage = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  const evalPage = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-eval-detail/ai-eval-detail.vue', import.meta.url),
    'utf8',
  )
  const achievementDetailPage = readFileSync(
    new URL('../subpackages/tech-transfer/pages/achievement-detail/achievement-detail.vue', import.meta.url),
    'utf8',
  )
  assert.match(mark, />AI生成</)
  assert.match(mark, /virtualHost:\s*true/)
  assert.match(mark, /badgeCaption/)
  assert.match(matchPage, /AiGeneratedMark/)
  assert.match(matchPage, /composer__disclosure/)
  assert.match(matchPage, /AI_FOOTER_NOTICE/)
  assert.match(matchPage, /人工智能生成/)
  assert.match(evalPage, /AiGeneratedMark/)
  assert.match(evalPage, /AI_EVAL_NOTICE/)
  assert.match(evalPage, /人工智能生成/)
  assert.match(achievementDetailPage, /AiGeneratedMark/)
})
