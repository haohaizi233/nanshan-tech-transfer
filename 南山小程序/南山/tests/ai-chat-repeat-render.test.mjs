import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { createSSRApp } from 'vue'
import { compileTemplate, parse } from 'vue/compiler-sfc'
import * as serverRenderer from '@vue/server-renderer'
import { renderToString } from '@vue/server-renderer'

import * as chat from '../subpackages/tech-transfer/api/ai-chat.mjs'
import * as queue from '../subpackages/tech-transfer/api/ai-chat-queue.mjs'
import * as wal from '../subpackages/tech-transfer/api/ai-chat-wal.mjs'
import * as pageState from '../subpackages/tech-transfer/api/page-state-cache.mjs'
import * as progress from '../subpackages/tech-transfer/api/ai-chat-progress.mjs'
import { createChatEvaluationMonitor, createChatEvaluationReader } from '../subpackages/tech-transfer/api/ai-chat-evaluations.mjs'
import { extractStreamData } from '../subpackages/tech-transfer/api/ai-eval-stream.mjs'
import { AI_FEATURE_ENABLED } from '../config/feature-flags.js'

function pageStorage(values = {}) {
  return {
    values,
    getStorageSync(key) { return values[key] },
    setStorageSync(key, value) { values[key] = value },
    removeStorageSync(key) { delete values[key] },
  }
}

function createPage(storage = {}, overrides = {}) {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  const store = pageStorage(storage)
  const bindings = {
    ...chat,
    ...queue,
    ...wal,
    ...pageState,
    ...progress,
    createChatEvaluationMonitor,
    readChatEvaluationTask: createChatEvaluationReader(),
    extractStreamData,
    openEvalTaskStream() { return null },
    getEvaluationTask() { return new Promise(() => {}) },
    AI_FEATURE_ENABLED,
    AppTabbar: {},
    AiGeneratedMark: {},
    uni: store,
    async getChatHistory() { throw new Error('History service unavailable') },
    ...overrides,
  }
  const script = source.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/^\s*import[\s\S]*?\sfrom\s+['"][^'"]+['"];?/gm, '')
    .replace('export default', 'return')
  const component = new Function(...Object.keys(bindings), script)(...Object.values(bindings))
  const initialData = component.data()
  const page = { ...initialData, $nextTick(callback) { callback() } }
  for (const [name, method] of Object.entries(component.methods)) page[name] = method.bind(page)
  for (const [name, getter] of Object.entries(component.computed)) {
    Object.defineProperty(page, name, { get: getter.bind(page), enumerable: true })
  }
  return { component, page, store, initialData }
}

