import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import * as chat from '../subpackages/tech-transfer/api/ai-chat.mjs'
import * as queue from '../subpackages/tech-transfer/api/ai-chat-queue.mjs'
import * as wal from '../subpackages/tech-transfer/api/ai-chat-wal.mjs'
import * as pageState from '../subpackages/tech-transfer/api/page-state-cache.mjs'
import { AI_FEATURE_ENABLED } from '../config/feature-flags.js'

function createPage(storage = {}) {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  const bindings = {
    ...chat,
    ...queue,
    ...wal,
    ...pageState,
    AI_FEATURE_ENABLED,
    AppTabbar: {},
    AiGeneratedMark: {},
    uni: {
      getStorageSync(key) { return storage[key] },
      setStorageSync(key, value) { storage[key] = value },
    },
    async getChatHistory() { throw new Error('History service unavailable') },
  }
  const script = source.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/^\s*import[\s\S]*?\sfrom\s+['"][^'"]+['"];?/gm, '')
    .replace('export default', 'return')
  const component = new Function(...Object.keys(bindings), script)(...Object.values(bindings))
  const page = { ...component.data(), $nextTick(callback) { callback() } }
  for (const [name, method] of Object.entries(component.methods)) page[name] = method.bind(page)
  for (const [name, getter] of Object.entries(component.computed)) {
    Object.defineProperty(page, name, { get: getter.bind(page) })
  }
  return { component, page }
}

test('AI match initializes welcome content and composer without a memory cache', () => {
  const { page } = createPage()
  assert.equal(page.aiEnabled, true)
  assert.equal(page.visibleMessages[0].id, 'welcome')
  assert.ok(page.visibleMessages[0].content.includes('南山科转通 AI 助手'))
  assert.equal(page.inputText, '')
  assert.deepEqual(page.pendingQueue, [])
  assert.equal(page.showSuggestions, true)
  assert.equal(page.canSend, false)
  page.onInput({ detail: { value: '/' } })
  assert.equal(page.skillOptions[0].cmd, '/匹配')
  assert.equal(page.canSend, true)
})

test('AI match keeps rendering and restores the account draft when history fails', async () => {
  const { page } = createPage({
    tt_auth_mode: 'account',
    tt_current_user: { userId: 7 },
    'tt_ai_chat_send_queue:7': { draft: '未发送的需求', queue: [] },
  })
  page._alive = true
  page._scope = '7'
  await page.resumeSession()
  assert.equal(page._sessionReady, true)
  assert.equal(page.visibleMessages[0].id, 'welcome')
  assert.equal(page.inputText, '未发送的需求')
  assert.equal(page.canSend, true)
})

test('new AI match page instances do not share drafts or queued messages', () => {
  const { component, page: first } = createPage()
  first.inputText = '当前账号的草稿'
  first.pendingQueue.push({ id: 'queued', text: '当前账号的问题' })
  const second = component.data()
  assert.equal(second.inputText, '')
  assert.deepEqual(second.pendingQueue, [])
  assert.equal(component.computed.showSuggestions.call(second), true)
})
