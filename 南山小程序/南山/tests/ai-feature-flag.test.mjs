import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { AI_FEATURE_ENABLED, SHOW_AI_MATCH_ENTRY } from '../config/feature-flags.js'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

test('AI feature is off and entry follows the same switch', () => {
  assert.equal(AI_FEATURE_ENABLED, false)
  assert.equal(SHOW_AI_MATCH_ENTRY, AI_FEATURE_ENABLED)
})

test('AI API wrappers refuse requests when the feature is off', () => {
  const source = read('../subpackages/tech-transfer/api/ai.js')
  assert.match(source, /assertAiRuntimeEnabled/)
  assert.match(source, /AI_FEATURE_ENABLED/)
  assert.equal((source.match(/export async function createMatchTask/g) || []).length, 1)
  assert.equal((source.match(/export async function getMatchTask/g) || []).length, 1)
  assert.equal((source.match(/export async function createEvaluationTask/g) || []).length, 1)
  assert.equal((source.match(/export async function getEvaluationTask/g) || []).length, 1)
  assert.match(source, /export async function createMatchTask[\s\S]*?assertAiRuntimeEnabled\(\)/)
  assert.match(source, /export async function getMatchTask[\s\S]*?assertAiRuntimeEnabled\(\)/)
  assert.match(source, /export async function createEvaluationTask[\s\S]*?assertAiRuntimeEnabled\(\)/)
  assert.match(source, /export async function getEvaluationTask[\s\S]*?assertAiRuntimeEnabled\(\)/)
})

test('mis-opened AI pages show coming soon and keep chat/eval source', () => {
  const matchPage = read('../subpackages/tech-transfer/pages/ai-match/ai-match.vue')
  const evalPage = read('../subpackages/tech-transfer/pages/ai-eval-detail/ai-eval-detail.vue')
  assert.match(matchPage, /v-if="!aiEnabled"/)
  assert.match(matchPage, /功能即将开放/)
  assert.match(matchPage, /if \(!this\.aiEnabled\) return/)
  assert.match(matchPage, /class="composer"/)
  assert.match(matchPage, /createMatchTask/)
  assert.match(evalPage, /v-if="!aiEnabled"/)
  assert.match(evalPage, /功能即将开放/)
  assert.match(evalPage, /if \(!this\.aiEnabled\) return/)
  assert.match(evalPage, /getEvaluationTask/)
})

test('AI evaluation buttons stay hidden while the feature is off', () => {
  const myList = read('../subpackages/tech-transfer/pages/my-list/my-list.vue')
  const postResult = read('../subpackages/tech-transfer/pages/post-result/post-result.vue')
  assert.match(myList, /pageType === 'result' && aiEnabled/)
  assert.match(postResult, /v-if="aiEnabled"/)
  assert.match(postResult, /发起 AI 评估/)
})