async function renderVuePage(pageInstance) {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )
  const parsed = parse(source)
  const compiled = compileTemplate({
    id: 'ai-match-test',
    source: parsed.descriptor.template.content,
    filename: 'ai-match.vue',
    ssr: true,
    compilerOptions: {
      isCustomElement: (tag) => tag !== 'rich-text',
    },
  })
  if (compiled.errors.length) {
    throw new Error('Template compile errors: ' + compiled.errors.join(', '))
  }

  const transformed = compiled.code
    .replace(/import\s*\{([\s\S]*?)\}\s*from\s*['"]vue['"];?/g, (m, g) => {
      const bindings = g.split(',').map((s) => {
        const parts = s.trim().split(/\s+as\s+/)
        return parts.length === 2 ? `${parts[0]}: ${parts[1]}` : parts[0]
      }).join(', ')
      return `const { ${bindings} } = vue;`
    })
    .replace(/import\s*\{([\s\S]*?)\}\s*from\s*['"]vue\/server-renderer['"];?/g, (m, g) => {
      const bindings = g.split(',').map((s) => {
        const parts = s.trim().split(/\s+as\s+/)
        return parts.length === 2 ? `${parts[0]}: ${parts[1]}` : parts[0]
      }).join(', ')
      return `const { ${bindings} } = serverRenderer;`
    })
    .replace('export function ssrRender', 'return function ssrRender')

  const createRender = new Function('vue', 'serverRenderer', transformed)
  const ssrRender = createRender(vue, serverRenderer)

  // Extract non-function properties from pageInstance, excluding computeds
  const pageData = {}
  for (const key of Object.getOwnPropertyNames(pageInstance)) {
    if (typeof pageInstance[key] !== 'function') {
      pageData[key] = pageInstance[key]
    }
  }
  delete pageData.chatPreview
  delete pageData.queuePreview
  delete pageData.renderMessages
  delete pageData.activeQuickQuestions

  const app = createSSRApp({
    components: {
      // 模拟 uni-app 的节点渲染，普通 SSR 不会展开 rich-text 的 nodes 属性。
      'rich-text': {
        props: ['nodes'],
        render() {
          const renderNode = (node) => node.type === 'text'
            ? node.text
            : vue.h(node.name, node.attrs || {}, (node.children || []).map(renderNode))
          return vue.h('div', (this.nodes || []).map(renderNode))
        },
      },
    },
    ssrRender,
    data() {
      return pageData
    },
    methods: {
      formatReplyNodes: pageInstance.formatReplyNodes.bind(pageInstance),
      isCommandMessage: pageInstance.isCommandMessage ? pageInstance.isCommandMessage.bind(pageInstance) : () => false,
      bubbleClass: pageInstance.bubbleClass ? pageInstance.bubbleClass.bind(pageInstance) : () => 'bubble',
      displayText: pageInstance.displayText ? pageInstance.displayText.bind(pageInstance) : (m) => m?.content,
      cardViewCount: pageInstance.cardViewCount ? pageInstance.cardViewCount.bind(pageInstance) : () => 0,
      dimensionLabel: pageInstance.dimensionLabel ? pageInstance.dimensionLabel.bind(pageInstance) : (k) => k,
      referenceForCard: pageInstance.referenceForCard ? pageInstance.referenceForCard.bind(pageInstance) : () => null,
      openCard: pageInstance.openCard ? pageInstance.openCard.bind(pageInstance) : () => {},
      pickEvaluate: pageInstance.pickEvaluate ? pageInstance.pickEvaluate.bind(pageInstance) : () => {},
      introduceCard: pageInstance.introduceCard ? pageInstance.introduceCard.bind(pageInstance) : () => {},
      goPostDemand: pageInstance.goPostDemand ? pageInstance.goPostDemand.bind(pageInstance) : () => {},
      onPickDemand: pageInstance.onPickDemand ? pageInstance.onPickDemand.bind(pageInstance) : () => {},
      onHelpCommand: pageInstance.onHelpCommand ? pageInstance.onHelpCommand.bind(pageInstance) : () => {},
      onSuggest: pageInstance.onSuggest ? pageInstance.onSuggest.bind(pageInstance) : () => {},
    },
    computed: {
      chatPreview() {
        return pageInstance.chatPreview || { collapsed: false, hiddenCount: 0, canCollapse: false, visible: this.messages || [] }
      },
      queuePreview() {
        return pageInstance.queuePreview || { collapsed: false, items: [] }
      },
      renderMessages() {
        return pageInstance.renderMessages || pageInstance.messages || []
      },
      activeQuickQuestions() {
        return pageInstance.activeQuickQuestions || []
      },
    },
  })

  return renderToString(app)
}

