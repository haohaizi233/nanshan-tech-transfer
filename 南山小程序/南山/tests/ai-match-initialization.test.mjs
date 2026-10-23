import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import * as chat from '../subpackages/tech-transfer/api/ai-chat.mjs'
import * as queue from '../subpackages/tech-transfer/api/ai-chat-queue.mjs'
import * as wal from '../subpackages/tech-transfer/api/ai-chat-wal.mjs'
import * as pageState from '../subpackages/tech-transfer/api/page-state-cache.mjs'
import * as progress from '../subpackages/tech-transfer/api/ai-chat-progress.mjs'
import { AI_FEATURE_ENABLED } from '../config/feature-flags.js'

function createPage(storage = {}, overrides = {}) {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  const bindings = {
    ...chat,
    ...queue,
    ...wal,
    ...pageState,
    ...progress,
    AI_FEATURE_ENABLED,
    AppTabbar: {},
    AiGeneratedMark: {},
    uni: {
      getStorageSync(key) { return storage[key] },
      setStorageSync(key, value) { storage[key] = value },
      removeStorageSync(key) { delete storage[key] },
    },
    async getChatHistory() { throw new Error('History service unavailable') },
    ...overrides,
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

test('recovery exhaustion keeps the pending turn instead of acknowledging uncertain execution', async () => {
  const storage = {}
  const { page } = createPage(storage)
  page._scope = '7'
  page._alive = true
  page._visible = true
  page._recoverAttempts = 3
  wal.beginTurn({ turnId: 'pending-recovery', message: '评估成果' }, pageStorage(storage), '7')
  page.waitForTurnStatus = async () => 'pending'
  page.scheduleTurnRecovery = () => {}
  await page.recoverActiveTurn(wal.loadActiveTurn(pageStorage(storage), '7'))
  assert.equal(wal.loadActiveTurn(pageStorage(storage), '7')?.status, 'pending')
  assert.ok(page.waitNotice.includes('确认'))
})


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
  assert.deepEqual(page.skillOptions.map((s) => s.cmd), ['/评估', '/搜索', '/帮助', '/匹配'])
  assert.equal(page.canSend, true)
})

test('slash menu fills commands without submitting until the user sends', () => {
  const { page } = createPage()
  page.onInput({ detail: { value: '/' } })
  const evaluate = page.skillOptions[0]
  assert.equal(evaluate.takesArgs, true)
  page.onPickSkill(evaluate)
  assert.equal(page.inputText, '/评估 ')
  assert.equal(page.inputFocus, true)
  assert.equal(page.skillOptions.length, 0, 'menu hides while typing arguments')

  const help = { cmd: '/帮助', id: 'help', takesArgs: false }
  page.onPickSkill(help)
  assert.equal(page.inputText, '/帮助')
  page.onSend()
  assert.equal(page.messages[page.messages.length - 1].content.includes('当前可用命令'), true)
})

