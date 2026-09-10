import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  SKILLS,
  buildDemoReply,
  filterSkills,
  isSlashDraft,
  resolveSkillCommand,
  formatMatchProgress,
  createWelcomeMessage,
} from '../subpackages/tech-transfer/api/ai-chat.mjs'

test('slash draft detection and skill filtering', () => {
  assert.equal(isSlashDraft('/'), true)
  assert.equal(isSlashDraft('/匹'), true)
  assert.equal(isSlashDraft('匹配'), false)
  assert.equal(filterSkills('/').length, 1)
  assert.equal(filterSkills('/匹配')[0].id, 'match')
  assert.equal(filterSkills('/需求').length, 1)
  assert.equal(filterSkills('/zzzz').length, 0)
})

test('resolves demand-matching as a slash skill', () => {
  assert.equal(resolveSkillCommand('/匹配').id, 'match')
  assert.equal(resolveSkillCommand('/需求匹配').id, 'match')
  assert.equal(resolveSkillCommand('/match').id, 'match')
  assert.equal(resolveSkillCommand('/未知'), null)
  assert.equal(resolveSkillCommand('帮我匹配'), null)
  assert.ok(SKILLS.some((s) => s.label === 'AI 需求匹配'))
})

test('welcome and demo replies point users to slash skills', () => {
  assert.match(createWelcomeMessage().content, /输入 \//)
  assert.match(createWelcomeMessage().content, /人工智能生成/)
  assert.match(buildDemoReply('工业视觉'), /\/ 选择/)
  assert.equal(formatMatchProgress('queued'), '匹配任务已排队，AI 服务接入后会在这里返回推荐成果。')
})

test('ai-match page restores the chat composer and slash skill sheet', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /class="composer"/)
  assert.match(source, /class="skill-sheet"/)
  assert.match(source, /runMatchSkill/)
  assert.match(source, /createMatchTask/)
  assert.match(source, /AiGeneratedMark/)
  assert.match(source, /人工智能生成/)
  assert.match(source, /功能即将开放/)
  assert.match(source, /v-if="!aiEnabled"/)
})