test('Test 1: AI 成果卡片正文恰好渲染一次，卡片及交互入口完整保留', async () => {
  const source = readFileSync(
    new URL('../subpackages/tech-transfer/pages/ai-match/ai-match.vue', import.meta.url),
    'utf8',
  )

  // 1. 静态模板检查：agent-cards__intro 必须被彻底删除，不得残留于 template 或 style 中
  assert.equal(source.includes('agent-cards__intro'), false, '模板与样式中不应存在 agent-cards__intro')

  // 2. 检查 agent-cards-scroll 容器内只有卡片循环，无重复文本节点
  const scrollMatch = source.match(/<view[^>]*class="[^"]*agent-cards-scroll[^"]*"[^>]*>([\s\S]*?)<\/view>\s*<\/view>\s*<\/view>/)
  assert.ok(scrollMatch, '应该找到 agent-cards-scroll 容器')
  const scrollInner = scrollMatch[1]
  assert.equal(scrollInner.includes('msg.content'), false, 'agent-cards-scroll 内部不应再绑定 msg.content')

  // 3. 构造标准成果卡片消息并渲染 DOM
  const { page } = createPage()
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  const cardMessage = {
    id: 'test-agent-card',
    role: 'assistant',
    type: 'agent-cards',
    content: '为您介绍 9 项科技成果',
    payload: {
      cards: [
        { id: 1, card_type: 'achievement', title: '成果A', advisorSummary: '摘要A' },
        { id: 2, card_type: 'achievement', title: '成果B', advisorSummary: '摘要B' },
      ],
    },
  }
  page.messages = [cardMessage]

  const html = await renderVuePage(page)

  // 断言 AI 正文恰好渲染一次
  const contentMatches = [...html.matchAll(/为您介绍 9 项科技成果/g)]
  assert.equal(contentMatches.length, 1, `AI 正文必须恰好渲染一次，实际渲染了 ${contentMatches.length} 次`)

  // 正文位于卡片列表前的富文本区域。
  assert.match(html, /class="reply-rich-text panel__reply"[^>]*><div[^>]*>为您介绍 9 项科技成果<\/div>/)

  // 断言两张成果卡片全部渲染
  assert.match(html, /成果A/)
  assert.match(html, /成果B/)
  const cardMatches = [...html.matchAll(/class="agent-card"/g)]
  assert.equal(cardMatches.length, 2, '两张成果卡片应全部渲染')

  // 断言交互入口与滚动容器存在
  assert.match(html, /class="agent-cards-scroll"/)
  assert.equal(typeof page.openCard, 'function')
  assert.equal(typeof page.introduceCard, 'function')
  assert.equal(typeof page.pickEvaluate, 'function')
})

test('Test 2: 普通文字消息正常渲染，AI 文字不会因修复卡片模板而消失', async () => {
  const { page } = createPage()
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  const textMessage = {
    id: 'test-text-bot',
    role: 'assistant',
    type: 'text',
    content: '这是一条普通的AI文本回复',
  }
  page.messages = [textMessage]

  const html = await renderVuePage(page)
  const matches = [...html.matchAll(/这是一条普通的AI文本回复/g)]
  assert.equal(matches.length, 1, '普通文本回复应恰好渲染一次')
  assert.match(html, /class="reply-rich-text"[^>]*><div[^>]*>这是一条普通的AI文本回复<\/div>/)
})

test('Test 3: 命令帮助消息无重复正文，点击命令卡片填入输入框而不自动发送', async () => {
  const { page } = createPage()
  page._scope = 'anonymous'; page._alive = true; page._visible = true
  const helpMessage = {
    id: 'test-help-commands',
    role: 'assistant',
    type: 'help-commands',
    content: '这里是命令帮助描述文本',
    payload: {
      commands: [
        { id: 'evaluate', icon: '📊', label: '/评估', cmd: '/评估', desc: '评估科技成果', usage: '/评估 3' },
        { id: 'search', icon: '🔍', label: '/搜索', cmd: '/搜索', desc: '搜索科技成果', usage: '/搜索 机器视觉' },
      ],
    },
  }
  page.messages = [helpMessage]

  const html = await renderVuePage(page)
  // help-commands 在模板中有 v-if="msg.content && msg.type !== 'help-commands'"，正文不应进入 panel__text 造成重复
  assert.equal(html.includes('panel__text'), false, 'help-commands 不应渲染 panel__text 节点')
  assert.match(html, /当前可用命令/)
  assert.match(html, /\/评估/)
  assert.match(html, /\/搜索/)
  assert.match(html, /点击命令卡片填入输入框，补充参数后发送/)

  // 测试交互：点击命令填入输入框，不自动发送
  page.inputText = ''
  const prevMsgCount = page.messages.length
  page.onHelpCommand({ id: 'evaluate', cmd: '/评估', usage: '/评估 仿生灵巧手' })
  assert.equal(page.inputText, '/评估 ')
  assert.equal(page.messages.length, prevMsgCount, '点击命令不应自动发送消息')
})