test('slash commands dispatch to the agent as natural language and help answers locally', () => {
  const { page } = createPage()
  const sent = []
  page.runAgentChat = (text) => { sent.push(text) }
  page.dispatchUserText('/评估 3')
  page.dispatchUserText('/搜索 机器视觉')
  assert.deepEqual(sent, ['/评估 3', '帮我找机器视觉相关的科技成果或技术需求'])
  page.dispatchUserText('/帮助')
  assert.ok(page.messages[page.messages.length - 1].content.includes('/评估 [成果ID/名称]'))
  page.dispatchUserText('/不存在的命令')
  assert.ok(page.messages[page.messages.length - 1].content.includes('未识别的命令'))
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

test('AI cards refresh every visible count in bounded batches without changing chat snapshots', async () => {
  const batches = []
  const { page } = createPage({}, {
    getCardViewCounts: async cards => {
      batches.push(cards)
      return { list: cards.map(card => ({
        ...card, viewCount: card.card_type === 'demand' ? 3 : 12,
      })) }
    },
  })
  page._alive = true
  page._visible = true
  page._scope = 'anonymous'
  page.messages = [{ id: 'reply', payload: { cards: [
    { card_type: 'achievement', id: 42 },
    { card_type: 'achievement', id: 42 },
    { card_type: 'demand', id: 42 },
    ...Array.from({ length: 70 }, (_, index) => ({ card_type: 'achievement', id: index + 100 })),
  ] } }]
  const snapshot = JSON.stringify(page.messages)
  await page.refreshCardViewCounts()
  assert.deepEqual(batches.map(batch => batch.length), [50, 22])
  assert.equal(page.cardViewCount({ card_type: 'achievement', id: 42 }), 12)
  assert.equal(page.cardViewCount({ card_type: 'demand', id: 42 }), 3)
  assert.equal(page.cardViewCount({ card_type: 'achievement', id: 169 }), 12)
  assert.equal(JSON.stringify(page.messages), snapshot)
})

test('AI card count polling starts on return and stops when the page is hidden', async () => {
  let polls = 0
  let stops = 0
  const { component, page } = createPage({}, {
    setInterval: () => { polls++; return 1 },
    clearInterval: () => { stops++ },
  })
  page._alive = true
  page._scope = 'anonymous'
  page._sessionReady = true
  let refreshes = 0
  page.refreshCardViewCounts = async () => { refreshes++ }
  page.restoreScrollPosition = () => {}
  component.onShow.call(page)
  assert.equal(refreshes, 1)
  assert.equal(polls, 1)
  component.onHide.call(page)
  assert.equal(stops, 1)
})

test('late AI card counts are ignored after switching accounts', async () => {
  let resolveCounts
  const storage = {}
  const { page } = createPage(storage, {
    getCardViewCounts: () => new Promise(resolve => { resolveCounts = resolve }),
  })
  page._alive = true
  page._visible = true
  page._scope = 'anonymous'
  page.messages = [{ payload: { cards: [{ card_type: 'achievement', id: 42 }] } }]
  const pending = page.refreshCardViewCounts()
  storage.tt_auth_mode = 'account'
  storage.tt_current_user = { userId: 8 }
  resolveCounts({ list: [{ card_type: 'achievement', id: 42, viewCount: 99 }] })
  await pending
  assert.deepEqual(page.cardViewCounts, {})
})

test('expired pending WAL is queried on return and is never cleared by local age', async () => {
  const storage = {}
  const { component, page } = createPage(storage)
  wal.beginTurn({ turnId: 'old_pending', message: 'question' }, pageStorage(storage), 'anonymous')
  storage['tt_ai_chat_wal_v1:anonymous'].turn.createdAt = 1
  page._alive = true
  page._scope = 'anonymous'
  page._sessionReady = true
  page._requestInFlight = true
  page.startCardStatsRefresh = () => {}
  let queried = ''
  page.recoverActiveTurn = async turn => { queried = turn.turnId }
  component.onShow.call(page)
  assert.equal(queried, 'old_pending')
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').turnId, 'old_pending')
})

test('hiding the page cancels a scheduled chat recovery', () => {
  const stopped = []
  const { component, page } = createPage({}, { clearTimeout: timer => stopped.push(timer) })
  page._scope = 'anonymous'
  page._recoveryTimer = 27
  component.onHide.call(page)
  assert.deepEqual(stopped, [27])
  assert.equal(page._recoveryTimer, null)
})

test('history cards retain a server message ID separately from their local rendering ID', async () => {
  const { page } = createPage({}, { getChatHistory: async () => ({ generation: 4, messages: [
    { id: 81, role: 'assistant', content: '结果', cards: [{ card_type: 'achievement', id: 12 }] },
  ] }) })
  page._scope = 'anonymous'
  await page.loadHistory()
  assert.equal(page.messages[1].id, 'm_81')
  assert.equal(page.messages[1].serverMessageId, 81)
  assert.equal(page.chatGeneration, 4)
})

function pageStorage(storage) {
  return {
    getStorageSync: key => storage[key],
    setStorageSync: (key, value) => { storage[key] = value },
    removeStorageSync: key => { delete storage[key] },
  }
}

test('legacy synchronous replies persist then confirm WAL and do not invent a server message ID', async () => {
  const storage = {}
  const { page } = createPage(storage, {
    chatWithAgent: async () => ({ success: true, message: '旧版回答', data: [{ card_type: 'achievement', id: 12 }] }),
  })
  page._scope = 'anonymous'
  page._alive = true
  page._visible = true
  await page.runAgentChat('问题')
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
  assert.equal(page.messages.at(-1).content, '旧版回答')
  assert.equal(page.referenceForCard(page.messages.at(-1), page.messages.at(-1).payload.cards[0]), null)
  assert.equal(page.typing, false)
})

test('an async reply polls one turn after two seconds and acknowledges only its terminal response', async () => {
  const storage = {}
  const timers = []
  const requests = []
  let turnId
  let clock = 100
  const { page } = createPage(storage, {
    Date: { now: () => clock },
    setTimeout: (callback, delay) => { timers.push({ callback, delay }); return timers.length },
    clearTimeout: () => {},
    chatWithAgent: async (text, id) => {
      requests.push({ text, id }); turnId = id
      return { turnId: id, status: 'running', generation: 2, stage: 'queued', stageSeq: 0 }
    },
    getChatTurn: async id => {
      assert.equal(id, turnId)
      return requests.length === 1
        ? (requests.push({ poll: true }), { turnId: id, status: 'running', generation: 2, stage: 'retrieving', stageSeq: 3 })
        : { turnId: id, status: 'succeeded', generation: 2, stage: 'succeeded', stageSeq: 4, reply: '新回答', cards: [], messageId: 90 }
    },
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  const pending = page.runAgentChat('问题')
  await settle()
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').status, 'pending')
  assert.equal(page.chatProgress.stage, 'retrieving')
  assert.equal(timers[0].delay, 2000)
  clock += 2000
  timers.shift().callback()
  await pending
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
  assert.equal(page.messages.at(-1).content, '新回答')
  assert.equal(page.messages.at(-1).serverMessageId, 90)
  assert.equal(requests.filter(request => request.text).length, 1)
})

test('hidden pages ignore a late poll result and keep pending WAL for the next visit', async () => {
  const storage = {}
  let reply
  const { component, page } = createPage(storage, {
    getChatTurn: () => new Promise(resolve => { reply = resolve }),
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  wal.beginTurn({ turnId: 'hidden', message: '问题' }, pageStorage(storage), 'anonymous')
  const pending = page.recoverActiveTurn(wal.loadActiveTurn(pageStorage(storage), 'anonymous'))
  component.onHide.call(page)
  reply({ turnId: 'hidden', status: 'succeeded', reply: '迟到回答', cards: [] })
  await pending
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').status, 'pending')
  assert.equal(page.messages.some(message => message.content === '迟到回答'), false)
  assert.equal(page._recoveryTimer, null)
})

test('clear generation invalidates an outstanding POST before it can save a terminal result', async () => {
  const storage = {}
  let reply
  const { page } = createPage(storage, {
    chatWithAgent: () => new Promise(resolve => { reply = resolve }),
    clearChatHistory: async () => { wal.clearTurns(pageStorage(storage), 'anonymous'); return { deleted: 2, generation: 3 } },
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  const pending = page.runAgentChat('旧问题')
  await page.clearConversation()
  reply({ success: true, message: '旧结果', data: [] })
  await pending
  assert.equal(page.chatGeneration, 3)
  assert.equal(page.messages.length, 1)
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
})

test('a local wait threshold leaves WAL pending and shows a later-check notice', async () => {
  const storage = {}
  let clock = 1
  const { page } = createPage(storage, {
    Date: { now: () => clock },
    getChatTurn: async id => { clock += 120001; return { turnId: id, status: 'running', stage: 'routing', stageSeq: 1 } },
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  wal.beginTurn({ turnId: 'waiting', message: '问题' }, pageStorage(storage), 'anonymous')
  assert.equal(await page.waitForTurnStatus('waiting', '问题'), 'pending')
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').status, 'pending')
  assert.match(page.progressText, /稍后/)
})

async function settle() {
  for (let step = 0; step < 8; step++) await Promise.resolve()
}

test('returning before session initialization finishes retries the read-only history load', () => {
  const { component, page } = createPage()
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  page._sessionReady = false
  page.startCardStatsRefresh = () => {}
  page.restoreScrollPosition = () => {}
  let resumed = 0
  page.resumeSession = () => { resumed++ }
  component.onShow.call(page)
  assert.equal(resumed, 1)
})

test('a repeated question cannot substitute an earlier answer when history refresh fails', async () => {
  const storage = {}
  const { page } = createPage(storage)
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  page.messages.push(chat.createMessage('user', '重复问题'), chat.createMessage('assistant', '旧回答', { serverMessageId: 30 }))
  wal.beginTurn({ turnId: 'repeat', message: '重复问题' }, pageStorage(storage), 'anonymous')
  await page.saveServerTurn({ turnId: 'repeat', status: 'succeeded', reply: '本轮回答', cards: [], messageId: 31 })
  assert.equal(page.messages.at(-1).content, '本轮回答')
  assert.equal(page.messages.at(-1).serverMessageId, 31)
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
})

test('reloading progress uses the WAL sequence to reject an older terminal response', () => {
  const storage = {}
  const { page } = createPage(storage)
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  wal.beginTurn({ turnId: 'ordered', message: '问题' }, pageStorage(storage), 'anonymous')
  wal.saveTurnProgress('ordered', { generation: 2, stage: 'retrieving', stageSeq: 4 }, pageStorage(storage), 'anonymous')
  assert.equal(page.acceptChatProgress({ turnId: 'ordered', generation: 2, status: 'succeeded', stage: 'succeeded', stageSeq: 3 }, 'ordered'), false)
  assert.equal(page.chatProgress.stage, 'retrieving')
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').status, 'pending')
})

test('only current-generation durable cards are referenceable when the server capability is enabled', async () => {
  const cards = [{ card_type: 'achievement', id: 12 }]
  const { page } = createPage({}, { getChatHistory: async () => ({ generation: 4, referenceSupported: true, messages: [
    { id: 81, role: 'assistant', content: '旧同步结果', cards },
    { id: 82, role: 'assistant', content: '可引用结果', cards, turnId: 'durable', generation: 4 },
  ] }) })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  await page.loadHistory()
  assert.equal(page.referenceForCard(page.messages[1], cards[0]), null)
  assert.deepEqual(page.referenceForCard(page.messages[2], cards[0]), { messageId: 82, cardType: 'achievement', cardId: 12 })
  page.referenceSupported = false
  assert.equal(page.referenceForCard(page.messages[2], cards[0]), null)
  page.referenceSupported = true
  page.chatGeneration = 5
  assert.equal(page.referenceForCard(page.messages[2], cards[0]), null)
})

test('the shared history API contract restores referenceable cards on a fresh page', async () => {
  const response = JSON.parse(readFileSync(new URL('./fixtures/ai-chat-history-contract.json', import.meta.url), 'utf8'))
  const apiSource = readFileSync(new URL('../subpackages/tech-transfer/api/ai.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace(/export /g, '')
  const clientSource = readFileSync(new URL('../subpackages/tech-transfer/api/client.js', import.meta.url), 'utf8')
  const requestScript = clientSource.slice(clientSource.indexOf('export async function apiRequest'), clientSource.indexOf('export async function publicRequest')).replace('export ', '')
  const request = new Function('ensureSession', 'HostBridge', requestScript + '; return apiRequest')(
    async () => {}, { request: async options => {
      assert.equal(options.method, 'GET')
      assert.equal(options.path, '/ai/chat/messages')
      return { code: 0, data: response }
    } },
  )
  const getChatHistory = new Function('apiRequest', 'AI_FEATURE_ENABLED', apiSource + '; return getChatHistory')(request, true)
  const { page } = createPage({}, { getChatHistory })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  await page.resumeSession()
  assert.equal(page.chatGeneration, 4)
  assert.equal(page.referenceSupported, true)
  assert.deepEqual(page.referenceForCard(page.messages[1], page.messages[1].payload.cards[0]), {
    messageId: 82, cardType: 'achievement', cardId: 12,
  })
})

test('a durable terminal response preserves reference metadata even when history is unavailable', async () => {
  const card = { card_type: 'achievement', id: 12 }
  const { page } = createPage({}, { chatWithAgent: async (text, turnId) => ({
    turnId, generation: 4, status: 'succeeded', stage: 'succeeded', stageSeq: 8,
    messageId: 99, reply: '回答', cards: [card], referenceSupported: true,
  }) })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  await page.runAgentChat('问题')
  assert.deepEqual(page.referenceForCard(page.messages.at(-1), card), { messageId: 99, cardType: 'achievement', cardId: 12 })
})

test('clear completion while hidden resets typing and allows sending after returning', async () => {
  const storage = {}
  let finishClear
  const { component, page } = createPage(storage, {
    clearChatHistory: () => new Promise(resolve => { finishClear = () => {
      wal.clearTurns(pageStorage(storage), 'anonymous')
      queue.clearQueueState(pageStorage(storage), 'anonymous')
      resolve({ deleted: 2, generation: 2 })
    } }),
    getChatHistory: async () => ({ messages: [], generation: 2, referenceSupported: true }),
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true; page._sessionReady = true
  page.startCardStatsRefresh = () => {}
  page.restoreScrollPosition = () => {}
  const pending = page.clearConversation()
  component.onHide.call(page)
  finishClear()
  await pending
  component.onShow.call(page)
  await settle()
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
  assert.equal(page.chatGeneration, 2)
  assert.equal(page.typing, false)
  let sent
  page.dispatchUserText = text => { sent = text }
  page.inputText = '清空后的问题'
  page.onSend()
  assert.equal(sent, '清空后的问题')
  assert.deepEqual(page.pendingQueue, [])
})

test('resuming without a WAL releases stale typing state', async () => {
  const { page } = createPage({}, { getChatHistory: async () => ({ messages: [], generation: 2, referenceSupported: true }) })
  page._scope = 'anonymous'; page._alive = true; page._visible = true; page.typing = true
  page.recoveringTurn = true
  await page.resumeSession()
  assert.equal(page.typing, false)
  assert.equal(page.recoveringTurn, false)
})

test('resuming a cleared WAL releases typing even when the send queue retains an interrupted question', async () => {
  const storage = { tt_ai_chat_send_queue: { queue: [], inflight: '已清空的问题', inflightTurnId: 'cleared' } }
  const { page } = createPage(storage, { getChatHistory: async () => ({ messages: [], generation: 2, referenceSupported: true }) })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  page.typing = true; page.recoveringTurn = true
  await page.resumeSession()
  assert.equal(page.typing, false)
  assert.equal(page.recoveringTurn, false)
  assert.equal(page.inflightTurnId, '')
  let sent
  page.dispatchUserText = text => { sent = text }
  page.inputText = '下一问'
  page.onSend()
  assert.equal(sent, '下一问')
})

test('returning during a clear keeps sending paused until the authoritative clear finishes', async () => {
  const storage = {}
  let finishClear
  const { component, page } = createPage(storage, {
    clearChatHistory: () => new Promise(resolve => { finishClear = () => resolve({ deleted: 0, generation: 2 }) }),
    getChatHistory: async () => ({ messages: [], generation: 1, referenceSupported: true }),
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true; page._sessionReady = true
  page.startCardStatsRefresh = () => {}
  const pending = page.clearConversation()
  component.onHide.call(page)
  component.onShow.call(page)
  await settle()
  assert.equal(page.typing, true)
  finishClear()
  await pending
  assert.equal(page.typing, false)
  assert.equal(page.chatGeneration, 2)
})

test('a new turn accepts the current server generation after another device clears history', async () => {
  const storage = {}
  const { page } = createPage(storage, {
    chatWithAgent: async (text, turnId) => ({ turnId, generation: 2, status: 'running', stage: 'queued', stageSeq: 0 }),
    getChatTurn: async turnId => {
      assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').generation, 2)
      return { turnId, generation: 2, status: 'succeeded', stage: 'succeeded', stageSeq: 3, reply: '新代际回答', cards: [] }
    },
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true; page.chatGeneration = 1
  await page.runAgentChat('新问题')
  assert.equal(page.chatGeneration, 2)
  assert.equal(page.messages.at(-1).content, '新代际回答')
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
  assert.equal(page.typing, false)
})

test('reentering can confirm a new generation for a WAL whose POST acceptance was lost', async () => {
  const storage = {}
  wal.beginTurn({ turnId: 'accepted_elsewhere', message: '新问题', generation: 1 }, pageStorage(storage), 'anonymous')
  let clock = 1
  const { page } = createPage(storage, {
    Date: { now: () => clock },
    getChatHistory: async () => ({ generation: 2, referenceSupported: true, messages: [] }),
    getChatTurn: async turnId => { clock += 120001; return { turnId, generation: 2, status: 'succeeded', stage: 'succeeded', stageSeq: 3, reply: '恢复回答', cards: [] } },
    setTimeout: () => 1,
    clearTimeout: () => {},
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  await page.resumeSession()
  assert.equal(page.messages.at(-1).content, '恢复回答')
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
  assert.equal(page.typing, false)
})

test('a confirmed generation cannot be replaced by a different generation on recovery', () => {
  const storage = {}
  const { page } = createPage(storage)
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  wal.beginTurn({ turnId: 'confirmed', message: '旧问题', generation: 1 }, pageStorage(storage), 'anonymous')
  wal.saveTurnProgress('confirmed', { generation: 1, stage: 'retrieving', stageSeq: 2 }, pageStorage(storage), 'anonymous')
  assert.equal(page.acceptChatProgress({ turnId: 'confirmed', generation: 2, status: 'succeeded', stageSeq: 3 }, 'confirmed'), false)
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').generation, 1)
})

test('a known unaccepted rejection releases WAL and permits the next question without polling', async () => {
  const storage = {}
  let polls = 0
  const { page } = createPage(storage, {
    chatWithAgent: async () => { throw Object.assign(new Error('请求太频繁，请稍后重试'), { code: 'TT_COMMON_42901', status: 429, details: { accepted: false } }) },
    getChatTurn: async turnId => { polls++; return { turnId, status: 'failed', errorMessage: '不应轮询' } },
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  await page.runAgentChat('被拒绝的问题')
  assert.equal(polls, 0)
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous'), null)
  assert.match(page.messages.at(-1).content, /请求太频繁/)
  assert.equal(page.typing, false)
  let sent
  page.dispatchUserText = text => { sent = text }
  page.inputText = '下一问'
  page.onSend()
  assert.equal(sent, '下一问')
})

test('an unknown POST outcome keeps WAL and checks status without resending even after a 404', async () => {
  const storage = {}
  let posts = 0
  let polls = 0
  let clock = 1
  const { page } = createPage(storage, {
    Date: { now: () => clock },
    chatWithAgent: async () => { posts++; throw new Error('network disconnected') },
    getChatTurn: async () => { polls++; clock += 120001; throw Object.assign(new Error('not found'), { status: 404 }) },
    setTimeout: () => 1,
    clearTimeout: () => {},
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  await page.runAgentChat('结果未知的问题')
  assert.equal(posts, 1)
  assert.equal(polls, 1)
  assert.equal(wal.loadActiveTurn(pageStorage(storage), 'anonymous').status, 'pending')
  assert.equal(page.recoveringTurn, true)
})
