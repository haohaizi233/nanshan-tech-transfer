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
import {
  QUEUE_STORAGE_KEY,
  enqueueMessage,
  dequeueMessage,
  findInflightStatus,
  loadQueueState,
  previewChatMessages,
  previewQueue,
  removeQueueItem,
  saveQueueState,
} from '../subpackages/tech-transfer/api/ai-chat-queue.mjs'

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
  assert.match(source, /matchDemand/)
  assert.match(source, /AiGeneratedMark/)
  assert.match(source, /人工智能生成/)
  assert.match(source, /功能即将开放/)
  assert.match(source, /v-if="!aiEnabled"/)
})

test('ai-match composer stays editable while generating and queues follow-ups locally', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  assert.doesNotMatch(source.match(/<input[\s\S]*?\/>/)[0], /:disabled="typing"/)
  assert.match(source, /pendingQueue/)
  assert.match(source, /enqueueMessage/)
  assert.match(source, /pumpQueue/)
  assert.match(source, /resumeSession/)
  assert.match(source, /class="queue-dock"/)
  assert.match(source, /class="history-fold"/)
  assert.match(source, /sendLabel/)
  assert.match(source, /排队/)
  assert.match(source, /saveQueueState/)
  assert.match(source, /onHide\(\)/)
  assert.match(source, /onUnload\(\)/)
  assert.match(source, /beginTurn\(\{ turnId, message: text, reference/)
  assert.match(source, /chatWithAgent\(text, turnId, reference\)/)
  assert.match(source, /loadActiveTurn/)
  assert.match(source, /getChatTurn/)
  assert.match(source, /为避免重复请求/)
  assert.doesNotMatch(source, /waitForInflightTurn/)
  const saved = source.indexOf('saveTurnResult(turnId, reply, res.success')
  const rendered = source.indexOf('presentSavedTurn(loadActiveTurn(uni, this._scope))', saved)
  assert.ok(saved >= 0 && rendered > saved, 'persist the terminal result before rendering it')
})

test('AI page drops an in-flight local turn when the server reports cleared history', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  const start = source.indexOf('async runAgentChat(text, reference)')
  const end = source.indexOf('openCard(card)', start)
  const runAgentChat = start >= 0 && end > start ? source.slice(start, end) : ''
  assert.match(runAgentChat, /e\.details\?\.reason === 'chat_history_cleared'/)
  assert.match(runAgentChat, /acknowledgeTurn\(turnId, uni, this\._scope\)/)
  assert.match(runAgentChat, /this\.pendingQueue = \[\]/)
  assert.match(runAgentChat, /await this\.loadHistory\(\)/)
  assert.match(runAgentChat, /this\.finishTurn\(\)/)
})

test('AI chat API sends a turn ID and exposes the authenticated status lookup', () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/api/ai.js', import.meta.url),
    'utf8',
  )
  assert.match(source, /export async function chatWithAgent\(message, turnId, reference\)/)
  assert.match(source, /turnId: turnId \|\| undefined/)
  assert.match(source, /export async function getChatTurn\(turnId\)/)
  assert.match(source, /\/ai\/chat\/turns\//)
  assert.match(source, /clearTurns\(undefined, scope\)/)
  assert.match(source, /clearQueueState\(undefined, scope\)/)
})

function memoryStorage(init) {
  const data = { ...(init || {}) }
  return {
    getStorageSync(key) {
      return data[key]
    },
    setStorageSync(key, value) {
      data[key] = value
    },
  }
}

test('send queue persists locally and restores after a page switch', () => {
  const storage = memoryStorage()
  const first = enqueueMessage([], '先问成果')
  const second = enqueueMessage(first.queue, '再问需求')
  saveQueueState({ queue: second.queue, inflight: '当前正在生成', draft: '未发出的草稿' }, storage)
  const restored = loadQueueState(storage)
  assert.equal(restored.queue.length, 2)
  assert.equal(restored.queue[0].text, '先问成果')
  assert.equal(restored.queue[1].text, '再问需求')
  assert.equal(restored.inflight, '当前正在生成')
  assert.equal(restored.draft, '未发出的草稿')
  assert.equal(storage.getStorageSync(QUEUE_STORAGE_KEY).queue.length, 2)
})

test('send queue stores an inflight turn id and scopes queued questions by account', () => {
  const storage = memoryStorage({
    tt_auth_mode: 'account',
    tt_current_user: { userId: 7 },
  })
  saveQueueState({ queue: [], inflight: 'in progress', inflightTurnId: 'ai_turn7' }, storage)
  assert.equal(loadQueueState(storage).inflightTurnId, 'ai_turn7')
  assert.equal(loadQueueState(storage, '8').inflight, '')
  assert.equal(storage.getStorageSync(QUEUE_STORAGE_KEY), undefined)
})

test('queue overflow, dequeue and remove keep FIFO order', () => {
  let queue = []
  for (let i = 0; i < 20; i++) {
    const next = enqueueMessage(queue, 'q' + i)
    queue = next.queue
    assert.equal(next.overflow, false)
  }
  const overflow = enqueueMessage(queue, 'too many')
  assert.equal(overflow.overflow, true)
  assert.equal(overflow.queue.length, 20)
  const removed = removeQueueItem(overflow.queue, overflow.queue[1].id)
  assert.equal(removed.length, 19)
  assert.equal(removed[0].text, 'q0')
  assert.equal(removed[1].text, 'q2')
  const dequeued = dequeueMessage(removed)
  assert.equal(dequeued.item.text, 'q0')
  assert.equal(dequeued.queue[0].text, 'q2')
})

test('queued follow-ups collapse after two visible items', () => {
  const queue = ['a', 'b', 'c', 'd'].reduce((list, text) => enqueueMessage(list, text).queue, [])
  const collapsed = previewQueue(queue, false)
  assert.equal(collapsed.collapsed, true)
  assert.equal(collapsed.visible.length, 2)
  assert.equal(collapsed.hiddenCount, 2)
  const expanded = previewQueue(queue, true)
  assert.equal(expanded.collapsed, false)
  assert.equal(expanded.visible.length, 4)
})

test('long chat history keeps welcome plus a tail until expanded', () => {
  const messages = [{ id: 'welcome', role: 'assistant', content: 'hi' }]
  for (let i = 0; i < 16; i++) {
    messages.push({ id: 'm' + i, role: i % 2 ? 'assistant' : 'user', content: String(i) })
  }
  const collapsed = previewChatMessages(messages, false)
  assert.equal(collapsed.collapsed, true)
  assert.equal(collapsed.visible[0].id, 'welcome')
  assert.equal(collapsed.visible.length, 9)
  assert.equal(collapsed.hiddenCount, 8)
  const expanded = previewChatMessages(messages, true)
  assert.equal(expanded.collapsed, false)
  assert.equal(expanded.visible.length, messages.length)
})

test('inflight turn is done only after the matching assistant reply', () => {
  const messages = [
    { id: 'welcome', role: 'assistant', content: 'hi' },
    { role: 'user', content: '找视觉成果' },
    { role: 'assistant', content: '这是结果' },
  ]
  assert.equal(findInflightStatus(messages, '找视觉成果'), 'done')
  assert.equal(findInflightStatus(messages.slice(0, 2), '找视觉成果'), 'pending')
  assert.equal(findInflightStatus(messages, '另一句'), 'missing')
  assert.equal(findInflightStatus(messages, ''), 'idle')
})