test('Test 4: 历史恢复流程，正文不重复、卡片数量不变、顺序正确且无额外网络请求', async () => {
  const storage = {}
  const cards = [
    { id: 101, card_type: 'achievement', title: '成果101' },
    { id: 102, card_type: 'achievement', title: '成果102' },
  ]
  let networkCallCount = 0
  const historyData = {
    generation: 5,
    referenceSupported: true,
    messages: [
      { id: 1, role: 'user', content: '找仿生手成果' },
      { id: 2, role: 'assistant', content: '为您找到2项仿生手成果', cards, turnId: 'turn-4' },
    ],
  }

  const { page, store } = createPage(storage, {
    getChatHistory: async () => {
      networkCallCount++
      return historyData
    },
  })
  page._scope = 'anonymous'; page._alive = true; page._visible = true

  // 模拟发送问题 -> 接收成果卡片 -> 保存服务端消息
  wal.beginTurn({ turnId: 'turn-4', message: '找仿生手成果' }, store, 'anonymous')
  page.ensureLocalUserMessage('找仿生手成果')
  const saved = await page.saveServerTurn({
    turnId: 'turn-4',
    status: 'succeeded',
    reply: '为您找到2项仿生手成果',
    cards,
    messageId: 2,
    generation: 5,
  })
  assert.equal(saved, true)

  // 卸载前检查
  assert.equal(page.messages.length, 3, '包含欢迎语+用户消息+AI助手卡片消息')
  assert.equal(page.messages[2].type, 'agent-cards')
  assert.equal(page.messages[2].payload.cards.length, 2)

  // 模拟页面卸载
  page._alive = false
  page._visible = false

  // 记录重新打开前网络请求数
  const callsBeforeReload = networkCallCount

  // 模拟页面重新打开并恢复历史
  const { page: newPage } = createPage(storage, {
    getChatHistory: async () => {
      networkCallCount++
      return historyData
    },
  })
  newPage._scope = 'anonymous'; newPage._alive = true; newPage._visible = true
  const success = await newPage.loadHistory()
  assert.equal(success, true)
  assert.equal(networkCallCount, callsBeforeReload + 1, '加载历史应只触发一次历史拉取请求')

  // 验证恢复后的消息列表
  assert.equal(newPage.messages.length, 3, '恢复后应为欢迎语 + 1 条用户提问 + 1 条卡片回复')
  assert.equal(newPage.messages[0].role, 'assistant') // 欢迎语
  assert.equal(newPage.messages[1].role, 'user')
  assert.equal(newPage.messages[1].content, '找仿生手成果')
  assert.equal(newPage.messages[2].role, 'assistant')
  assert.equal(newPage.messages[2].content, '为您找到2项仿生手成果')
  assert.equal(newPage.messages[2].type, 'agent-cards')
  assert.equal(newPage.messages[2].payload.cards.length, 2)

  // 验证渲染后正文不重复
  const html = await renderVuePage(newPage)
  const matches = [...html.matchAll(/为您找到2项仿生手成果/g)]
  assert.equal(matches.length, 1, '恢复历史后正文必须恰好渲染一次')
})

test('Test 5: 异步轮询恢复流程 (queued -> running -> succeeded -> WAL确认) 终态回复与卡片只出现一次', async () => {
  const storage = {}
  const cards = [
    { id: 201, card_type: 'achievement', title: '异步成果1' },
    { id: 202, card_type: 'achievement', title: '异步成果2' },
  ]
  const { page, store } = createPage(storage)
  page._scope = 'anonymous'; page._alive = true; page._visible = true

  // 1. 开始轮次 (queued) 并记录 WAL
  const started = wal.beginTurn({ turnId: 'turn-async-1', message: '介绍柔性夹爪' }, store, 'anonymous')
  assert.equal(started, true)
  assert.equal(wal.loadActiveTurn(store, 'anonymous').status, 'pending')

  // 2. 轮询过程推进 (running / stage 进度更新)
  wal.saveTurnProgress('turn-async-1', { generation: 1, stage: 'retrieving', stageSeq: 1 }, store, 'anonymous')
  assert.equal(wal.loadActiveTurn(store, 'anonymous').status, 'pending')

  // 3. 成功终态 (succeeded)
  const saveSuccess = await page.saveServerTurn({
    turnId: 'turn-async-1',
    status: 'succeeded',
    reply: '已为您找到柔性夹爪相关成果',
    cards,
    messageId: 88,
  })
  assert.equal(saveSuccess, true)

  // 4. 断言 WAL 确认已完成 (active turn 已清理)
  assert.equal(wal.loadActiveTurn(store, 'anonymous'), null, '成功处理后 WAL 必须被确认清理')

  // 5. 断言页面消息只有一条 assistant 回复且卡片数量一致
  const assistantMsgs = page.messages.filter((m) => m.role === 'assistant' && m.type === 'agent-cards')
  assert.equal(assistantMsgs.length, 1, '终态回复只出现一次')
  assert.equal(assistantMsgs[0].serverTurnId, 'turn-async-1')
  assert.equal(assistantMsgs[0].serverMessageId, 88)
  assert.equal(assistantMsgs[0].payload.cards.length, 2)

  // 6. 验证渲染不重复
  const html = await renderVuePage(page)
  const matches = [...html.matchAll(/已为您找到柔性夹爪相关成果/g)]
  assert.equal(matches.length, 1, '终态回复正文恰好渲染一次')
})

test('Test 6: 重复通知与幂等性：同一 turnId 收到两次成功通知，不重复插入且旧状态不覆盖', async () => {
  const storage = {}
  const cards = [
    { id: 301, card_type: 'achievement', title: '幂等成果' },
  ]
  const { page, store } = createPage(storage)
  page._scope = 'anonymous'; page._alive = true; page._visible = true

  wal.beginTurn({ turnId: 'turn-idempotent', message: '测试幂等' }, store, 'anonymous')

  // 第一次成功通知
  const firstSave = await page.saveServerTurn({
    turnId: 'turn-idempotent',
    status: 'succeeded',
    reply: '首次完成回复',
    cards,
    messageId: 99,
  })
  assert.equal(firstSave, true)
  const messageCountAfterFirst = page.messages.length

  // 第二次收到相同 turnId 的成功通知 (由于已经确认清理 WAL，saveServerTurn 返回 false 且不重复插入)
  const secondSave = await page.saveServerTurn({
    turnId: 'turn-idempotent',
    status: 'succeeded',
    reply: '首次完成回复',
    cards,
    messageId: 99,
  })
  assert.equal(secondSave, false, '已确认的轮次再次调用 saveServerTurn 应被幂等拒绝')
  assert.equal(page.messages.length, messageCountAfterFirst, '重复通知不得再次插入新消息')

  // 模拟兜底 presentOrphanTurn 收到相同 messageId 通知
  page.presentOrphanTurn({
    turnId: 'turn-idempotent',
    messageId: 99,
    status: 'succeeded',
    reply: '首次完成回复',
    cards,
  }, '测试幂等')
  assert.equal(page.messages.length, messageCountAfterFirst, 'presentOrphanTurn 收到已展示消息不得重复插入')

  // 已确认的服务端结果不能被后到的旧状态覆盖：
  // 1. 尝试以 running 状态保存旧结果到 WAL，WAL 必须拒绝
  const overwriteResult = wal.saveTurnResult('turn-idempotent', { content: '晚到的旧结果' }, 'running', store, 'anonymous')
  assert.equal(overwriteResult, false, 'WAL 必须拒绝用非终态覆盖已完成轮次')

  // 2. 尝试向已清理的 WAL 写入旧进度
  const overwriteProgress = wal.saveTurnProgress('turn-idempotent', { generation: 1, stageSeq: 0 }, store, 'anonymous')
  assert.equal(overwriteProgress, false, 'WAL 必须拒绝向已清理轮次写入进度')

  // 3. 检查消息中的回复正文与卡片没有被篡改
  const targetMsg = page.messages.find((m) => m.serverTurnId === 'turn-idempotent')
  assert.ok(targetMsg)
  assert.equal(targetMsg.content, '首次完成回复')
  assert.equal(targetMsg.payload.cards.length, 1)
})
